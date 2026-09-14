from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import jdatetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Entry, ExtractedRecord, User
from app.time_utils import PERSIAN_OUTPUT_DIGITS, format_persian_datetime

CATEGORY_LABELS = {
    "task": "کار",
    "reminder": "یادآوری",
    "follow_up": "پیگیری",
    "finance": "مالی",
    "appointment": "قرار",
    "project": "پروژه",
    "idea": "ایده",
    "errand": "کار بیرون",
    "decision": "تصمیم",
    "opinion": "نظر",
    "reflection": "بازتاب و احساس",
}
CATEGORY_ICONS = {
    "task": "✅", "reminder": "⏰", "follow_up": "📞", "finance": "💳",
    "appointment": "📅", "project": "🧩", "idea": "💡", "errand": "🛒",
    "decision": "⚖️", "reflection": "🌿",
    "opinion": "🗣️",
}


def period_bounds(now: datetime, user: User, kind: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(user.timezone)
    local = now.astimezone(tz)
    local_day = local.date()
    if kind == "weekly":
        delta = (local.weekday() - user.week_start) % 7
        start_date = local_day - timedelta(days=delta)
        end_date = start_date + timedelta(days=7)
    else:
        start_date = local_day
        end_date = start_date + timedelta(days=1)
    start = datetime.combine(start_date, time.min, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(end_date, time.min, tzinfo=tz).astimezone(UTC)
    return start, end


_period = period_bounds


def _db_datetime(value: datetime) -> datetime:
    """SQLite stores DateTime values without timezone metadata."""
    return value.astimezone(UTC).replace(tzinfo=None)


def _solar(value: datetime, user: User) -> str:
    local = value.astimezone(ZoneInfo(user.timezone))
    date = jdatetime.date.fromgregorian(date=local.date())
    return f"{date.year:04d}/{date.month:02d}/{date.day:02d}".translate(PERSIAN_OUTPUT_DIGITS)


def build_digest(session: Session, user: User, now: datetime, kind: str = "daily") -> str:
    if kind not in {"daily", "weekly"}:
        raise ValueError("نوع گزارش باید daily یا weekly باشد")
    start, end = _period(now, user, kind)
    records = list(
        session.scalars(
            select(ExtractedRecord)
            .join(Entry, Entry.id == ExtractedRecord.entry_id)
            .where(
                ExtractedRecord.user_id == user.id,
                ExtractedRecord.deleted_at.is_(None),
                Entry.deleted_at.is_(None),
                Entry.created_at >= _db_datetime(start),
                Entry.created_at < _db_datetime(end),
            )
            .order_by(Entry.created_at.asc(), ExtractedRecord.id.asc())
        )
    )
    title = "گزارش روزانه" if kind == "daily" else "گزارش هفتگی"
    lines = [f"{title} | { _solar(start, user) }", ""]
    if not records:
        lines.append("در این بازه هنوز چیزی در صندوقچه ثبت نشده است.")
        return "\n".join(lines)

    grouped: dict[str, list[ExtractedRecord]] = {}
    for record in records:
        grouped.setdefault(record.category, []).append(record)
    lines.append(f"تعداد موارد ثبت‌شده: {len(records)}")
    for category, items in grouped.items():
        lines.append(f"\n{CATEGORY_ICONS.get(category, '•')} {CATEGORY_LABELS.get(category, category)}:")
        for item in items:
            detail = f" — {item.body}" if item.body else ""
            entry_time = session.scalar(select(Entry.created_at).where(Entry.id == item.entry_id))
            stamp = f" ({format_persian_datetime(entry_time, user.timezone)})" if entry_time else ""
            lines.append(f"• {item.title}{detail}{stamp}")

    reflections = grouped.get("reflection", [])
    if reflections:
        lines.extend(["", "برداشت از حال و هوا:"])
        for item in reflections:
            lines.append(f"• {item.title}: {item.body or item.evidence or 'بدون توضیح بیشتر'}")
        lines.append("پیشنهاد: اگر این الگو تکرار شد، یک اقدام کوچک و قابل انجام برای سبک‌تر شدن روز انتخاب کن.")
    return "\n".join(lines)
