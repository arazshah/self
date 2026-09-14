from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Entry, User


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

    def list_for_user(self, user_id: int) -> list[Entry]:
        return list(
            self.session.scalars(
                select(Entry)
                .where(Entry.user_id == user_id)
                .order_by(Entry.created_at.asc())
            )
        )
