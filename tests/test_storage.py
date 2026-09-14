from datetime import UTC, datetime

from sqlalchemy import create_engine

from app.db import init_db, make_engine, session_scope
from app.repositories import EntryRepository, UserRepository


def test_user_is_created_once_per_bale_chat(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.sqlite3'}")
    init_db(engine)

    with session_scope(engine) as session:
        repository = UserRepository(session)
        first = repository.get_or_create_by_bale_chat(101, "A")
        second = repository.get_or_create_by_bale_chat(101, "Changed")

    assert first.id == second.id
    assert second.display_name == "A"


def test_entries_are_scoped_to_the_user(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.sqlite3'}")
    init_db(engine)

    with session_scope(engine) as session:
        users = UserRepository(session)
        first = users.get_or_create_by_bale_chat(101, "A")
        second = users.get_or_create_by_bale_chat(202, "B")
        entries = EntryRepository(session)
        entries.create(first.id, "first", datetime.now(UTC))
        entries.create(second.id, "second", datetime.now(UTC))

        first_entries = entries.list_for_user(first.id)

    assert [entry.transcript for entry in first_entries] == ["first"]


def test_sqlite_uses_wal_and_busy_timeout(tmp_path):
    engine = make_engine(str(tmp_path / "wal.sqlite3"))
    with engine.connect() as connection:
        journal_mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar()
        busy_timeout = connection.exec_driver_sql("PRAGMA busy_timeout").scalar()

    assert journal_mode.lower() == "wal"
    assert busy_timeout >= 30000
