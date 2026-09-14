import httpx
import pytest

from app.bale import (
    BaleClient,
    entry_keyboard,
    main_menu_keyboard,
    parse_callback_update,
    parse_private_update,
)


def test_parse_private_voice_update():
    incoming = parse_private_update(
        {
            "update_id": 7,
            "message": {
                "message_id": 9,
                "date": 1779000000,
                "chat": {"id": 123, "type": "private"},
                "from": {"id": 123, "first_name": "آراز"},
                "voice": {"file_id": "voice-1", "duration": 12},
            },
        }
    )

    assert incoming is not None
    assert incoming.chat_id == 123
    assert incoming.message_id == 9
    assert incoming.kind == "voice"
    assert incoming.file_id == "voice-1"


def test_group_update_is_ignored():
    assert (
        parse_private_update(
            {
                "update_id": 7,
                "message": {
                    "message_id": 9,
                    "chat": {"id": -123, "type": "group"},
                    "text": "secret",
                },
            }
        )
        is None
    )


def test_parse_callback_and_build_entry_keyboard():
    callback = parse_callback_update(
        {
            "callback_query": {
                "id": "query-1",
                "from": {"id": 42},
                "data": "entry:edit:7",
                "message": {
                    "message_id": 99,
                    "chat": {"id": 42, "type": "private"},
                },
            }
        }
    )

    assert callback is not None
    assert callback.data == "entry:edit:7"
    keyboard = entry_keyboard(7, "https://self.example/dashboard")
    assert keyboard["inline_keyboard"][0][0]["callback_data"] == "entry:edit:7"
    assert keyboard["inline_keyboard"][1][0]["url"].endswith("/dashboard")


def test_main_menu_contains_dashboard_and_daily_actions():
    menu = main_menu_keyboard()
    labels = [button["text"] for row in menu["keyboard"] for button in row]
    assert "📊 ورود به سامانه" in labels
    assert "📅 امروز" in labels
    assert "⏰ یادآوری‌ها" in labels
    assert menu["resize_keyboard"] is True


@pytest.mark.asyncio
async def test_send_message_uses_bale_api():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 2}})

    client = BaleClient("test-token", transport=httpx.MockTransport(handler))
    result = await client.send_message(123, "سلام")
    await client.close()

    assert result["message_id"] == 2
    assert requests[0].url.path.endswith("/bottest-token/sendMessage")
    assert requests[0].content.decode() == '{"chat_id":123,"text":"سلام"}'


@pytest.mark.asyncio
async def test_set_webhook_uses_exact_configured_url():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": True})

    client = BaleClient("test-token", transport=httpx.MockTransport(handler))
    result = await client.set_webhook("https://self.example/bale/webhook/exact-secret")
    await client.close()

    assert result is True
    assert requests[0].url.path.endswith("/bottest-token/setWebhook")
    assert requests[0].content.decode() == (
        '{"url":"https://self.example/bale/webhook/exact-secret"}'
    )
