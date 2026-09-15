from dataclasses import replace
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import session_scope
from app.main import create_app
from app.models import Entry, ExtractedRecord, User
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
