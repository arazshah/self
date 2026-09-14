from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Entry, ExtractedRecord, Reminder, User
from app.pipeline import PipelineAI, PipelineBale, process_entry
from app.repositories import EntryRepository


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
