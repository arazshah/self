from dataclasses import replace

from fastapi.testclient import TestClient

from app.main import create_app
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
        dashboard_markup = next(
            markup
            for markup in app.state.bale.markups
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
