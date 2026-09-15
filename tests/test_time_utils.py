from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.time_utils import (
    format_persian_date,
    format_persian_datetime,
    format_persian_time,
    resolve_persian_datetime,
)

TEHRAN = ZoneInfo("Asia/Tehran")


def test_resolves_solar_hijri_date_and_time():
    now = datetime(2026, 9, 14, 8, tzinfo=TEHRAN)
    result = resolve_persian_datetime("۲۵ مهر ساعت ۱۰:۳۰", now, "Asia/Tehran")

    assert result.needs_confirmation is False
    assert result.solar_date == "۱۴۰۵/۰۷/۲۵"
    assert result.value.astimezone(TEHRAN).hour == 10
    assert result.value.astimezone(TEHRAN).minute == 30


def test_resolves_tomorrow_in_user_timezone():
    now = datetime(2026, 9, 14, 23, 45, tzinfo=TEHRAN)
    result = resolve_persian_datetime("فردا ساعت ۹", now, "Asia/Tehran")

    assert result.value.astimezone(TEHRAN).date().isoformat() == "2026-09-15"
    assert result.value.astimezone(TEHRAN).hour == 9


def test_ambiguous_expression_requires_confirmation():
    result = resolve_persian_datetime(
        "بعداً یادم بنداز", datetime(2026, 9, 14, tzinfo=TEHRAN), "Asia/Tehran"
    )

    assert result.needs_confirmation is True
    assert result.value is None


def test_formats_utc_timestamp_as_persian_date_and_time():
    value = datetime(2026, 9, 14, 5, 30, tzinfo=UTC)

    assert format_persian_date(value, "Asia/Tehran") == "۱۴۰۵/۰۶/۲۳"
    assert format_persian_time(value, "Asia/Tehran") == "۰۹:۰۰"
    assert format_persian_datetime(value, "Asia/Tehran") == "۱۴۰۵/۰۶/۲۳، ۰۹:۰۰"


def test_resolves_this_week_weekday_without_matching_saturday_substring():
    now = datetime(2026, 9, 14, 8, tzinfo=TEHRAN)  # Monday / دوشنبه
    result = resolve_persian_datetime("این هفته سه شنبه ساعت ۱۵", now, "Asia/Tehran")
    assert result.solar_date == "۱۴۰۵/۰۶/۲۴"
    assert result.value.astimezone(TEHRAN).hour == 15


def test_resolves_next_week_weekday():
    now = datetime(2026, 9, 14, 8, tzinfo=TEHRAN)
    result = resolve_persian_datetime("هفته آینده سه شنبه ساعت ۱۵", now, "Asia/Tehran")
    assert result.solar_date == "۱۴۰۵/۰۶/۳۱"


def test_resolves_spoken_half_hour():
    now = datetime(2026, 9, 14, 8, tzinfo=TEHRAN)
    result = resolve_persian_datetime("فردا ساعت ده و نیم", now, "Asia/Tehran")
    assert result.value.astimezone(TEHRAN).hour == 10
    assert result.value.astimezone(TEHRAN).minute == 30


def test_resolves_persian_ezafe_next_week_and_written_minutes():
    now = datetime(2026, 9, 14, 8, tzinfo=TEHRAN)
    result = resolve_persian_datetime(
        "هفتهٔ آینده سه‌شنبه ساعت ۱۰ و ۳۰ دقیقه", now, "Asia/Tehran"
    )
    assert result.solar_date == "۱۴۰۵/۰۶/۳۱"
    assert result.value.astimezone(TEHRAN).hour == 10
    assert result.value.astimezone(TEHRAN).minute == 30


def test_resolves_relative_minutes_from_current_local_time():
    now = datetime(2026, 9, 15, 10, 20, 45, tzinfo=TEHRAN)
    result = resolve_persian_datetime("امروز ۵ دقیقه دیگه بهم یادآوری کن", now, "Asia/Tehran")
    due = result.value.astimezone(TEHRAN)
    assert due.date() == now.date()
    assert due.hour == 10
    assert due.minute == 25


def test_resolves_relative_half_hour():
    now = datetime(2026, 9, 15, 23, 50, tzinfo=TEHRAN)
    result = resolve_persian_datetime("نیم ساعت دیگه یادآوری کن", now, "Asia/Tehran")
    due = result.value.astimezone(TEHRAN)
    assert due.date().isoformat() == "2026-09-16"
    assert due.hour == 0
    assert due.minute == 20


def test_date_without_hour_is_not_scheduled():
    now = datetime(2026, 9, 15, 15, 30, tzinfo=TEHRAN)
    for phrase in ("امروز یادآوری کن", "فردا یادآوری کن", "هفته آینده سه شنبه"):
        result = resolve_persian_datetime(phrase, now, "Asia/Tehran")
        assert result.value is None
        assert result.needs_confirmation
        assert "ساعت" in result.clarification


def test_past_times_and_dates_are_rejected_instead_of_rolled_forward():
    now = datetime(2026, 9, 15, 15, 30, tzinfo=TEHRAN)
    for phrase in (
        "امروز ساعت ۹",
        "۱۴۰۵/۰۶/۲۳ ساعت ۱۰",
        "۲۳ شهریور ساعت ۱۰",
        "این هفته دوشنبه ساعت ۸",
        "دیروز ساعت ۱۰",
    ):
        result = resolve_persian_datetime(phrase, now, "Asia/Tehran")
        assert result.value is None
        assert result.needs_confirmation
        assert "گذشته" in result.clarification


def test_night_and_evening_hour_are_understood():
    now = datetime(2026, 9, 15, 15, 30, tzinfo=TEHRAN)
    result = resolve_persian_datetime("فردا ساعت ۹ شب", now, "Asia/Tehran")
    assert result.value.astimezone(TEHRAN).hour == 21
    evening = resolve_persian_datetime("فردا ساعت ۶ عصر", now, "Asia/Tehran")
    assert evening.value.astimezone(TEHRAN).hour == 18


def test_invalid_hour_requires_clarification_without_throwing():
    now = datetime(2026, 9, 15, 15, 30, tzinfo=TEHRAN)
    result = resolve_persian_datetime("فردا ساعت ۲۵", now, "Asia/Tehran")
    assert result.value is None
    assert result.needs_confirmation
    assert "نامعتبر" in result.clarification


def test_spoken_relative_durations_use_current_clock():
    now = datetime(2026, 9, 15, 15, 30, tzinfo=TEHRAN)
    minutes = resolve_persian_datetime("پنج دقیقه دیگر یادآوری کن", now, "Asia/Tehran")
    hours = resolve_persian_datetime("دو ساعت بعد یادآوری کن", now, "Asia/Tehran")
    assert minutes.value.astimezone(TEHRAN).hour == 15
    assert minutes.value.astimezone(TEHRAN).minute == 35
    assert hours.value.astimezone(TEHRAN).hour == 17
    assert hours.value.astimezone(TEHRAN).minute == 30


def test_day_with_bare_clock_and_period_is_precise():
    now = datetime(2026, 9, 15, 15, 30, tzinfo=TEHRAN)
    result = resolve_persian_datetime("فردا ۹ شب زنگ بزنم", now, "Asia/Tehran")
    assert result.value.astimezone(TEHRAN).hour == 21


def test_twelve_at_night_requires_clarification():
    now = datetime(2026, 9, 15, 15, 30, tzinfo=TEHRAN)
    result = resolve_persian_datetime("فردا ساعت ۱۲ شب", now, "Asia/Tehran")
    assert result.value is None
    assert result.needs_confirmation
