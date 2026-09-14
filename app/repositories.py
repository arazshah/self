from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Entry, ExtractedRecord, Reminder, User


class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_or_create_by_bale_chat(
        self, chat_id: int, display_name: str, bale_user_id: int | None = None
    ) -> User:
        user = self.session.scalar(select(User).where(User.bale_chat_id == chat_id))
        if user is not None:
            return user
        user = User(
            bale_chat_id=chat_id,
            bale_user_id=bale_user_id,
            display_name=display_name,
        )
        self.session.add(user)
        self.session.flush()
        return user

    def get_by_id(self, user_id: int) -> User | None:
        return self.session.get(User, user_id)


class EntryRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        user_id: int,
        transcript: str,
        created_at: datetime,
        source_message_id: int = 0,
        kind: str = "text",
        raw_text: str | None = None,
        source_update_id: int | None = None,
    ) -> Entry:
        entry = Entry(
            user_id=user_id,
            source_message_id=source_message_id,
            source_update_id=source_update_id,
            kind=kind,
            raw_text=raw_text,
            transcript=transcript,
            created_at=created_at,
        )
        self.session.add(entry)
        self.session.flush()
        return entry

    def get_owned_entry(self, entry_id: int, user_id: int) -> Entry | None:
        return self.session.scalar(
            select(Entry).where(
                Entry.id == entry_id,
                Entry.user_id == user_id,
                Entry.deleted_at.is_(None),
            )
        )

    def get_owned_record(
        self, record_id: int, user_id: int
    ) -> ExtractedRecord | None:
        return self.session.scalar(
            select(ExtractedRecord).where(
                ExtractedRecord.id == record_id,
                ExtractedRecord.user_id == user_id,
                ExtractedRecord.deleted_at.is_(None),
            )
        )

    def update_entry_text(
        self, entry_id: int, user_id: int, text: str
    ) -> Entry:
        entry = self.get_owned_entry(entry_id, user_id)
        if entry is None:
            raise LookupError("entry not found")
        entry.transcript = text.strip()
        entry.raw_text = text.strip()
        entry.status = "received"
        entry.processed_at = None
        entry.revision += 1
        self.session.flush()
        return entry

    def soft_delete_entry(self, entry_id: int, user_id: int) -> bool:
        entry = self.get_owned_entry(entry_id, user_id)
        if entry is None:
            return False
        deleted_at = datetime.now(UTC)
        entry.deleted_at = deleted_at
        records = list(
            self.session.scalars(
                select(ExtractedRecord).where(
                    ExtractedRecord.entry_id == entry_id,
                    ExtractedRecord.user_id == user_id,
                    ExtractedRecord.deleted_at.is_(None),
                )
            )
        )
        record_ids = [record.id for record in records]
        for record in records:
            record.deleted_at = deleted_at
        if record_ids:
            reminders = self.session.scalars(
                select(Reminder).where(
                    Reminder.user_id == user_id,
                    Reminder.record_id.in_(record_ids),
                    Reminder.deleted_at.is_(None),
                )
            )
            for reminder in reminders:
                reminder.deleted_at = deleted_at
        self.session.flush()
        return True

    def soft_delete_record(self, record_id: int, user_id: int) -> bool:
        record = self.get_owned_record(record_id, user_id)
        if record is None:
            return False
        deleted_at = datetime.now(UTC)
        record.deleted_at = deleted_at
        self.session.flush()
        return True

    def soft_delete_reminder(self, reminder_id: int, user_id: int) -> bool:
        reminder = self.session.scalar(
            select(Reminder).where(
                Reminder.id == reminder_id,
                Reminder.user_id == user_id,
                Reminder.deleted_at.is_(None),
            )
        )
        if reminder is None:
            return False
        reminder.deleted_at = datetime.now(UTC)
        self.session.flush()
        return True

    def list_for_user(self, user_id: int, include_deleted: bool = False) -> list[Entry]:
        statement = select(Entry).where(Entry.user_id == user_id)
        if not include_deleted:
            statement = statement.where(Entry.deleted_at.is_(None))
        return list(
            self.session.scalars(
                statement.order_by(Entry.created_at.asc())
            )
        )
