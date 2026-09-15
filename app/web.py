from __future__ import annotations

import hmac
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.auth import AuthService
from app.bale import main_menu_keyboard, parse_callback_update, parse_private_update
from app.db import session_scope
from app.models import Entry, ExtractedRecord, Reminder, User
from app.pipeline import process_entry
from app.reports import CATEGORY_ICONS, CATEGORY_LABELS, build_digest, period_bounds
from app.repositories import EntryRepository, UserRepository
from app.services import reprocess_entry
from app.time_utils import format_persian_date, format_persian_datetime

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["persian_datetime"] = format_persian_datetime
templates.env.globals["persian_date"] = format_persian_date
templates.env.globals["labels"] = CATEGORY_LABELS
templates.env.globals["icons"] = CATEGORY_ICONS


def _now() -> datetime:
    return datetime.now(UTC)


def _session_user(request: Request):
    session_id = request.cookies.get("self_session")
    if not session_id:
        return None, None, None
    with session_scope(request.app.state.engine) as session:
        auth = AuthService(
            session,
            request.app.state.settings.session_secret,
            request.app.state.settings.app_base_url,
        )
        user_id = auth.get_session_user(session_id, _now())
        if user_id is None:
            return None, None, None
        user = session.get(User, user_id)
        # The raw CSRF value is held in a non-HttpOnly cookie and is read by forms.
        raw_csrf = request.cookies.get("self_csrf")
        return user, session_id, raw_csrf


def _render(request: Request, template: str, **context):
    user, session_id, csrf = _session_user(request)
    if user is None:
        return RedirectResponse("/", status_code=303)
    context.update(user=user, csrf=csrf or "")
    return templates.TemplateResponse(request=request, name=template, context=context)


async def _answer_callback(bale, query_id: str, text: str) -> None:
    answer = getattr(bale, "answer_callback_query", None)
    if answer is not None:
        await answer(query_id, text)


def _dashboard_markup(auth: AuthService, token: str) -> dict:
    return {
        "inline_keyboard": [[{"text": "📊 ورود به سامانه", "url": auth.dashboard_url(token)}]]
    }


def register_routes(app: FastAPI) -> None:
    @app.post("/bale/webhook/{secret:path}")
    async def bale_webhook(secret: str, request: Request):
        if not hmac.compare_digest(secret, request.app.state.settings.bale_webhook_secret):
            raise HTTPException(status_code=404, detail="Not found")
        payload = await request.json()
        callback = parse_callback_update(payload)
        if callback is not None:
            parts = callback.data.split(":")
            if len(parts) != 3 or not parts[2].isdigit():
                await _answer_callback(request.app.state.bale, callback.query_id, "دستور نامعتبر است")
                return {"ok": True}
            kind, action, object_id = parts[0], parts[1], int(parts[2])
            with session_scope(request.app.state.engine) as session:
                user = session.scalar(select(User).where(User.bale_chat_id == callback.chat_id))
                if user is None or (callback.user_id is not None and user.bale_user_id not in {None, callback.user_id}):
                    await _answer_callback(request.app.state.bale, callback.query_id, "دسترسی مجاز نیست")
                    return {"ok": True}
                repository = EntryRepository(session)
                if kind == "entry" and action == "edit":
                    changed = repository.request_entry_edit(object_id, user.id)
                    message = "✏️ متن اصلاح‌شدهٔ همین ثبت را در پیام بعدی بفرست."
                elif kind == "entry" and action == "delete":
                    changed = repository.soft_delete_entry(object_id, user.id)
                    message = "🗑 ثبت حذف شد." if changed else "⚠️ این ثبت پیدا نشد یا قبلاً حذف شده است."
                elif kind == "reminder" and action in {"done", "cancel"}:
                    changed = repository.update_reminder_status(
                        object_id, user.id, "done" if action == "done" else "cancelled"
                    )
                    message = "✅ یادآوری به‌روزرسانی شد." if changed else "⚠️ یادآوری پیدا نشد."
                elif kind == "reminder" and action == "tomorrow":
                    reminder = session.scalar(
                        select(Reminder).where(
                            Reminder.id == object_id,
                            Reminder.user_id == user.id,
                            Reminder.deleted_at.is_(None),
                        )
                    )
                    if reminder is None:
                        changed = False
                        message = "⚠️ یادآوری پیدا نشد."
                    else:
                        local_due = reminder.due_at.replace(tzinfo=UTC).astimezone(ZoneInfo(user.timezone))
                        changed = repository.snooze_reminder(
                            object_id,
                            user.id,
                            (local_due + timedelta(days=1)).astimezone(UTC),
                        )
                        message = "🔁 یادآوری برای فردا تنظیم شد."
                else:
                    changed = False
                    message = "ℹ️ این دکمه هنوز فعال نشده است."
                if changed:
                    session.commit()
            await _answer_callback(request.app.state.bale, callback.query_id, message)
            if kind == "entry" and action == "delete":
                editor = getattr(request.app.state.bale, "edit_message_text", None)
                if editor is not None:
                    await editor(callback.chat_id, callback.message_id, message)
            return {"ok": True}
        message = parse_private_update(payload)
        if message is None:
            return {"ok": True}

        with session_scope(request.app.state.engine) as session:
            user = UserRepository(session).get_or_create_by_bale_chat(
                message.chat_id, message.display_name, message.user_id
            )
            if message.kind == "text" and message.text in {
                "/start", "📊 ورود به سامانه", "ورود به سامانه"
            }:
                auth = AuthService(
                    session,
                    request.app.state.settings.session_secret,
                    request.app.state.settings.app_base_url,
                )
                token = auth.create_dashboard_token(user.id, _now())
                session.commit()
                await request.app.state.bale.send_message(
                    user.bale_chat_id,
                    "📊 برای ورود به سامانه، دکمهٔ زیر را بزن:",
                    reply_markup=_dashboard_markup(auth, token),
                )
                await request.app.state.bale.send_message(
                    user.bale_chat_id, "✅ آماده‌ام.", reply_markup=main_menu_keyboard()
                )
                return JSONResponse({"ok": True})
            if message.kind == "text" and message.text == "❓ راهنما":
                session.commit()
                await request.app.state.bale.send_message(
                    user.bale_chat_id,
                    "📘 راهنمای صندوقچه\n\n"
                    "🎙 هر چیزی را با ویس یا متن بفرست؛ من آن را مرتب می‌کنم.\n"
                    "✅ کار: «امروز گزارش پروژه را تمام کنم»\n"
                    "💡 ایده: «ایده‌ای برای یک اپلیکیشن دارم»\n"
                    "🗣 نظر: «به نظرم صندوقچه بهتر شده»\n"
                    "🌿 احساس: «امروز از فشار کار خسته‌ام»\n"
                    "⏰ یادآوری: «امروز ۵ دقیقه دیگر یادآوری کن» یا «فردا ساعت ۹ زنگ بزن»\n\n"
                    "📅 تاریخ‌ها را شمسی بنویس؛ مثل «۲۵ مهر ساعت ۱۰:۳۰».\n"
                    "از منوی پایین می‌توانی همیشه وارد سامانه، گزارش امروز یا یادآوری‌ها شوی.",
                    reply_markup=main_menu_keyboard(),
                )
                return JSONResponse({"ok": True})
            if message.kind == "text" and message.text == "📅 امروز":
                content = build_digest(session, user, _now(), "daily")
                session.commit()
                await request.app.state.bale.send_message(
                    user.bale_chat_id, content, reply_markup=main_menu_keyboard()
                )
                return JSONResponse({"ok": True})
            if message.kind == "text" and message.text == "⏰ یادآوری‌ها":
                reminders = list(
                    session.scalars(
                        select(Reminder).where(
                            Reminder.user_id == user.id,
                            Reminder.status == "pending",
                            Reminder.deleted_at.is_(None),
                        ).order_by(Reminder.due_at.asc()).limit(20)
                    )
                )
                content = "⏰ یادآوری‌های باز:\n" + "\n".join(
                    f"• {item.text} — {format_persian_datetime(item.due_at, user.timezone)}"
                    for item in reminders
                ) if reminders else "✅ یادآوری بازی نداری."
                session.commit()
                await request.app.state.bale.send_message(
                    user.bale_chat_id, content, reply_markup=main_menu_keyboard()
                )
                return JSONResponse({"ok": True})
            repository = EntryRepository(session)
            pending = repository.pending_edit_entry(user.id) if message.kind == "text" else None
            if pending is not None:
                session.commit()
                try:
                    await reprocess_entry(
                        session,
                        pending.id,
                        user,
                        message.text or "",
                        ai_client=request.app.state.ai,
                        bale_client=request.app.state.bale,
                    )
                except Exception:
                    await request.app.state.bale.send_message(
                        user.bale_chat_id, "⚠️ ویرایش دریافت شد، اما پردازش آن کامل نشد."
                    )
                else:
                    await request.app.state.bale.send_message(
                        user.bale_chat_id, "✅ ثبت و دسته‌بندی دوباره انجام شد."
                    )
                return JSONResponse({"ok": True})
            existing = session.scalar(
                select(Entry).where(
                    Entry.user_id == user.id,
                    Entry.source_message_id == message.message_id,
                )
            )
            if existing is not None:
                return {"ok": True}
            entry = Entry(
                user_id=user.id,
                source_message_id=message.message_id,
                source_update_id=message.update_id,
                kind=message.kind,
                raw_text=message.text,
                transcript=message.text if message.kind == "text" else None,
                audio_path=message.file_id if message.kind in {"voice", "audio"} else None,
                created_at=datetime.fromtimestamp(message.date, UTC)
                if message.date
                else _now(),
            )
            session.add(entry)
            session.flush()
            # Do not hold the insert transaction while AvalAI/Bale network
            # calls are running; concurrent webhook deliveries must remain
            # writable in SQLite.
            session.commit()
            try:
                await process_entry(
                    session,
                    entry,
                    user,
                    ai_client=request.app.state.ai,
                    bale_client=request.app.state.bale,
                )
            except Exception:
                entry.status = "failed"
                await request.app.state.bale.send_message(
                    user.bale_chat_id,
                    "⚠️ پیامت رسید، اما پردازش آن کامل نشد. در داشبورد می‌توانی متن خام را ببینی و دوباره تلاش کنی.",
                )
        return JSONResponse({"ok": True})

    @app.get("/auth/claim/{token}")
    async def claim_dashboard(token: str, request: Request):
        with session_scope(request.app.state.engine) as session:
            auth = AuthService(
                session,
                request.app.state.settings.session_secret,
                request.app.state.settings.app_base_url,
            )
            user_id = auth.consume_dashboard_token(token, _now())
            if user_id is None:
                raise HTTPException(status_code=404, detail="لینک منقضی یا قبلاً مصرف شده است")
            session_id, csrf = auth.create_session(user_id, _now())
        response = RedirectResponse("/dashboard", status_code=303)
        secure = request.app.state.settings.app_base_url.startswith("https://") and request.url.hostname != "testserver"
        response.set_cookie(
            "self_session", session_id, httponly=True, secure=secure, samesite="lax", max_age=14 * 86400
        )
        response.set_cookie("self_csrf", csrf, httponly=False, secure=secure, samesite="lax", max_age=14 * 86400)
        return response

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        user, _, _ = _session_user(request)
        if user:
            return RedirectResponse("/dashboard", status_code=303)
        return templates.TemplateResponse(request=request, name="home.html", context={})

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(
        request: Request,
        period: str = Query("all", pattern="^(all|today|week)$"),
        category: str | None = Query(None),
    ):
        user, _, csrf = _session_user(request)
        if user is None:
            return RedirectResponse("/", status_code=303)
        with session_scope(request.app.state.engine) as session:
            record_query = (
                select(ExtractedRecord)
                .join(Entry, Entry.id == ExtractedRecord.entry_id)
                .where(
                    ExtractedRecord.user_id == user.id,
                    ExtractedRecord.deleted_at.is_(None),
                    Entry.deleted_at.is_(None),
                )
            )
            if category:
                record_query = record_query.where(ExtractedRecord.category == category)
            if period in {"today", "week"}:
                start, end = period_bounds(_now(), user, "daily" if period == "today" else "weekly")
                record_query = record_query.where(
                    Entry.created_at >= start.replace(tzinfo=None),
                    Entry.created_at < end.replace(tzinfo=None),
                )
            records = list(session.scalars(record_query.order_by(Entry.created_at.desc()).limit(100)))
            today_start, today_end = period_bounds(_now(), user, "daily")
            today_id = session.scalar(
                select(ExtractedRecord.id)
                .join(Entry, Entry.id == ExtractedRecord.entry_id)
                .where(
                    ExtractedRecord.user_id == user.id,
                    ExtractedRecord.deleted_at.is_(None),
                    Entry.deleted_at.is_(None),
                    Entry.created_at >= today_start.replace(tzinfo=None),
                    Entry.created_at < today_end.replace(tzinfo=None),
                )
                .order_by(ExtractedRecord.id.desc())
                .limit(1)
            )
            today_count = 1 if today_id is not None else 0
            reminders = list(
                session.scalars(
                    select(Reminder)
                    .where(
                        Reminder.user_id == user.id,
                        Reminder.status == "pending",
                        Reminder.deleted_at.is_(None),
                    )
                    .order_by(Reminder.due_at.asc())
                )
            )
            daily = build_digest(session, user, _now() - timedelta(days=1), "daily")
        standalone = request.url.path != "/dashboard"
        page_title = (
            CATEGORY_LABELS.get(category)
            if category
            else "ثبت‌های امروز"
            if period == "today"
            else "ثبت‌های این هفته"
            if period == "week"
            else "نمای کلی"
        )
        page_kicker = "دسته‌بندی" if category else "نمایش ثبت‌ها"
        page_description = (
            f"تمام ثبت‌های دستهٔ {CATEGORY_LABELS[category]} را با زمان ثبت ببین."
            if category
            else "ثبت‌های خودت را بر اساس بازهٔ زمانی مرور و مدیریت کن."
        )
        active_path = f"/categories/{category}" if category else "/" + period if period != "all" else "/dashboard"
        return templates.TemplateResponse(
            request=request,
            name="records.html" if standalone else "dashboard.html",
            context={
                "user": user,
                "csrf": csrf or "",
                "records": records,
                "reminders": reminders,
                "daily": daily,
                "today_digest": build_digest(session, user, _now(), "daily"),
                "labels": CATEGORY_LABELS,
                "icons": CATEGORY_ICONS,
                "period": period,
                "category": category,
                "selected_label": CATEGORY_LABELS.get(category) if category else None,
                "selected_icon": CATEGORY_ICONS.get(category) if category else None,
                "now": _now(),
                "today_count": today_count,
                "active_path": active_path,
                "page_title": page_title,
                "page_kicker": page_kicker,
                "page_description": page_description,
            },
        )

    @app.get("/today", response_class=HTMLResponse)
    async def today(request: Request):
        return await dashboard(request, period="today", category=None)

    @app.get("/week", response_class=HTMLResponse)
    async def week(request: Request):
        return await dashboard(request, period="week", category=None)

    @app.get("/categories/{category}", response_class=HTMLResponse)
    async def category_page(request: Request, category: str):
        if category not in CATEGORY_LABELS:
            raise HTTPException(status_code=404, detail="دسته‌بندی پیدا نشد")
        return await dashboard(request, period="all", category=category)

    @app.get("/reminders", response_class=HTMLResponse)
    async def reminders_page(request: Request):
        user, _, csrf = _session_user(request)
        if user is None:
            return RedirectResponse("/", status_code=303)
        with session_scope(request.app.state.engine) as session:
            reminders = list(
                session.scalars(
                    select(Reminder)
                    .where(Reminder.user_id == user.id, Reminder.deleted_at.is_(None))
                    .order_by(Reminder.status.asc(), Reminder.due_at.asc())
                )
            )
        return templates.TemplateResponse(
            request=request,
            name="reminders.html",
            context={
                "user": user,
                "csrf": csrf or "",
                "reminders": reminders,
                "active_path": "/reminders",
            },
        )

    @app.get("/reports/{kind}", response_class=HTMLResponse)
    async def report(request: Request, kind: str):
        user, _, csrf = _session_user(request)
        if user is None:
            return RedirectResponse("/", status_code=303)
        with session_scope(request.app.state.engine) as session:
            reference = _now() - (timedelta(days=1) if kind == "daily" else timedelta(days=7))
            content = build_digest(session, user, reference, kind)
            today_content = build_digest(session, user, _now(), "daily") if kind == "daily" else None
        return templates.TemplateResponse(
            request=request,
            name="report.html",
            context={
                "user": user,
                "csrf": csrf or "",
                "content": content,
                "today_content": today_content,
                "kind": kind,
                "active_path": "/reports/daily" if kind == "daily" else "/reports/weekly",
            },
        )

    @app.post("/reminders/{reminder_id}/status")
    async def reminder_status(request: Request, reminder_id: int, status: str = Form(...), csrf: str = Form(...)):
        session_id = request.cookies.get("self_session")
        if not session_id:
            raise HTTPException(status_code=401)
        with session_scope(request.app.state.engine) as session:
            auth = AuthService(
                session, request.app.state.settings.session_secret, request.app.state.settings.app_base_url
            )
            user_id = auth.get_session_user(session_id, _now())
            if user_id is None or not auth.verify_csrf(session_id, csrf, _now()):
                raise HTTPException(status_code=403)
            reminder = session.scalar(
                select(Reminder).where(
                    Reminder.id == reminder_id,
                    Reminder.user_id == user_id,
                    Reminder.deleted_at.is_(None),
                )
            )
            if reminder is None:
                raise HTTPException(status_code=404)
            user = session.get(User, user_id)
            if user is None:
                raise HTTPException(status_code=404)
            if status == "tomorrow":
                local_due = reminder.due_at.replace(tzinfo=UTC).astimezone(ZoneInfo(user.timezone))
                reminder.due_at = (local_due + timedelta(days=1)).astimezone(UTC)
                reminder.snooze_until = reminder.due_at
                reminder.delivered_at = None
                reminder.status = "pending"
            elif status in {"done", "cancelled"}:
                reminder.status = status
            else:
                raise HTTPException(status_code=400)
        return RedirectResponse("/dashboard", status_code=303)

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        user, _, csrf = _session_user(request)
        if user is None:
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(
            request=request, name="settings.html", context={"user": user, "csrf": csrf or ""}
        )

    @app.post("/settings")
    async def save_settings(
        request: Request,
        daily_digest_hour: int = Form(...),
        timezone: str = Form(...),
        csrf: str = Form(...),
    ):
        session_id = request.cookies.get("self_session")
        if not session_id:
            raise HTTPException(status_code=401)
        if not 0 <= daily_digest_hour <= 23:
            raise HTTPException(status_code=400, detail="ساعت نامعتبر است")
        try:
            ZoneInfo(timezone)
        except Exception as error:
            raise HTTPException(status_code=400, detail="منطقهٔ زمانی نامعتبر است") from error
        with session_scope(request.app.state.engine) as session:
            auth = AuthService(
                session, request.app.state.settings.session_secret, request.app.state.settings.app_base_url
            )
            user_id = auth.get_session_user(session_id, _now())
            if user_id is None or not auth.verify_csrf(session_id, csrf, _now()):
                raise HTTPException(status_code=403)
            user = session.get(User, user_id)
            if user is None:
                raise HTTPException(status_code=404)
            user.daily_digest_hour = daily_digest_hour
            user.timezone = timezone
        return RedirectResponse("/dashboard", status_code=303)

    @app.get("/entries/{entry_id}/edit", response_class=HTMLResponse)
    async def edit_entry_page(request: Request, entry_id: int):
        user, _, csrf = _session_user(request)
        if user is None:
            return RedirectResponse("/", status_code=303)
        with session_scope(request.app.state.engine) as session:
            entry = EntryRepository(session).get_owned_entry(entry_id, user.id)
            if entry is None:
                raise HTTPException(status_code=404)
        return templates.TemplateResponse(
            request=request,
            name="edit_entry.html",
            context={"user": user, "csrf": csrf or "", "entry": entry},
        )

    @app.post("/entries/{entry_id}/edit")
    async def edit_entry(request: Request, entry_id: int, text: str = Form(...), csrf: str = Form(...)):
        session_id = request.cookies.get("self_session")
        if not session_id:
            raise HTTPException(status_code=401)
        with session_scope(request.app.state.engine) as session:
            auth = AuthService(
                session, request.app.state.settings.session_secret, request.app.state.settings.app_base_url
            )
            user_id = auth.get_session_user(session_id, _now())
            if user_id is None or not auth.verify_csrf(session_id, csrf, _now()):
                raise HTTPException(status_code=403)
            user = session.get(User, user_id)
            if user is None:
                raise HTTPException(status_code=404)
            session.commit()
            await reprocess_entry(
                session,
                entry_id,
                user,
                text,
                ai_client=request.app.state.ai,
                bale_client=request.app.state.bale,
            )
        return RedirectResponse("/dashboard", status_code=303)

    @app.post("/records/{record_id}/delete")
    async def delete_record(request: Request, record_id: int, csrf: str = Form(...)):
        session_id = request.cookies.get("self_session")
        if not session_id:
            raise HTTPException(status_code=401)
        with session_scope(request.app.state.engine) as session:
            auth = AuthService(
                session, request.app.state.settings.session_secret, request.app.state.settings.app_base_url
            )
            user_id = auth.get_session_user(session_id, _now())
            if user_id is None or not auth.verify_csrf(session_id, csrf, _now()):
                raise HTTPException(status_code=403)
            if not EntryRepository(session).soft_delete_record(record_id, user_id):
                raise HTTPException(status_code=404)
        return RedirectResponse("/dashboard", status_code=303)

    @app.post("/logout")
    async def logout(request: Request, csrf: str = Form(...)):
        session_id = request.cookies.get("self_session")
        if session_id:
            with session_scope(request.app.state.engine) as session:
                auth = AuthService(
                    session, request.app.state.settings.session_secret, request.app.state.settings.app_base_url
                )
                if auth.verify_csrf(session_id, csrf, _now()):
                    auth.delete_session(session_id)
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie("self_session")
        response.delete_cookie("self_csrf")
        return response
