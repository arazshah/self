from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import jdatetime

from app.schemas import ResolvedDate

MONTHS = {
    "فروردین": 1,
    "اردیبهشت": 2,
    "خرداد": 3,
    "تیر": 4,
    "مرداد": 5,
    "شهریور": 6,
    "مهر": 7,
    "آبان": 8,
    "آذر": 9,
    "دی": 10,
    "بهمن": 11,
    "اسفند": 12,
}
WEEKDAYS = {
    "شنبه": 5,
    "یکشنبه": 6,
    "دوشنبه": 0,
    "سهشنبه": 1,
    "چهارشنبه": 2,
    "پنجشنبه": 3,
    "جمعه": 4,
}
HOUR_WORDS = {
    "یک": 1, "دو": 2, "سه": 3, "چهار": 4, "پنج": 5, "شش": 6,
    "هفت": 7, "هشت": 8, "نه": 9, "ده": 10, "یازده": 11, "دوازده": 12,
    "سیزده": 13, "چهارده": 14, "پانزده": 15, "شانزده": 16,
    "هفده": 17, "هجده": 18, "نوزده": 19, "بیست": 20,
    "بیست و یک": 21, "بیست و دو": 22, "بیست و سه": 23,
}
DURATION_WORDS = {
    "یک": 1, "دو": 2, "سه": 3, "چهار": 4, "پنج": 5, "شش": 6,
    "هفت": 7, "هشت": 8, "نه": 9, "ده": 10, "یازده": 11,
    "دوازده": 12, "پانزده": 15, "بیست": 20, "سی": 30,
    "چهل": 40, "چهل و پنج": 45, "پنجاه": 50,
}
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
PERSIAN_OUTPUT_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _normalize(text: str) -> str:
    return (
        text.translate(PERSIAN_DIGITS)
        .replace("ي", "ی")
        .replace("ك", "ک")
        .replace("‌", "")
        .replace("ٔ", "")
        .strip()
    )


def _time(text: str) -> tuple[int, int] | None:
    words = "|".join(re.escape(word) for word in sorted(HOUR_WORDS, key=len, reverse=True))
    match = re.search(
        rf"ساعت\s*(\d{{1,2}}|{words})(?:(?:\s*[:：]\s*|\s*و\s*)(\d{{1,2}})(?:\s*دقیقه)?)?",
        text,
    )
    if not match:
        match = re.search(r"(?<!\d)(\d{1,2})\s*[:：]\s*(\d{2})(?!\d)", text)
    if not match:
        bare = re.search(
            rf"(?:^|\s)(\d{{1,2}}|{words})\s*(?:صبح|عصر|شب|بامداد)(?=\s|$)", text
        )
        if not bare:
            return None
        hour = int(bare.group(1)) if bare.group(1).isdigit() else HOUR_WORDS[bare.group(1)]
        minute = 0
    else:
        hour = int(match.group(1)) if match.group(1).isdigit() else HOUR_WORDS[match.group(1)]
        minute = int(match.group(2) or (30 if re.search(r"\sو\s*نیم", text[match.end():]) else 0))
    if "شب" in text or "عصر" in text or "بعدازظهر" in text:
        if hour < 12:
            hour += 12
    elif "بامداد" in text and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        raise ValueError("زمان نامعتبر است")
    return hour, minute


def _relative_duration(text: str, local_now: datetime) -> datetime | None:
    words = "|".join(re.escape(word) for word in sorted(DURATION_WORDS, key=len, reverse=True))
    number = rf"(\d+|{words})"
    minute_match = re.search(rf"{number}\s*دقیقه\s*(?:دیگه|دیگر|بعد)", text)
    if minute_match:
        amount = minute_match.group(1)
        minutes = int(amount) if amount.isdigit() else DURATION_WORDS[amount]
        return local_now + timedelta(minutes=minutes) if minutes > 0 else None
    if re.search(r"نیم\s*ساعت\s*(?:دیگه|دیگر|بعد)", text):
        return local_now + timedelta(minutes=30)
    hour_match = re.search(rf"{number}\s*ساعت\s*(?:دیگه|دیگر|بعد)", text)
    if hour_match:
        amount = hour_match.group(1)
        hours = int(amount) if amount.isdigit() else DURATION_WORDS[amount]
        return local_now + timedelta(hours=hours) if hours > 0 else None
    return None


def _solar_to_utc(year: int, month: int, day: int, hour: int, minute: int, tz: ZoneInfo):
    gregorian = jdatetime.datetime(year, month, day, hour, minute).togregorian()
    return gregorian.replace(tzinfo=tz).astimezone(UTC)


def _solar_date_string(year: int, month: int, day: int) -> str:
    return f"{year:04d}/{month:02d}/{day:02d}".translate(PERSIAN_OUTPUT_DIGITS)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def format_persian_date(value: datetime, timezone_name: str = "Asia/Tehran") -> str:
    local = _aware(value).astimezone(ZoneInfo(timezone_name))
    solar = jdatetime.date.fromgregorian(date=local.date())
    return _solar_date_string(solar.year, solar.month, solar.day)


def format_persian_time(value: datetime, timezone_name: str = "Asia/Tehran") -> str:
    local = _aware(value).astimezone(ZoneInfo(timezone_name))
    return f"{local.hour:02d}:{local.minute:02d}".translate(PERSIAN_OUTPUT_DIGITS)


def format_persian_datetime(value: datetime, timezone_name: str = "Asia/Tehran") -> str:
    return f"{format_persian_date(value, timezone_name)}، {format_persian_time(value, timezone_name)}"


def resolve_persian_datetime(text: str, now: datetime, timezone_name: str) -> ResolvedDate:
    raw = text
    normalized = _normalize(text)
    tz = ZoneInfo(timezone_name)
    local_now = now.astimezone(tz)
    solar_now = jdatetime.date.fromgregorian(date=local_now.date())
    relative = _relative_duration(normalized, local_now)
    if relative is not None:
        solar = jdatetime.date.fromgregorian(date=relative.date())
        return ResolvedDate(
            raw=raw,
            value=relative.astimezone(UTC),
            solar_date=_solar_date_string(solar.year, solar.month, solar.day),
        )

    def unclear(message: str) -> ResolvedDate:
        return ResolvedDate(raw=raw, needs_confirmation=True, clarification=message)

    if re.search(r"(?:دیروز|پریروز|هفته\s*(?:گذشته|قبل)|ماه\s*(?:گذشته|قبل))", normalized):
        return unclear("زمان گفته‌شده در گذشته است؛ تاریخ و ساعت آینده را مشخص کن.")
    if re.search(r"(?:12|دوازده)\s*شب", normalized):
        return unclear("ساعت ۱۲ شب مبهم است؛ لطفاً تاریخ و ساعت را به‌صورت ۰۰:۰۰ یا ۲۴ ساعته بگو.")
    try:
        parsed_time = _time(normalized)
    except ValueError:
        return unclear("ساعت یادآوری نامعتبر است؛ ساعت درست را بگو.")
    if parsed_time is None:
        return unclear("ساعت یادآوری مشخص نیست؛ روز و ساعت دقیق را بگو.")
    hour, minute = parsed_time

    def future(value: datetime, solar_date: str) -> ResolvedDate:
        if value <= now.astimezone(UTC):
            return unclear("زمان یادآوری در گذشته است؛ تاریخ و ساعت آینده را مشخص کن.")
        return ResolvedDate(raw=raw, value=value, solar_date=solar_date)

    if "بعداً" in text or "بعدا" in normalized or "وقتی فرصت" in normalized:
        return ResolvedDate(
            raw=raw,
            needs_confirmation=True,
            clarification="برای یادآوری، لطفاً روز و ساعت دقیق را مشخص کن.",
        )

    relative_days = {"پسفردا": 2, "فردا": 1, "امروز": 0}
    for phrase, days in relative_days.items():
        if phrase in normalized.replace(" ", ""):
            local_value = local_now + timedelta(days=days)
            local_value = local_value.replace(hour=hour, minute=minute, second=0, microsecond=0)
            solar = jdatetime.date.fromgregorian(date=local_value.date())
            return future(local_value.astimezone(UTC), _solar_date_string(solar.year, solar.month, solar.day))

    compact = normalized.replace(" ", "")
    next_week = "هفتهآینده" in compact or "هفتهبعد" in compact
    this_week = "اینهفته" in compact
    for name, weekday in sorted(WEEKDAYS.items(), key=lambda item: len(item[0]), reverse=True):
        if name in compact:
            if next_week or this_week:
                week_start = local_now.date() - timedelta(days=(local_now.weekday() - 5) % 7)
                target_date = week_start + timedelta(days=(weekday - 5) % 7 + (7 if next_week else 0))
                delta = (target_date - local_now.date()).days
            else:
                delta = (weekday - local_now.weekday()) % 7
            local_value = (local_now + timedelta(days=delta)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            solar = jdatetime.date.fromgregorian(date=local_value.date())
            return future(local_value.astimezone(UTC), _solar_date_string(solar.year, solar.month, solar.day))

    explicit = re.search(
        r"(?:(\d{4})\s*[/\-]\s*)?(\d{1,2})\s*[/\-]\s*(\d{1,2})", normalized
    )
    if explicit:
        year = int(explicit.group(1) or solar_now.year)
        month, day = int(explicit.group(2)), int(explicit.group(3))
    else:
        month_match = re.search(
            r"(\d{1,2})\s*(فروردین|اردیبهشت|خرداد|تیر|مرداد|شهریور|مهر|آبان|آذر|دی|بهمن|اسفند)",
            normalized,
        )
        if not month_match:
            return ResolvedDate(
                raw=raw,
                needs_confirmation=True,
                clarification="تاریخ یا ساعت یادآوری مشخص نیست.",
            )
        day = int(month_match.group(1))
        month = MONTHS[month_match.group(2)]
        year = solar_now.year

    try:
        value = _solar_to_utc(year, month, day, hour, minute, tz)
    except (ValueError, OverflowError):
        return ResolvedDate(
            raw=raw,
            needs_confirmation=True,
            clarification="این تاریخ معتبر نیست؛ لطفاً دوباره بررسی کن.",
        )
    return future(value, _solar_date_string(year, month, day))
