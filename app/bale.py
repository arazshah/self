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

    async def get_file(self, file_id: str) -> dict[str, Any]:
        return await self._post("getFile", {"file_id": file_id})

    async def download_file(self, file_path: str, max_bytes: int = 20 * 1024 * 1024) -> bytes:
        response = await self._files.get(f"/{file_path.lstrip('/')}")
        response.raise_for_status()
        if len(response.content) > max_bytes:
            raise ValueError("فایل صوتی بزرگ‌تر از حد مجاز است")
        return response.content
