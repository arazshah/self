from datetime import UTC, datetime

from app.models import ExtractedRecord, Reminder
from app.repositories import EntryRepository, UserRepository


def test_owned_lifecycle_supports_revision_and_soft_delete(session):
    users = UserRepository(session)
    owner = users.get_or_create_by_bale_chat(501, "مالک")
    other = users.get_or_create_by_bale_chat(502, "دیگری")
    entries = EntryRepository(session)
    entry = entries.create(
        owner.id,
        "متن اولیه",
        datetime(2026, 9, 14, tzinfo=UTC),
        source_message_id=51,
    )
    record = ExtractedRecord(
        user_id=owner.id,
        entry_id=entry.id,
        category="task",
        title="کار اولیه",
        confidence=0.9,
    )
    session.add(record)
    session.flush()
    reminder = Reminder(
        user_id=owner.id,
        record_id=record.id,
        text="کار اولیه",
        due_at=datetime(2026, 9, 15, tzinfo=UTC),
    )
    session.add(reminder)
    session.flush()

    assert entries.get_owned_entry(entry.id, owner.id) is entry
    assert entries.get_owned_entry(entry.id, other.id) is None
    assert entries.get_owned_record(record.id, owner.id).id == record.id
    assert entries.get_owned_record(record.id, other.id) is None

    updated = entries.update_entry_text(entry.id, owner.id, "متن اصلاح‌شده")
    assert updated.transcript == "متن اصلاح‌شده"
    assert updated.revision == 2
    assert updated.status == "received"

    assert entries.soft_delete_record(record.id, other.id) is False
    assert entries.soft_delete_record(record.id, owner.id) is True
    assert entries.soft_delete_reminder(reminder.id, owner.id) is True
    assert entries.soft_delete_entry(entry.id, owner.id) is True
    assert entries.get_owned_entry(entry.id, owner.id) is None
    assert entries.list_for_user(owner.id) == []
