from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Entry, ExtractedRecord, Reminder, User
from app.pipeline import PipelineAI, PipelineBale, process_entry
from app.repositories import EntryRepository
from app.time_utils import HOUR_WORDS, MONTHS

_HOUR_WORD_PATTERN = "|".join(re.escape(word) for word in sorted(HOUR_WORDS, key=len, reverse=True))
_DAY_WORD_PATTERN = r"(?:شنبه|یک\s*شنبه|دو\s*شنبه|سه\s*شنبه|چهار\s*شنبه|پنج\s*شنبه|جمعه)"
_MONTH_WORD_PATTERN = "|".join(re.escape(word) for word in MONTHS)
_DATE_ONLY_PATTERN = (
    r"(?:امروز|فردا|پس[‌ ]?فردا|"
    rf"(?:(?:این\s*هفته|هفته\s*(?:آینده|بعد))\s*)?(?:{_DAY_WORD_PATTERN})|"
    r"[۰-۹0-9]{1,4}\s*[/\-]\s*[۰-۹0-9]{1,2}(?:\s*[/\-]\s*[۰-۹0-9]{1,2})?|"
    rf"[۰-۹0-9]{{1,2}}\s*(?:{_MONTH_WORD_PATTERN}))"
)
_TIME_ONLY_EDIT = re.compile(
    rf"^\s*{_DATE_ONLY_PATTERN}"
    rf"(?:\s*[،,]?\s*ساعت\s*(?:[۰-۹0-9]{{1,2}}(?:\s*[:：]\s*[۰-۹0-9]{{2}})?|{_HOUR_WORD_PATTERN})"
    r"(?:\s*(?:صبح|عصر|شب|بامداد))?)?\s*$"
)


def compose_bale_edit_text(session: Session, entry: Entry, user: User, correction: str) -> str:
    """Keep the original subject when a Bale correction contains only a date/time."""
    correction = correction.strip()
    if not _TIME_ONLY_EDIT.fullmatch(correction.replace("‌", "")):
        return correction
    record = session.scalar(
        select(ExtractedRecord)
        .where(
            ExtractedRecord.entry_id == entry.id,
            ExtractedRecord.user_id == user.id,
            ExtractedRecord.deleted_at.is_(None),
        )
        .order_by(ExtractedRecord.id.desc())
    )
    if record is None or record.category not in {
        "task", "reminder", "follow_up", "finance", "appointment", "errand"
    }:
        return correction
    return f"یادآوری {record.title}، {correction}"


async def reprocess_entry(
    session: Session,
    entry_id: int,
    user: User,
    text: str,
    *,
    ai_client: PipelineAI,
    bale_client: PipelineBale,
    now: datetime | None = None,
) -> Entry:
    repository = EntryRepository(session)
    entry = repository.get_owned_entry(entry_id, user.id)
    if entry is None:
        raise LookupError("entry not found")
    records = list(
        session.scalars(
            select(ExtractedRecord).where(
                ExtractedRecord.entry_id == entry.id,
                ExtractedRecord.user_id == user.id,
                ExtractedRecord.deleted_at.is_(None),
            )
        )
    )
    deleted_at = datetime.now(UTC)
    for record in records:
        record.deleted_at = deleted_at
        for reminder in session.scalars(
            select(Reminder).where(
                Reminder.record_id == record.id,
                Reminder.user_id == user.id,
                Reminder.deleted_at.is_(None),
            )
        ):
            reminder.deleted_at = deleted_at
    repository.update_entry_text(entry.id, user.id, text)
    await process_entry(
        session,
        entry,
        user,
        ai_client=ai_client,
        bale_client=bale_client,
        now=now,
    )
    return entry
