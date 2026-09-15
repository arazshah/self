from dataclasses import replace
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import session_scope
from app.main import create_app
from app.models import Entry, ExtractedRecord, Reminder, User
from app.schemas import ExtractedItem, ExtractionResult


class FakeAI:
    async def transcribe(self, audio: bytes, filename: str) -> str:
        return "ایدهٔ اپلیکیشن"

    async def extract(self, transcript, now, timezone_name):
        return ExtractionResult(
            items=[
                ExtractedItem(
                    category="idea",
                    title="ایدهٔ اپلیکیشن",
                    body="یک ابزار برای مدیریت زندگی",
                    evidence=transcript,
                    confidence=0.95,
                    needs_confirmation=False,
                )
            ]
        )


class FakeBale:
    def __init__(self):
        self.messages = []
        self.markups = []
        self.webhook_urls = []

    async def set_webhook(self, url):
        self.webhook_urls.append(url)
        return True

    async def send_message(self, chat_id, text, reply_markup=None):
        self.messages.append((chat_id, text))
        self.markups.append(reply_markup)
        return {"ok": True}


class EditAI(FakeAI):
    async def extract(self, transcript, now, timezone_name):
        return ExtractionResult(items=[ExtractedItem(
            category="reminder", title="تماس با علی", evidence=transcript,
            due_raw="فردا", confidence=0.9, needs_confirmation=True,
        )])


def test_bale_time_edit_keeps_subject_and_does_not_claim_false_success(test_settings):
    app = create_app(test_settings)
    app.state.ai = EditAI()
    app.state.bale = FakeBale()
    with TestClient(app) as client:
        with session_scope(app.state.engine) as session:
            user = User(bale_chat_id=8101, bale_user_id=8102, display_name="آراز")
            session.add(user)
            session.flush()
            entry = Entry(
                user_id=user.id, source_message_id=91,
                transcript="فردا یادآوری کن به علی زنگ بزنم",
                raw_text="فردا یادآوری کن به علی زنگ بزنم",
                awaiting_edit=True,
            )
            session.add(entry)
            session.flush()
            entry_id = entry.id
            session.add(ExtractedRecord(
                user_id=user.id, entry_id=entry.id, category="reminder",
                title="تماس با علی", due_raw="فردا", status="needs_confirmation",
            ))

        def send_edit(message_id, text):
            result = client.post("/bale/webhook/test-webhook-secret", json={
                "update_id": message_id,
                "message": {
                    "message_id": message_id,
                    "chat": {"id": 8101, "type": "private"},
                    "from": {"id": 8102, "first_name": "آراز"},
                    "text": text,
                },
            })
            assert result.status_code == 200

        send_edit(92, "فردا")
        assert len(app.state.bale.messages) == 1
        assert "ساعت" in app.state.bale.messages[-1][1]
        assert all("ثبت و دسته‌بندی دوباره انجام شد" not in message for _, message in app.state.bale.messages)

        with session_scope(app.state.engine) as session:
            entry = session.get(Entry, entry_id)
            entry.awaiting_edit = True

        send_edit(93, "فردا ساعت ۱۰")
        assert len(app.state.bale.messages) == 2
        assert "✅ ثبت شد" in app.state.bale.messages[-1][1]
        assert "تماس با علی" in app.state.bale.messages[-1][1]
        assert "زمان فهمیده‌شده" in app.state.bale.messages[-1][1]
        assert all("ثبت و دسته‌بندی دوباره انجام شد" not in message for _, message in app.state.bale.messages)
        with session_scope(app.state.engine) as session:
            entry = session.get(Entry, entry_id)
            assert "تماس با علی" in entry.transcript
            reminders = list(session.scalars(select(Reminder).where(Reminder.user_id == user.id,
                                                             Reminder.deleted_at.is_(None))))
            assert len(reminders) == 1

        with session_scope(app.state.engine) as session:
            session.get(Entry, entry_id).awaiting_edit = True
        send_edit(94, "هفته آینده سه‌شنبه ساعت ۱۰")
        with session_scope(app.state.engine) as session:
            assert "تماس با علی" in session.get(Entry, entry_id).transcript

        with session_scope(app.state.engine) as session:
            session.get(Entry, entry_id).awaiting_edit = True
        send_edit(95, "هفته آینده سه‌شنبه ساعت ۱۰ به رضا زنگ بزنم")
        with session_scope(app.state.engine) as session:
            assert session.get(Entry, entry_id).transcript == "هفته آینده سه‌شنبه ساعت ۱۰ به رضا زنگ بزنم"


def _login_from_bale_start(client, bale, *, chat_id=7700):
    response = client.post(
        "/bale/webhook/test-webhook-secret",
        json={
            "update_id": 90,
            "message": {
                "message_id": 90,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": chat_id + 1, "first_name": "کاربر"},
                "text": "/start",
            },
        },
    )
    assert response.status_code == 200
    markup = next(item for item in bale.markups if item and "inline_keyboard" in item)
    url = markup["inline_keyboard"][0][0]["url"]
    return client.get(url.replace("https://self.example", ""), follow_redirects=False)


def test_private_webhook_processes_message_and_dashboard_is_user_scoped(test_settings):
    app = create_app(test_settings)
    app.state.ai = FakeAI()
    app.state.bale = FakeBale()
    with TestClient(app) as client:
        response = client.post(
            "/bale/webhook/test-webhook-secret",
            json={
                "update_id": 20,
                "message": {
                    "message_id": 8,
                    "chat": {"id": 7001, "type": "private"},
                    "from": {"id": 9001, "first_name": "آراز"},
                    "text": "ایده‌ای برای اپلیکیشن دارم",
                },
            },
        )

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert any("ایدهٔ اپلیکیشن" in text for _, text in app.state.bale.messages)
        assert all("داشبورد" not in text for _, text in app.state.bale.messages)
        assert all("منوی همیشگی" not in text for _, text in app.state.bale.messages)
        assert all("این مورد را ثبت کردم" not in text for _, text in app.state.bale.messages)
        assert all(markup is None for markup in app.state.bale.markups)
        start_response = client.post(
            "/bale/webhook/test-webhook-secret",
            json={
                "update_id": 24,
                "message": {
                    "message_id": 12,
                    "chat": {"id": 7001, "type": "private"},
                    "from": {"id": 9001, "first_name": "آراز"},
                    "text": "/start",
                },
            },
        )
        assert start_response.status_code == 200
        dashboard_markup = next(
            markup for markup in app.state.bale.markups
            if markup and any("url" in button for row in markup["inline_keyboard"] for button in row)
        )
        dashboard_url = next(
            button["url"]
            for row in dashboard_markup["inline_keyboard"]
            for button in row
            if "url" in button
        )
        token = dashboard_url.rsplit("/", 1)[-1]
        claim = client.get(f"/auth/claim/{token}", follow_redirects=False)
        assert claim.status_code == 303
        dashboard = client.get("/dashboard")
        assert dashboard.status_code == 200
        assert "ایدهٔ اپلیکیشن" in dashboard.text
        assert app.state.bale.webhook_urls == [
            "https://self.example/bale/webhook/test-webhook-secret"
        ]


def test_group_messages_are_ignored(test_settings):
    app = create_app(test_settings)
    app.state.ai = FakeAI()
    app.state.bale = FakeBale()
    with TestClient(app) as client:
        response = client.post(
            "/bale/webhook/test-webhook-secret",
            json={
                "update_id": 21,
                "message": {
                    "message_id": 9,
                    "chat": {"id": -100, "type": "group"},
                    "text": "نباید ثبت شود",
                },
            },
        )
        assert response.json() == {"ok": True}
        assert app.state.bale.messages == []


def test_start_and_dashboard_menu_always_offer_dashboard_button(test_settings):
    app = create_app(test_settings)
    app.state.ai = FakeAI()
    app.state.bale = FakeBale()
    with TestClient(app) as client:
        response = client.post(
            "/bale/webhook/test-webhook-secret",
            json={
                "update_id": 23,
                "message": {
                    "message_id": 11,
                    "chat": {"id": 7010, "type": "private"},
                    "from": {"id": 9010, "first_name": "کاربر"},
                    "text": "/start",
                },
            },
        )
    assert response.status_code == 200
    assert any(
        markup and any("url" in button for row in markup["inline_keyboard"] for button in row)
        for markup in app.state.bale.markups
    )
    assert any(markup and "keyboard" in markup for markup in app.state.bale.markups)
    assert all("منوی همیشگی" not in text for _, text in app.state.bale.messages)


def test_webhook_secret_may_contain_slashes(test_settings):
    secret = "part-one/part-two/part-three"
    app = create_app(replace(test_settings, bale_webhook_secret=secret))
    app.state.ai = FakeAI()
    app.state.bale = FakeBale()
    with TestClient(app) as client:
        response = client.post(
            f"/bale/webhook/{secret}",
            json={
                "update_id": 22,
                "message": {
                    "message_id": 10,
                    "chat": {"id": 7002, "type": "private"},
                    "from": {"id": 9002, "first_name": "کاربر"},
                    "text": "یک پیام آزمایشی",
                },
            },
        )
        assert response.status_code == 200


def test_workspace_pages_are_independent_and_user_scoped(test_settings):
    app = create_app(test_settings)
    app.state.ai = FakeAI()
    app.state.bale = FakeBale()
    with TestClient(app) as client:
        assert client.get("/today", follow_redirects=False).status_code == 303
        assert client.get("/week", follow_redirects=False).status_code == 303
        assert client.get("/reminders", follow_redirects=False).status_code == 303
        assert client.get("/categories/idea", follow_redirects=False).status_code == 303

        _login_from_bale_start(client, app.state.bale)
        for path in ("/today", "/week", "/reminders", "/categories/idea"):
            page = client.get(path)
            assert page.status_code == 200
            assert "نمای کلی" in page.text


def test_overview_links_to_independent_workspace_pages(test_settings):
    app = create_app(test_settings)
    app.state.ai = FakeAI()
    app.state.bale = FakeBale()
    with TestClient(app) as client:
        _login_from_bale_start(client, app.state.bale, chat_id=7701)
        page = client.get("/dashboard")
        assert page.status_code == 200
        assert 'href="/today"' in page.text
        assert 'href="/week"' in page.text
        assert 'href="/reminders"' in page.text
        assert "stat-card" not in page.text


def test_overview_activity_offers_confirmed_delete_for_whole_entry(test_settings):
    app = create_app(test_settings)
    app.state.ai = FakeAI()
    app.state.bale = FakeBale()
    with TestClient(app) as client:
        _login_from_bale_start(client, app.state.bale, chat_id=7710)
        with session_scope(app.state.engine) as session:
            user = session.scalar(select(User).where(User.bale_chat_id == 7710))
            entry = Entry(user_id=user.id, source_message_id=77101, transcript="تماس با علی")
            session.add(entry)
            session.flush()
            record = ExtractedRecord(
                user_id=user.id, entry_id=entry.id, category="reminder",
                title="تماس با علی", status="confirmed",
            )
            session.add(record)
            session.flush()
            record_id = record.id

        overview = client.get("/dashboard")
        assert overview.status_code == 200
        assert f'action="/records/{record_id}/delete"' in overview.text
        assert "حذف ثبت" in overview.text
        assert "confirm(" in overview.text

        today = client.get("/today")
        assert today.status_code == 200
        assert f'action="/records/{record_id}/delete"' in today.text
        assert "حذف ثبت" in today.text


def test_dashboard_delete_removes_entry_all_records_and_linked_reminders(test_settings):
    app = create_app(test_settings)
    app.state.ai = FakeAI()
    app.state.bale = FakeBale()
    with TestClient(app) as client:
        _login_from_bale_start(client, app.state.bale, chat_id=7711)
        with session_scope(app.state.engine) as session:
            user = session.scalar(select(User).where(User.bale_chat_id == 7711))
            entry = Entry(user_id=user.id, source_message_id=77111,
                          transcript="فردا به علی زنگ بزنم و قبض را پرداخت کنم")
            session.add(entry)
            session.flush()
            entry_id = entry.id
            contact = ExtractedRecord(
                user_id=user.id, entry_id=entry.id, category="reminder",
                title="تماس با علی", status="confirmed",
            )
            payment = ExtractedRecord(
                user_id=user.id, entry_id=entry.id, category="finance",
                title="پرداخت قبض", status="confirmed",
            )
            session.add_all([contact, payment])
            session.flush()
            record_id = contact.id
            session.add(Reminder(
                user_id=user.id, record_id=contact.id, text="تماس با علی",
                due_at=datetime(2026, 9, 25, 8, tzinfo=UTC),
            ))

        response = client.post(
            f"/records/{record_id}/delete",
            data={"csrf": client.cookies.get("self_csrf")},
            follow_redirects=False,
        )
        assert response.status_code == 303
        with session_scope(app.state.engine) as session:
            assert session.get(Entry, entry_id).deleted_at is not None
            records = list(session.scalars(select(ExtractedRecord).where(ExtractedRecord.entry_id == entry_id)))
            assert len(records) == 2
            assert all(record.deleted_at is not None for record in records)
            reminders = list(session.scalars(select(Reminder).where(Reminder.record_id == record_id)))
            assert len(reminders) == 1
            assert reminders[0].deleted_at is not None

        assert "تماس با علی" not in client.get("/dashboard").text
        assert "تماس با علی" not in client.get("/reminders").text


def test_daily_report_page_also_shows_today_entries(test_settings):
    app = create_app(test_settings)
    app.state.ai = FakeAI()
    app.state.bale = FakeBale()
    with TestClient(app) as client:
        _login_from_bale_start(client, app.state.bale, chat_id=7702)
        with session_scope(app.state.engine) as session:
            user = session.scalar(select(User).where(User.bale_chat_id == 7702))
            entry = Entry(
                user_id=user.id,
                source_message_id=7002,
                transcript="ثبت امروز",
                created_at=datetime.now(UTC),
            )
            session.add(entry)
            session.flush()
            session.add(
                ExtractedRecord(
                    user_id=user.id,
                    entry_id=entry.id,
                    category="task",
                    title="کار ثبت‌شده امروز",
                    evidence="ثبت امروز",
                    confidence=1.0,
                    status="confirmed",
                )
            )
        page = client.get("/reports/daily")
        assert page.status_code == 200
        assert "ثبت‌های امروز تا این لحظه" in page.text
        assert "کار ثبت‌شده امروز" in page.text


def test_unscheduled_reminder_is_flagged_in_category_page(test_settings):
    app = create_app(test_settings)
    app.state.ai = FakeAI()
    app.state.bale = FakeBale()
    with TestClient(app) as client:
        _login_from_bale_start(client, app.state.bale, chat_id=7703)
        with session_scope(app.state.engine) as session:
            user = session.scalar(select(User).where(User.bale_chat_id == 7703))
            entry = Entry(
                user_id=user.id, source_message_id=7003,
                transcript="فردا یادآوری کن", created_at=datetime.now(UTC),
            )
            session.add(entry)
            session.flush()
            session.add(ExtractedRecord(
                user_id=user.id, entry_id=entry.id, category="reminder", title="تماس",
                due_raw="فردا", confidence=0.9, status="needs_confirmation",
            ))
        page = client.get("/categories/reminder")
        assert page.status_code == 200
        assert "زمان‌بندی نشده" in page.text
        assert "زمان دقیق را اصلاح کن" in page.text
