from datetime import UTC, datetime

import pytest

from app.models import ExtractedRecord, Reminder
from app.pipeline import process_entry
from app.repositories import EntryRepository, UserRepository
from app.schemas import ExtractedItem, ExtractionResult


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
