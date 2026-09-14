from datetime import UTC, datetime

import pytest

from app.jobs import run_digest_once
from app.models import Digest, Entry, ExtractedRecord
from app.repositories import UserRepository


class FakeNotifier:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))


@pytest.mark.asyncio
async def test_digest_job_sends_daily_once_and_weekly_on_week_start(session):
    user = UserRepository(session).get_or_create_by_bale_chat(401, "آراز")
    user.daily_digest_hour = 8
    entry = Entry(
        user_id=user.id,
        source_message_id=1,
        transcript="ایده",
        created_at=datetime(2026, 9, 14, 5, 0, tzinfo=UTC),
    )
    session.add(entry)
    session.flush()
    session.add(
        ExtractedRecord(
            user_id=user.id,
            entry_id=entry.id,
            category="idea",
            title="ایده جدید",
            confidence=0.9,
            status="confirmed",
        )
    )
    notifier = FakeNotifier()
    now = datetime(2026, 9, 14, 5, 5, tzinfo=UTC)  # ۸:۳۵ تهران، دوشنبه

    stats = await run_digest_once(session, notifier, now)
    assert stats.sent == 1
    assert len(notifier.messages) == 1
    assert "گزارش روزانه" in notifier.messages[0][1]

    again = await run_digest_once(session, notifier, now)
    assert again.sent == 0

    user.week_start = 0  # Monday, to exercise the weekly boundary in this test.
    weekly = await run_digest_once(session, notifier, now)
    assert weekly.sent == 1
    assert "گزارش هفتگی" in notifier.messages[-1][1]
    assert session.query(Digest).count() == 2
