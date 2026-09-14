from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    update_id: int
    message_id: int
    chat_id: int
    user_id: int | None
    display_name: str
    kind: str
    text: str | None = None
    file_id: str | None = None
    date: int | None = None


@dataclass(frozen=True, slots=True)
class IncomingCallback:
    query_id: str
    chat_id: int
    user_id: int | None
    message_id: int
    data: str


def parse_callback_update(payload: dict[str, Any]) -> IncomingCallback | None:
    callback = payload.get("callback_query")
    if not isinstance(callback, dict) or not isinstance(callback.get("data"), str):
        return None
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    if chat.get("type") != "private":
        return None
    sender = callback.get("from") or {}
    return IncomingCallback(
        query_id=str(callback.get("id", "")),
        chat_id=int(chat["id"]),
        user_id=int(sender["id"]) if sender.get("id") is not None else None,
        message_id=int(message.get("message_id", 0)),
        data=callback["data"],
    )


def entry_keyboard(entry_id: int, dashboard_url: str | None = None) -> dict[str, Any]:
    rows = [
        [
            {"text": "✏️ ویرایش متن", "callback_data": f"entry:edit:{entry_id}"},
            {"text": "🗑 حذف", "callback_data": f"entry:delete:{entry_id}"},
        ]
    ]
    if dashboard_url:
        rows.append([{"text": "📊 داشبورد", "url": dashboard_url}])
    return {
        "inline_keyboard": rows
    }


def reminder_keyboard(reminder_id: int) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ انجام شد", "callback_data": f"reminder:done:{reminder_id}"},
                {"text": "⏰ فردا", "callback_data": f"reminder:tomorrow:{reminder_id}"},
            ],
            [{"text": "🚫 لغو", "callback_data": f"reminder:cancel:{reminder_id}"}],
        ]
    }


def main_menu_keyboard() -> dict[str, Any]:
    return {
        "keyboard": [
            [{"text": "📊 ورود به سامانه"}, {"text": "📅 امروز"}],
            [{"text": "⏰ یادآوری‌ها"}, {"text": "❓ راهنما"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def parse_private_update(payload: dict[str, Any]) -> IncomingMessage | None:
    message = payload.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat") or {}
    if chat.get("type") != "private":
        return None

    voice = message.get("voice")
    audio = message.get("audio")
    sender = message.get("from") or {}
    display_name = " ".join(
        part for part in (sender.get("first_name"), sender.get("last_name")) if part
    ) or "کاربر"
    if isinstance(voice, dict) and voice.get("file_id"):
        kind = "voice"
        file_id = voice["file_id"]
    elif isinstance(audio, dict) and audio.get("file_id"):
        kind = "audio"
        file_id = audio["file_id"]
    elif isinstance(message.get("text"), str):
        kind = "text"
        file_id = None
    else:
        return None

    return IncomingMessage(
        update_id=int(payload.get("update_id", 0)),
        message_id=int(message.get("message_id", 0)),
        chat_id=int(chat["id"]),
        user_id=int(sender["id"]) if sender.get("id") is not None else None,
        display_name=display_name,
        kind=kind,
        text=message.get("text") if kind == "text" else None,
        file_id=file_id,
        date=message.get("date"),
    )


class BaleClient:
    def __init__(
        self,
        token: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ):
        self._api = httpx.AsyncClient(
            base_url=f"https://tapi.bale.ai/bot{token}",
            transport=transport,
            timeout=timeout,
        )
        self._files = httpx.AsyncClient(
            base_url=f"https://tapi.bale.ai/file/bot{token}",
            transport=transport,
            timeout=timeout,
        )

    async def close(self) -> None:
        await self._api.aclose()
        await self._files.aclose()

    async def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._api.post(f"/{method}", json=payload)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", "Bale API request failed"))
        return data["result"]

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self._post("sendMessage", payload)

    async def set_webhook(self, url: str) -> bool:
        result = await self._post("setWebhook", {"url": url})
        return result is True

    async def answer_callback_query(self, query_id: str, text: str | None = None) -> bool:
        payload: dict[str, Any] = {"callback_query_id": query_id}
        if text:
            payload["text"] = text
        result = await self._post("answerCallbackQuery", payload)
        return result is True

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self._post("editMessageText", payload)

    async def get_file(self, file_id: str) -> dict[str, Any]:
        return await self._post("getFile", {"file_id": file_id})

    async def download_file(self, file_path: str, max_bytes: int = 20 * 1024 * 1024) -> bytes:
        response = await self._files.get(f"/{file_path.lstrip('/')}")
        response.raise_for_status()
        if len(response.content) > max_bytes:
            raise ValueError("فایل صوتی بزرگ‌تر از حد مجاز است")
        return response.content
