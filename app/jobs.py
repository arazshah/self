from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Digest, User
from app.reports import _db_datetime, _period, build_digest


@dataclass(frozen=True, slots=True)
class DigestJobStats:
    sent: int = 0
    failed: int = 0


async def run_digest_once(
    session: Session, notifier, now: datetime | None = None
) -> DigestJobStats:
    current = now or datetime.now(UTC)
    sent = 0
    failed = 0
    for user in session.scalars(select(User)):
        local = current.astimezone(ZoneInfo(user.timezone))
        if local.hour != user.daily_digest_hour:
            continue
        kinds = ["daily"]
        if local.weekday() == user.week_start:
            kinds.append("weekly")
        for kind in kinds:
            # The morning digest describes the completed period, not the day/week
            # that has just started.
            reference = current - (timedelta(days=1) if kind == "daily" else timedelta(days=7))
            period_start, period_end = _period(reference, user, kind)
            exists = session.scalar(
                select(Digest.id).where(
                    Digest.user_id == user.id,
                    Digest.kind == kind,
                    Digest.period_start == _db_datetime(period_start),
                )
            )
            if exists is not None:
                continue
            content = build_digest(session, user, reference, kind)
            try:
                await notifier.send_message(user.bale_chat_id, content)
            except Exception:
                failed += 1
                continue
            session.add(
                Digest(
                    user_id=user.id,
                    kind=kind,
                    period_start=period_start,
                    period_end=period_end,
                    content=content,
                    delivered_at=current,
                )
            )
            session.flush()
            sent += 1
    return DigestJobStats(sent=sent, failed=failed)
