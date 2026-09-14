from datetime import UTC, datetime

from app.models import Entry, ExtractedRecord
from app.reports import build_digest
from app.repositories import UserRepository


def test_daily_and_weekly_digest_are_scoped_and_include_categories(session):
    user = UserRepository(session).get_or_create_by_bale_chat(301, "آراز")
    other = UserRepository(session).get_or_create_by_bale_chat(302, "دیگری")
    day = datetime(2026, 9, 14, 7, tzinfo=UTC)
    entry = Entry(
        user_id=user.id, source_message_id=1, transcript="ایده و کار", created_at=day
    )
    other_entry = Entry(
        user_id=other.id, source_message_id=2, transcript="محرمانه", created_at=day
    )
    session.add_all([entry, other_entry])
    session.flush()
    session.add_all(
        [
            ExtractedRecord(
                user_id=user.id,
                entry_id=entry.id,
                category="idea",
                title="ایدهٔ داشبورد",
                evidence="ایده",
                confidence=0.9,
                status="confirmed",
            ),
            ExtractedRecord(
                user_id=user.id,
                entry_id=entry.id,
                category="reflection",
                title="کمی خسته بودم",
                body="خستگی از کار زیاد",
                evidence="امروز خسته بودم",
                confidence=0.8,
                status="confirmed",
            ),
            ExtractedRecord(
                user_id=other.id,
                entry_id=other_entry.id,
                category="finance",
                title="اطلاعات خصوصی دیگران",
                evidence="نباید دیده شود",
                confidence=0.8,
                status="confirmed",
            ),
        ]
    )
    session.flush()

    daily = build_digest(session, user, day, "daily")
    weekly = build_digest(session, user, day, "weekly")

    assert "ایدهٔ داشبورد" in daily
    assert "خستگی از کار زیاد" in daily
    assert "اطلاعات خصوصی دیگران" not in daily
    assert "گزارش هفتگی" in weekly
