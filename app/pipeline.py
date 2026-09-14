from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.orm import Session

from app.ai import normalize_extraction
from app.models import Entry, ExtractedRecord, Reminder, User, utc_now
from app.reports import CATEGORY_ICONS, CATEGORY_LABELS
from app.schemas import ExtractedItem, ExtractionResult
from app.time_utils import resolve_persian_datetime

ACTIONABLE_CATEGORIES = {
    "task",
    "reminder",
    "follow_up",
    "finance",
    "appointment",
    "errand",
}


class PipelineAI(Protocol):
    async def transcribe(self, audio: bytes, filename: str) -> str: ...

    async def extract(
        self, transcript: str, now: datetime | str, timezone_name: str
    ) -> ExtractionResult: ...


class PipelineBale(Protocol):
    async def get_file(self, file_id: str) -> dict: ...

    async def download_file(self, file_path: str) -> bytes: ...

    async def send_message(self, chat_id: int, text: str, reply_markup: dict | None = None) -> dict: ...


async def _send_with_optional_keyboard(
    bale_client: PipelineBale, chat_id: int, text: str, keyboard: dict | None
) -> None:
    if keyboard is None:
        await bale_client.send_message(chat_id, text)
        return
    try:
        await bale_client.send_message(chat_id, text, reply_markup=keyboard)
    except TypeError as error:
        # Keep compatibility with lightweight integrations written before
        # inline keyboards were introduced.
        if "reply_markup" not in str(error):
            raise
        await bale_client.send_message(chat_id, text)


def _due_date(
    item: ExtractedItem, now: datetime, timezone_name: str, source_text: str | None = None
):
    source = item.evidence or source_text
    candidates = [item.due_raw] if item.due_raw else []
    if source and re.search(r"(?:ساعت|دقیقه|نیم\s*ساعت)", source) and not (
        item.due_raw and re.search(r"(?:ساعت|دقیقه|نیم\s*ساعت)", item.due_raw)
    ):
        candidates.insert(0, source)
    for candidate in candidates:
        resolved = resolve_persian_datetime(candidate, now, timezone_name)
        if resolved.value is not None:
            return resolved.value, resolved.solar_date
    if item.due_at is not None:
        value = item.due_at
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC), item.solar_date
    if not item.due_raw:
        return None, item.solar_date
    resolved = resolve_persian_datetime(item.due_raw, now, timezone_name)
    return resolved.value, resolved.solar_date


def _confirmation_text(item: ExtractedItem, due_raw: str | None, clarification: str | None) -> str:
    category = f"{CATEGORY_ICONS.get(item.category, '📝')} {CATEGORY_LABELS.get(item.category, item.category)}"
    suffix = f"\n⏰ زمان: {due_raw}" if due_raw else ""
    if clarification:
        suffix += f"\n⚠️ {clarification}"
    return f"✅ ثبت شد\n{category}: {item.title}{suffix}"


async def process_entry(
    session: Session,
    entry: Entry,
    user: User,
    *,
    ai_client: PipelineAI,
    bale_client: PipelineBale,
    now: datetime | None = None,
) -> ExtractionResult:
    """Process one entry while keeping all writes under the owning user."""
    processing_now = now or utc_now()
    entry.status = "processing"
    transcript = entry.transcript
    if not transcript and entry.audio_path:
        file_info = await bale_client.get_file(entry.audio_path)
        audio = await bale_client.download_file(file_info["file_path"])
        transcript = await ai_client.transcribe(audio, filename="voice.ogg")
        entry.transcript = transcript
    if not transcript:
        entry.status = "failed"
        raise ValueError("متن پیام برای پردازش وجود ندارد")

    extraction = await ai_client.extract(transcript, processing_now, user.timezone)
    extraction = normalize_extraction(extraction, transcript)
    outgoing_messages: list[tuple[str, dict | None]] = []
    for item in extraction.items:
        due_at, solar_date = _due_date(item, processing_now, user.timezone, transcript)
        ambiguous = bool(item.due_raw and due_at is None)
        needs_confirmation = item.needs_confirmation or ambiguous
        record = ExtractedRecord(
            user_id=user.id,
            entry_id=entry.id,
            category=item.category,
            title=item.title,
            body=item.body,
            evidence=item.evidence or transcript,
            due_at=due_at,
            due_raw=item.due_raw,
            solar_date=solar_date,
            confidence=item.confidence,
            status="needs_confirmation" if needs_confirmation else "confirmed",
        )
        session.add(record)
        session.flush()
        if item.category in ACTIONABLE_CATEGORIES and due_at is not None and not needs_confirmation:
            session.add(
                Reminder(
                    user_id=user.id,
                    record_id=record.id,
                    text=item.title,
                    due_at=due_at,
                )
            )

        outgoing_messages.append(
            (
                _confirmation_text(
                    item,
                    item.due_raw,
                    extraction.clarification if ambiguous else None,
                ),
                None,
            )
        )

    if extraction.reflection_summary:
        session.add(
            ExtractedRecord(
                user_id=user.id,
                entry_id=entry.id,
                category="reflection",
                title=extraction.reflection_summary,
                body=extraction.suggestion,
                evidence=transcript,
                confidence=1.0,
                status="confirmed",
            )
        )
        outgoing_messages.append((f"🌿 بازتاب ثبت شد: {extraction.reflection_summary}", None))

    entry.status = "processed"
    entry.processed_at = utc_now()
    session.flush()
    # Commit all local state before waiting on Bale. Otherwise SQLite keeps a
    # write lock while a network request is in flight.
    session.commit()
    for message, keyboard in outgoing_messages:
        await _send_with_optional_keyboard(bale_client, user.bale_chat_id, message, keyboard)
    return extraction
