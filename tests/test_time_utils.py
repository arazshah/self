from datetime import datetime
from zoneinfo import ZoneInfo

from app.time_utils import resolve_persian_datetime

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
