from __future__ import annotations

import hmac
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.auth import AuthService
from app.bale import parse_private_update
from app.db import session_scope
from app.models import Entry, ExtractedRecord, Reminder, User
from app.pipeline import process_entry
from app.reports import CATEGORY_LABELS, build_digest
from app.repositories import UserRepository

templates = Jinja2Templates(directory="app/templates")


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


def register_routes(app: FastAPI) -> None:
    @app.post("/bale/webhook/{secret:path}")
    async def bale_webhook(secret: str, request: Request):
        if not hmac.compare_digest(secret, request.app.state.settings.bale_webhook_secret):
            raise HTTPException(status_code=404, detail="Not found")
        message = parse_private_update(await request.json())
        if message is None:
            return {"ok": True}

        with session_scope(request.app.state.engine) as session:
            user = UserRepository(session).get_or_create_by_bale_chat(
                message.chat_id, message.display_name, message.user_id
            )
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
            auth = AuthService(
                session,
                request.app.state.settings.session_secret,
                request.app.state.settings.app_base_url,
            )
            raw_token = auth.create_dashboard_token(user.id, _now())
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
                    "پیامت رسید، اما پردازش آن کامل نشد. در داشبورد می‌توانی متن خام را ببینی و دوباره تلاش کنی.",
                )
            await request.app.state.bale.send_message(
                user.bale_chat_id,
                f"لینک داشبورد شخصی‌ات (یک‌بارمصرف و تا ۱۰ دقیقه معتبر):\n{auth.dashboard_url(raw_token)}",
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
    async def dashboard(request: Request):
        user, _, csrf = _session_user(request)
        if user is None:
            return RedirectResponse("/", status_code=303)
        with session_scope(request.app.state.engine) as session:
            records = list(
                session.scalars(
                    select(ExtractedRecord)
                    .where(ExtractedRecord.user_id == user.id)
                    .order_by(ExtractedRecord.created_at.desc())
                    .limit(50)
                )
            )
            reminders = list(
                session.scalars(
                    select(Reminder)
                    .where(Reminder.user_id == user.id, Reminder.status == "pending")
                    .order_by(Reminder.due_at.asc())
                )
            )
            daily = build_digest(session, user, _now() - timedelta(days=1), "daily")
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "user": user,
                "csrf": csrf or "",
                "records": records,
                "reminders": reminders,
                "daily": daily,
                "labels": CATEGORY_LABELS,
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
        return templates.TemplateResponse(
            request=request,
            name="report.html",
            context={"user": user, "csrf": csrf or "", "content": content, "kind": kind},
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
            reminder = session.scalar(select(Reminder).where(Reminder.id == reminder_id, Reminder.user_id == user_id))
            if reminder is None:
                raise HTTPException(status_code=404)
            if status not in {"done", "cancelled"}:
                raise HTTPException(status_code=400)
            reminder.status = status
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
