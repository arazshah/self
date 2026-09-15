from __future__ import annotations

import re
from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session

from app.ai import normalize_extraction
from app.models import Entry, ExtractedRecord, Reminder, User, utc_now
from app.reports import CATEGORY_ICONS, CATEGORY_LABELS
from app.schemas import ExtractedItem, ExtractionResult, ResolvedDate
from app.time_utils import format_persian_datetime, resolve_persian_datetime

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
)-> ResolvedDate:
    if item.category not in ACTIONABLE_CATEGORIES:
        return ResolvedDate(raw="")
    if (
        item.category != "reminder" and not item.due_raw and source_text
        and re.search(r"(?:دیروز|پریروز|هفته\s*(?:گذشته|قبل)|ماه\s*(?:گذشته|قبل))", source_text)
        and "یادآور" not in source_text
    ):
        return ResolvedDate(raw="")
    time_marker = r"(?:ساعت|دقیقه|\d{1,2}\s*[:：]\s*\d{2})"
    evidence_is_spoken = bool(
        source_text and item.evidence and item.evidence in source_text
        and re.search(time_marker, item.evidence)
        and resolve_persian_datetime(item.evidence, now, timezone_name).value is not None
    )
    sources = (item.evidence, source_text) if evidence_is_spoken else (source_text, item.evidence)
    candidates = [
        source for source in sources
        if source and re.search(time_marker, source)
    ]
    if item.due_raw:
        candidates.append(item.due_raw)
    for candidate in candidates:
        resolved = resolve_persian_datetime(candidate, now, timezone_name)
        if resolved.value is not None or resolved.needs_confirmation:
            return resolved
    return ResolvedDate(raw=item.due_raw or "", solar_date=item.solar_date)


def _confirmation_text(
    item: ExtractedItem, due_at: datetime | None, timezone_name: str, clarification: str | None
) -> str:
    category = f"{CATEGORY_ICONS.get(item.category, '📝')} {CATEGORY_LABELS.get(item.category, item.category)}"
    if clarification:
        return f"⚠️ {category}: {item.title}\nیادآوری زمان‌بندی نشد. {clarification}\n✏️ متن و زمان را در سامانه اصلاح کن."
    suffix = f"\n📅 زمان فهمیده‌شده: {format_persian_datetime(due_at, timezone_name)}" if due_at else ""
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
        resolved = _due_date(item, processing_now, user.timezone, transcript)
        due_at, solar_date = resolved.value, resolved.solar_date
        expired_during_processing = bool(
            due_at is not None and due_at <= (now if now is not None else utc_now())
        )
        if expired_during_processing:
            due_at = None
        ambiguous = bool(
            resolved.needs_confirmation or expired_during_processing
            or (item.category == "reminder" and due_at is None)
        )
        needs_confirmation = item.needs_confirmation or ambiguous
        clarification = (
            "زمان یادآوری هنگام پردازش گذشته است؛ تاریخ و ساعت آینده را مشخص کن."
            if expired_during_processing else resolved.clarification
        )
        if clarification is None and item.category == "reminder" and due_at is None:
            clarification = "روز و ساعت یادآوری مشخص نیست؛ هر دو را واضح بگو."
        if item.needs_confirmation and due_at is not None:
            clarification = "زمان استخراج‌شده نیاز به بررسی دارد؛ متن و زمان را اصلاح کن."
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
                    due_at if not needs_confirmation else None,
                    user.timezone,
                    clarification or extraction.clarification if needs_confirmation else None,
                ),
                {
                    "inline_keyboard": [[{
                        "text": "✏️ اصلاح زمان",
                        "callback_data": f"entry:edit:{entry.id}",
                    }]]
                } if needs_confirmation and item.category in ACTIONABLE_CATEGORIES else None,
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
