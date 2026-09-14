from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Reminder, User


@dataclass(frozen=True, slots=True)
class SchedulerStats:
    delivered: int = 0
    failed: int = 0


async def run_scheduler_once(
    session: Session,
    notifier,
    now: datetime | None = None,
    limit: int = 100,
) -> SchedulerStats:
    current = now or datetime.now(UTC)
    reminders = list(
        session.scalars(
            select(Reminder)
            .join(User, User.id == Reminder.user_id)
            .where(
                Reminder.status == "pending",
                Reminder.due_at <= current,
                (Reminder.snooze_until.is_(None) | (Reminder.snooze_until <= current)),
            )
            .order_by(Reminder.due_at.asc())
            .limit(limit)
        )
    )
    delivered = 0
    failed = 0
    for reminder in reminders:
        user = session.get(User, reminder.user_id)
        if user is None:
            reminder.status = "cancelled"
            session.commit()
            continue
        reminder.status = "sending"
        session.flush()
        session.commit()
        try:
            await notifier.send_message(user.bale_chat_id, f"یادآوری: {reminder.text}")
        except Exception:
            reminder.status = "pending"
            session.commit()
            failed += 1
            continue
        reminder.status = "sent"
        reminder.delivered_at = current
        session.commit()
        delivered += 1
    return SchedulerStats(delivered=delivered, failed=failed)
