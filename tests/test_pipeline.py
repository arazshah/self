from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.models import ExtractedRecord, Reminder
from app.pipeline import process_entry
from app.repositories import EntryRepository, UserRepository
from app.schemas import ExtractedItem, ExtractionResult

TEHRAN = ZoneInfo("Asia/Tehran")


class FakeAI:
    async def transcribe(self, audio: bytes, filename: str = "voice.ogg") -> str:
        return "فردا ساعت ۹ قبض برق را پرداخت کنم"

    async def extract(
        self, text: str, now: datetime | str | None = None, timezone_name: str = "Asia/Tehran"
    ) -> ExtractionResult:
        return ExtractionResult(
            items=[
                ExtractedItem(
                    category="finance",
                    title="پرداخت قبض برق",
                    body="قبض برق این ماه پرداخت شود",
                    evidence=text,
                    due_raw="فردا ساعت ۹",
                    confidence=0.96,
                    needs_confirmation=False,
                )
            ]
        )


class FakeBale:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> dict:
        self.messages.append((chat_id, text))
        return {"ok": True}


class VoiceBale(FakeBale):
    async def get_file(self, file_id: str) -> dict:
        return {"file_path": "voice/file.ogg"}

    async def download_file(self, file_path: str) -> bytes:
        return b"audio"


class TransactionCheckingBale(FakeBale):
    def __init__(self, session):
        super().__init__()
        self.session = session

    async def send_message(self, chat_id: int, text: str, reply_markup=None) -> dict:
        assert not self.session.in_transaction()
        return await super().send_message(chat_id, text)


@pytest.mark.asyncio
async def test_process_entry_persists_top_level_reflection_and_suggestion(session):
    user = UserRepository(session).get_or_create_by_bale_chat(104, "کاربر احساسات")
    entry = EntryRepository(session).create(
        user_id=user.id,
        transcript="امروز از فشار کار خسته بودم",
        created_at=datetime(2026, 9, 14, 5, 0, tzinfo=UTC),
        source_message_id=13,
    )

    class ReflectionAI(FakeAI):
        async def extract(
            self, text: str, now: datetime | str | None = None, timezone_name: str = "Asia/Tehran"
        ) -> ExtractionResult:
            return ExtractionResult(
                reflection_summary="خستگی و فشار کاری",
                suggestion="امروز یک وقفهٔ کوتاه برای استراحت بگذار.",
            )

    await process_entry(
        session,
        entry,
        user,
        ai_client=ReflectionAI(),
        bale_client=FakeBale(),
        now=datetime(2026, 9, 14, 5, 0, tzinfo=UTC),
    )

    record = session.query(ExtractedRecord).one()
    assert record.category == "reflection"
    assert record.title == "خستگی و فشار کاری"
    assert record.body == "امروز یک وقفهٔ کوتاه برای استراحت بگذار."


@pytest.mark.asyncio
async def test_process_entry_releases_sqlite_transaction_before_bale_call(session):
    user = UserRepository(session).get_or_create_by_bale_chat(105, "کاربر هم‌زمان")
    entry = EntryRepository(session).create(
        user_id=user.id,
        transcript="یک ایده دارم",
        created_at=datetime(2026, 9, 14, 5, 0, tzinfo=UTC),
        source_message_id=14,
    )
    session.commit()

    await process_entry(
        session,
        entry,
        user,
        ai_client=FakeAI(),
        bale_client=TransactionCheckingBale(session),
        now=datetime(2026, 9, 14, 5, 0, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_process_entry_extracts_record_and_creates_reminder(session):
    user = UserRepository(session).get_or_create_by_bale_chat(101, "آراز")
    entry = EntryRepository(session).create(
        user_id=user.id,
        transcript="فردا ساعت ۹ قبض برق را پرداخت کنم",
        created_at=datetime(2026, 9, 14, 5, 0, tzinfo=UTC),
        source_message_id=10,
    )
    bale = FakeBale()

    result = await process_entry(
        session,
        entry,
        user,
        ai_client=FakeAI(),
        bale_client=bale,
        now=datetime(2026, 9, 14, 5, 0, tzinfo=UTC),
    )

    record = session.query(ExtractedRecord).one()
    reminder = session.query(Reminder).one()
    assert result.items[0].title == "پرداخت قبض برق"
    assert record.user_id == user.id
    assert record.status == "confirmed"
    assert reminder.user_id == user.id
    assert reminder.text == "پرداخت قبض برق"
    assert entry.status == "processed"
    assert bale.messages and bale.messages[0][0] == 101


@pytest.mark.asyncio
async def test_process_entry_keeps_ambiguous_date_as_confirmation(session):
    user = UserRepository(session).get_or_create_by_bale_chat(102, "کاربر دوم")
    entry = EntryRepository(session).create(
        user_id=user.id,
        transcript="بعداً به علی زنگ بزنم",
        created_at=datetime(2026, 9, 14, 5, 0, tzinfo=UTC),
        source_message_id=11,
    )

    class AmbiguousAI(FakeAI):
        async def extract(
            self, text: str, now: datetime | str | None = None, timezone_name: str = "Asia/Tehran"
        ) -> ExtractionResult:
            return ExtractionResult(
                items=[
                    ExtractedItem(
                        category="follow_up",
                        title="تماس با علی",
                        evidence=text,
                        due_raw="بعداً",
                        confidence=0.7,
                        needs_confirmation=False,
                    )
                ]
            )

    await process_entry(
        session,
        entry,
        user,
        ai_client=AmbiguousAI(),
        bale_client=FakeBale(),
        now=datetime(2026, 9, 14, 5, 0, tzinfo=UTC),
    )

    record = session.query(ExtractedRecord).one()
    assert record.status == "needs_confirmation"
    assert session.query(Reminder).count() == 0


@pytest.mark.asyncio
async def test_process_entry_transcribes_voice_without_persisting_audio(session):
    user = UserRepository(session).get_or_create_by_bale_chat(103, "کاربر صوتی")
    entry = EntryRepository(session).create(
        user_id=user.id,
        transcript="",
        created_at=datetime(2026, 9, 14, 5, 0, tzinfo=UTC),
        source_message_id=12,
        kind="voice",
    )
    entry.audio_path = "file-voice"

    await process_entry(
        session,
        entry,
        user,
        ai_client=FakeAI(),
        bale_client=VoiceBale(),
        now=datetime(2026, 9, 14, 5, 0, tzinfo=UTC),
    )

    assert entry.transcript == "فردا ساعت ۹ قبض برق را پرداخت کنم"
    assert entry.audio_path == "file-voice"


@pytest.mark.asyncio
async def test_pipeline_prefers_natural_language_due_raw_over_model_due_at(session):
    user = UserRepository(session).get_or_create_by_bale_chat(106, "کاربر زمان")
    entry = EntryRepository(session).create(
        user.id, "فردا ساعت ۹ قبض برق را پرداخت کنم", datetime(2026, 9, 14, 5, tzinfo=UTC), 15
    )

    class WrongDateAI(FakeAI):
        async def extract(self, text, now, timezone_name):
            result = await super().extract(text, now, timezone_name)
            result.items[0].due_at = datetime(2030, 1, 1, tzinfo=UTC)
            return result

    await process_entry(
        session, entry, user, ai_client=WrongDateAI(), bale_client=FakeBale(),
        now=datetime(2026, 9, 14, 5, tzinfo=UTC)
    )
    reminder = session.query(Reminder).one()
    stored_due = reminder.due_at.replace(tzinfo=UTC)
    assert stored_due.astimezone(TEHRAN).date().isoformat() == "2026-09-15"
    assert stored_due.astimezone(TEHRAN).hour == 9


@pytest.mark.asyncio
async def test_pipeline_does_not_create_mood_summary_for_an_opinion(session):
    user = UserRepository(session).get_or_create_by_bale_chat(107, "کاربر نظر")
    text = "به نظرم صندوقچه نرم افزار بهتری شده."
    entry = EntryRepository(session).create(user.id, text, datetime(2026, 9, 14, 5, tzinfo=UTC), 16)

    class OpinionAI(FakeAI):
        async def extract(self, text, now, timezone_name):
            return ExtractionResult(
                items=[ExtractedItem(category="reflection", title="مقایسه نرم‌افزارها", evidence=text, confidence=0.8)],
                reflection_summary="صندوقچه بهتر است",
                suggestion="استراحت کن",
            )

    await process_entry(
        session, entry, user, ai_client=OpinionAI(), bale_client=FakeBale(),
        now=datetime(2026, 9, 14, 5, tzinfo=UTC)
    )
    records = session.query(ExtractedRecord).all()
    assert len(records) == 1
    assert records[0].category == "opinion"
