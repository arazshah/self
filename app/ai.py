from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.schemas import ExtractionResult
from app.time_utils import format_persian_datetime


class AIProviderError(RuntimeError):
    """Raised when AvalAI cannot provide a safe, parseable result."""


EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": [
                            "task", "reminder", "follow_up", "finance",
                            "appointment", "project", "idea", "errand",
                            "decision", "opinion", "reflection",
                        ],
                    },
                    "title": {"type": "string"},
                    "body": {"type": ["string", "null"]},
                    "evidence": {"type": ["string", "null"]},
                    "due_raw": {"type": ["string", "null"]},
                    "due_at": {"type": ["string", "null"]},
                    "solar_date": {"type": ["string", "null"]},
                    "confidence": {"type": "number"},
                    "needs_confirmation": {"type": "boolean"},
                },
                "required": [
                    "category", "title", "body", "evidence", "due_raw", "due_at",
                    "solar_date", "confidence", "needs_confirmation",
                ],
            },
        },
        "clarification": {"type": ["string", "null"]},
        "reflection_summary": {"type": ["string", "null"]},
        "suggestion": {"type": ["string", "null"]},
    },
    "required": ["items", "clarification", "reflection_summary", "suggestion"],
}


class AvalAIClient:
    def __init__(
        self,
        api_key: str,
        transcribe_model: str,
        text_model: str,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = "https://api.avalai.ir/v1",
    ):
        self.transcribe_model = transcribe_model
        self.text_model = text_model
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=90.0,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def transcribe(self, audio: bytes, filename: str) -> str:
        try:
            response = await self._client.post(
                "/audio/transcriptions",
                data={"model": self.transcribe_model, "language": "fa"},
                files={"file": (filename, audio, "audio/ogg")},
            )
            response.raise_for_status()
            text = response.json().get("text")
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise AIProviderError("رونویسی صوت با خطا مواجه شد") from exc
        if not isinstance(text, str) or not text.strip():
            raise AIProviderError("پاسخ رونویسی AvalAI معتبر نیست")
        return text.strip()

    async def extract(
        self, transcript: str, now: datetime | str, timezone_name: str
    ) -> ExtractionResult:
        instructions = (
            "تو یک استخراج‌کنندهٔ دقیق برای دستیار شخصی فارسی هستی. "
            "فقط اطلاعاتی را که کاربر گفته استخراج کن. تاریخ شمسی را در due_raw نگه دار؛ "
            "نظر، نقد، ترجیح و مقایسهٔ کاربر دربارهٔ یک محصول یا ایده را با category=opinion ثبت کن، نه reflection. "
            "reflection فقط برای احساس یا حال شخصیِ صریح خود کاربر است؛ "
            "برای opinion هیچ پیشنهاد درمانی یا حال‌وهوایی نساز. "
            "عبارت‌های امروز، فردا، این هفته، هفته آینده و نام روزهای هفته را دقیقاً در due_raw حفظ کن. "
            "برای زمان‌های نسبی و فارسی، due_at را محاسبه نکن و null بگذار؛ محاسبهٔ زمان با سامانه است. "
            "از حدس‌زدن تاریخ یا ساعت خودداری کن؛ اگر عبارت مبهم است needs_confirmation=true بگذار. "
            "اگر مبهم است needs_confirmation=true بگذار. احساسات را خوداظهاری ثبت کن، "
            "تشخیص پزشکی نده. هیچ عملیات خارجی پیشنهاد نده. خروجی فقط JSON مطابق schema باشد."
        )
        current = datetime.fromisoformat(now) if isinstance(now, str) else now
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        local_now = current.astimezone(ZoneInfo(timezone_name))
        payload = {
            "model": self.text_model,
            "instructions": instructions,
            "input": (
                f"زمان فعلی UTC: {now}\nمنطقه زمانی کاربر: {timezone_name}\n"
                f"زمان فعلی محلی کاربر: {format_persian_datetime(local_now, timezone_name)}\n"
                f"متن کاربر:\n{transcript}"
            ),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "self_assistant_extraction",
                    "strict": True,
                    "schema": EXTRACTION_SCHEMA,
                }
            },
        }
        try:
            response = await self._client.post("/responses", json=payload)
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise AIProviderError("ساختار پاسخ AvalAI معتبر نیست")
            if body.get("status") == "incomplete":
                raise AIProviderError("پاسخ AvalAI ناقص است")
            output_text = self._output_text(body)
            result = ExtractionResult.model_validate(json.loads(output_text))
            return normalize_extraction(result, transcript)
        except AIProviderError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise AIProviderError("ساختار پاسخ AvalAI معتبر نیست") from exc

    @staticmethod
    def _output_text(body: dict[str, Any]) -> str:
        if isinstance(body.get("output_text"), str):
            return body["output_text"]
        chunks: list[str] = []
        for item in body.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    chunks.append(content.get("text", ""))
                if content.get("type") == "refusal":
                    raise AIProviderError("AvalAI از پردازش این ورودی خودداری کرد")
        if not chunks:
            raise AIProviderError("پاسخ ساختاریافته از AvalAI دریافت نشد")
        return "".join(chunks)


OPINION_MARKERS = ("به نظرم", "به نظر من", "نظر من", "فکر می‌کنم", "فکر میکنم", "بهتر", "بدتر")
EMOTION_MARKERS = ("حالم", "احساس می‌کنم", "احساس میکنم", "غمگین", "خوشحالم", "عصبانی", "نگران")


def normalize_extraction(result: ExtractionResult, transcript: str) -> ExtractionResult:
    """Prevent comparative opinions from becoming duplicated mood reflections."""
    has_opinion = any(marker in transcript for marker in OPINION_MARKERS)
    has_emotion = any(marker in transcript for marker in EMOTION_MARKERS)
    if not has_opinion or has_emotion:
        return result
    items = [
        item.model_copy(update={"category": "opinion"})
        if item.category == "reflection" else item
        for item in result.items
    ]
    return result.model_copy(update={"items": items, "reflection_summary": None, "suggestion": None})
