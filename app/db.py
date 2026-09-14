from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base


def make_engine(database_path: str):
    return create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )


@event.listens_for(Engine, "connect")
def _configure_sqlite(dbapi_connection, _connection_record) -> None:
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


def init_db(engine) -> None:
    Base.metadata.create_all(engine)
    _migrate_existing_schema(engine)


def _migrate_existing_schema(engine) -> None:
    """Add columns introduced after the first release without replacing data."""
    additions = {
        "entries": {
            "revision": "INTEGER NOT NULL DEFAULT 1",
            "awaiting_edit": "BOOLEAN NOT NULL DEFAULT 0",
            "deleted_at": "DATETIME",
        },
        "extracted_records": {"deleted_at": "DATETIME"},
        "reminders": {"deleted_at": "DATETIME"},
    }
    with engine.begin() as connection:
        for table, columns in additions.items():
            existing = {
                row[1]
                for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
            }
            for column, definition in columns.items():
                if column not in existing:
                    connection.exec_driver_sql(
                        f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                    )


@contextmanager
def session_scope(engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
