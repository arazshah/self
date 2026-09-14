from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine

from app.db import init_db, session_scope
from app.models import Reminder
from app.repositories import UserRepository
from app.scheduler import run_scheduler_once


class FakeNotifier:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))


@pytest.mark.asyncio
async def test_scheduler_delivers_due_reminder_once(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'scheduler.sqlite3'}")
    init_db(engine)
    now = datetime(2026, 9, 14, 8, tzinfo=UTC)
    notifier = FakeNotifier()

    with session_scope(engine) as session:
        user = UserRepository(session).get_or_create_by_bale_chat(101, "A")
        session.add(
            Reminder(
                user_id=user.id,
                text="به علی زنگ بزن",
                due_at=now - timedelta(minutes=1),
            )
        )
        session.flush()
        stats = await run_scheduler_once(session, notifier, now)

    assert stats.delivered == 1
    assert notifier.messages == [(101, "یادآوری: به علی زنگ بزن")]

    with session_scope(engine) as session:
        stats = await run_scheduler_once(session, notifier, now)
    assert stats.delivered == 0
    assert len(notifier.messages) == 1


@pytest.mark.asyncio
async def test_scheduler_does_not_deliver_future_reminders(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'scheduler-future.sqlite3'}")
    init_db(engine)
    now = datetime(2026, 9, 14, 8, tzinfo=UTC)
    notifier = FakeNotifier()

    with session_scope(engine) as session:
        user = UserRepository(session).get_or_create_by_bale_chat(101, "A")
        session.add(Reminder(user_id=user.id, text="بعداً", due_at=now + timedelta(days=1)))
        stats = await run_scheduler_once(session, notifier, now)

    assert stats.delivered == 0
    assert notifier.messages == []
