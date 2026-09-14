import httpx
import pytest

from app.bale import BaleClient, parse_private_update


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
