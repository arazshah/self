from datetime import UTC, datetime, timedelta
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


class MarkupBale(FakeBale):
    def __init__(self):
        super().__init__()
        self.markups = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.markups.append(reply_markup)
        return await super().send_message(chat_id, text)


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
async def test_pipeline_uses_original_text_when_model_drops_relative_time(session):
    user = UserRepository(session).get_or_create_by_bale_chat(108, "کاربر پنج دقیقه")
    text = "امروز ۵ دقیقه دیگه بهم یادآوری کن و بگو سلام"
    entry = EntryRepository(session).create(user.id, text, datetime(2026, 9, 15, 6, 20, tzinfo=UTC), 17)

    class TruncatedTimeAI(FakeAI):
        async def extract(self, text, now, timezone_name):
            result = await super().extract(text, now, timezone_name)
            result.items[0].due_raw = "امروز"
            result.items[0].due_at = None
            result.items[0].title = "سلام"
            result.items[0].body = "سلام"
            return result

    await process_entry(
        session, entry, user, ai_client=TruncatedTimeAI(), bale_client=FakeBale(),
        now=datetime(2026, 9, 15, 5, 50, tzinfo=UTC)
    )
    reminder = session.query(Reminder).one()
    stored_due = reminder.due_at.replace(tzinfo=UTC).astimezone(TEHRAN)
    assert (stored_due.hour, stored_due.minute) == (9, 25)


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


@pytest.mark.asyncio
async def test_pipeline_never_uses_model_due_at_without_user_time(session):
    user = UserRepository(session).get_or_create_by_bale_chat(109, "کاربر زمان مبهم")
    entry = EntryRepository(session).create(
        user.id, "فردا یادآوری کن زنگ بزنم", datetime(2026, 9, 15, 12, tzinfo=UTC), 18
    )

    class InventedTimeAI(FakeAI):
        async def extract(self, text, now, timezone_name):
            return ExtractionResult(items=[ExtractedItem(
                category="reminder", title="زنگ زدن", evidence=text, due_raw="فردا",
                due_at=datetime(2026, 9, 16, 6, tzinfo=UTC), confidence=0.9,
                needs_confirmation=False,
            )])

    bale = FakeBale()
    await process_entry(
        session, entry, user, ai_client=InventedTimeAI(), bale_client=bale,
        now=datetime(2026, 9, 15, 12, tzinfo=UTC),
    )
    assert session.query(Reminder).count() == 0
    assert session.query(ExtractedRecord).one().status == "needs_confirmation"
    assert "ساعت" in bale.messages[0][1]
    assert "ثبت شد" not in bale.messages[0][1]


@pytest.mark.asyncio
async def test_pipeline_rejects_past_reminder_and_echoes_exact_future_time(session):
    user = UserRepository(session).get_or_create_by_bale_chat(110, "کاربر زمان دقیق")
    past = EntryRepository(session).create(
        user.id, "امروز ساعت ۹ یادآوری کن", datetime(2026, 9, 15, 12, tzinfo=UTC), 19
    )

    class TimeAI(FakeAI):
        async def extract(self, text, now, timezone_name):
            due_raw = "امروز ساعت ۹" if "امروز" in text else "فردا ساعت ۹ شب"
            return ExtractionResult(items=[ExtractedItem(
                category="reminder", title="تماس", evidence=text, due_raw=due_raw,
                confidence=0.9, needs_confirmation=False,
            )])

    bale = FakeBale()
    now = datetime(2026, 9, 15, 12, tzinfo=UTC)
    await process_entry(session, past, user, ai_client=TimeAI(), bale_client=bale, now=now)
    assert session.query(Reminder).count() == 0
    assert "گذشته" in bale.messages[-1][1]

    future = EntryRepository(session).create(user.id, "فردا ساعت ۹ شب یادآوری کن", now, 20)
    await process_entry(session, future, user, ai_client=TimeAI(), bale_client=bale, now=now)
    assert session.query(Reminder).count() == 1
    assert "۲۱:۰۰" in bale.messages[-1][1]


@pytest.mark.asyncio
async def test_pipeline_prefers_user_spoken_hour_over_model_due_raw(session):
    user = UserRepository(session).get_or_create_by_bale_chat(111, "کاربر ساعت دقیق")
    text = "فردا ساعت ۱۰ صبح یادآوری کن تماس بگیرم"
    entry = EntryRepository(session).create(user.id, text, datetime(2026, 9, 15, 12, tzinfo=UTC), 21)

    class WrongHourAI(FakeAI):
        async def extract(self, text, now, timezone_name):
            return ExtractionResult(items=[ExtractedItem(
                category="reminder", title="تماس", evidence="فردا ساعت ۹",
                due_raw="فردا ساعت ۹", confidence=0.9, needs_confirmation=False,
            )])

    bale = FakeBale()
    await process_entry(
        session, entry, user, ai_client=WrongHourAI(), bale_client=bale,
        now=datetime(2026, 9, 15, 12, tzinfo=UTC),
    )
    due = session.query(Reminder).one().due_at.replace(tzinfo=UTC).astimezone(TEHRAN)
    assert due.hour == 10
    assert "۱۰:۰۰" in bale.messages[-1][1]


@pytest.mark.asyncio
async def test_pipeline_uses_each_spoken_time_for_two_reminders(session):
    user = UserRepository(session).get_or_create_by_bale_chat(112, "کاربر دو زمان")
    text = "فردا ساعت ۹ به علی زنگ بزنم و پس‌فردا ساعت ۱۰ قبض را پرداخت کنم"
    entry = EntryRepository(session).create(user.id, text, datetime(2026, 9, 15, 12, tzinfo=UTC), 22)

    class TwoItemsAI(FakeAI):
        async def extract(self, text, now, timezone_name):
            return ExtractionResult(items=[
                ExtractedItem(category="reminder", title="تماس با علی", evidence="فردا ساعت ۹ به علی زنگ بزنم",
                              due_raw="فردا ساعت ۹", confidence=0.9, needs_confirmation=False),
                ExtractedItem(category="reminder", title="پرداخت قبض", evidence="پس‌فردا ساعت ۱۰ قبض را پرداخت کنم",
                              due_raw="پس‌فردا ساعت ۱۰", confidence=0.9, needs_confirmation=False),
            ])

    await process_entry(
        session, entry, user, ai_client=TwoItemsAI(), bale_client=FakeBale(),
        now=datetime(2026, 9, 15, 12, tzinfo=UTC),
    )
    reminders = session.query(Reminder).order_by(Reminder.id).all()
    assert len(reminders) == 2
    first = reminders[0].due_at.replace(tzinfo=UTC).astimezone(TEHRAN)
    second = reminders[1].due_at.replace(tzinfo=UTC).astimezone(TEHRAN)
    assert first.date() != second.date()
    assert (first.hour, second.hour) == (9, 10)


@pytest.mark.asyncio
async def test_opinion_mentioning_a_past_clock_is_not_treated_as_reminder(session):
    user = UserRepository(session).get_or_create_by_bale_chat(113, "کاربر نظر زمانی")
    text = "به نظرم جلسه دیروز ساعت ۹ خوب بود"
    entry = EntryRepository(session).create(user.id, text, datetime(2026, 9, 15, 12, tzinfo=UTC), 23)

    class OpinionAI(FakeAI):
        async def extract(self, text, now, timezone_name):
            return ExtractionResult(items=[ExtractedItem(
                category="opinion", title="نظر درباره جلسه", evidence=text,
                confidence=0.9, needs_confirmation=False,
            )])

    bale = FakeBale()
    await process_entry(session, entry, user, ai_client=OpinionAI(), bale_client=bale,
                        now=datetime(2026, 9, 15, 12, tzinfo=UTC))
    assert session.query(Reminder).count() == 0
    assert session.query(ExtractedRecord).one().status == "confirmed"
    assert "زمان‌بندی نشد" not in bale.messages[0][1]


@pytest.mark.asyncio
async def test_relative_due_that_passes_during_processing_is_not_queued(session, monkeypatch):
    user = UserRepository(session).get_or_create_by_bale_chat(114, "کاربر زمان پردازش")
    start = datetime(2026, 9, 15, 12, tzinfo=UTC)
    entry = EntryRepository(session).create(user.id, "پنج دقیقه دیگر یادآوری کن", start, 24)

    class RelativeAI(FakeAI):
        async def extract(self, text, now, timezone_name):
            return ExtractionResult(items=[ExtractedItem(
                category="reminder", title="سلام", evidence=text,
                due_raw="پنج دقیقه دیگر", confidence=0.9, needs_confirmation=False,
            )])

    calls = 0

    def clock():
        nonlocal calls
        calls += 1
        return start if calls == 1 else start + timedelta(minutes=10)

    monkeypatch.setattr("app.pipeline.utc_now", clock)
    bale = FakeBale()
    await process_entry(session, entry, user, ai_client=RelativeAI(), bale_client=bale)
    assert session.query(Reminder).count() == 0
    assert "گذشته" in bale.messages[-1][1]


@pytest.mark.asyncio
async def test_ambiguous_reminder_offers_bale_correction_button(session):
    user = UserRepository(session).get_or_create_by_bale_chat(115, "کاربر اصلاح")
    entry = EntryRepository(session).create(
        user.id, "فردا یادآوری کن تماس بگیرم", datetime(2026, 9, 15, 12, tzinfo=UTC), 25
    )

    class NoHourAI(FakeAI):
        async def extract(self, text, now, timezone_name):
            return ExtractionResult(items=[ExtractedItem(
                category="reminder", title="تماس", evidence=text, due_raw="فردا",
                confidence=0.9, needs_confirmation=False,
            )])

    bale = MarkupBale()
    await process_entry(
        session, entry, user, ai_client=NoHourAI(), bale_client=bale,
        now=datetime(2026, 9, 15, 12, tzinfo=UTC),
    )
    assert bale.markups[0]["inline_keyboard"][0][0]["callback_data"] == f"entry:edit:{entry.id}"
    assert "اصلاح زمان" in bale.markups[0]["inline_keyboard"][0][0]["text"]


@pytest.mark.asyncio
async def test_partial_evidence_does_not_hide_spoken_day(session):
    user = UserRepository(session).get_or_create_by_bale_chat(116, "کاربر شاهد کوتاه")
    text = "فردا ساعت ۹ به علی زنگ بزنم"
    entry = EntryRepository(session).create(user.id, text, datetime(2026, 9, 15, 12, tzinfo=UTC), 26)

    class PartialEvidenceAI(FakeAI):
        async def extract(self, text, now, timezone_name):
            return ExtractionResult(items=[ExtractedItem(
                category="reminder", title="تماس با علی", evidence="ساعت ۹ به علی زنگ بزنم",
                due_raw="فردا ساعت ۹", confidence=0.9, needs_confirmation=False,
            )])

    await process_entry(
        session, entry, user, ai_client=PartialEvidenceAI(), bale_client=FakeBale(),
        now=datetime(2026, 9, 15, 12, tzinfo=UTC),
    )
    assert session.query(Reminder).count() == 1


@pytest.mark.asyncio
async def test_completed_past_payment_is_recorded_without_reminder_warning(session):
    user = UserRepository(session).get_or_create_by_bale_chat(117, "کاربر پرداخت قبلی")
    text = "دیروز ساعت ۹ قبض برق را پرداخت کردم"
    entry = EntryRepository(session).create(user.id, text, datetime(2026, 9, 15, 12, tzinfo=UTC), 27)

    class PastPaymentAI(FakeAI):
        async def extract(self, text, now, timezone_name):
            return ExtractionResult(items=[ExtractedItem(
                category="finance", title="پرداخت قبض برق", evidence=text,
                confidence=0.9, needs_confirmation=False,
            )])

    bale = FakeBale()
    await process_entry(session, entry, user, ai_client=PastPaymentAI(), bale_client=bale,
                        now=datetime(2026, 9, 15, 12, tzinfo=UTC))
    assert session.query(ExtractedRecord).one().status == "confirmed"
    assert session.query(Reminder).count() == 0
    assert "زمان‌بندی نشد" not in bale.messages[0][1]
