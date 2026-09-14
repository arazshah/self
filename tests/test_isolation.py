from datetime import UTC, datetime

from sqlalchemy import create_engine, select

from app.db import init_db, session_scope
from app.models import ExtractedRecord
from app.repositories import EntryRepository, UserRepository


def test_user_scoped_record_lookup_cannot_cross_tenant(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'isolation.sqlite3'}")
    init_db(engine)

    with session_scope(engine) as session:
        users = UserRepository(session)
        first = users.get_or_create_by_bale_chat(1, "A")
        second = users.get_or_create_by_bale_chat(2, "B")
        entry = EntryRepository(session).create(
            first.id, "secret first", datetime.now(UTC), source_message_id=1
        )
        session.add(
            ExtractedRecord(
                user_id=first.id,
                entry_id=entry.id,
                category="idea",
                title="private idea",
                confidence=1,
            )
        )
        session.flush()
        records = list(
            session.scalars(
                select(ExtractedRecord).where(
                    ExtractedRecord.user_id == second.id,
                    ExtractedRecord.title == "private idea",
                )
            )
        )

    assert records == []
