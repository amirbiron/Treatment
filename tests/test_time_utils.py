from datetime import datetime

import pytz

from utils.time import DEFAULT_TZ_NAME, get_timezone, get_user_timezone_name, ensure_aware, now_in_timezone


class DummyUser:
    def __init__(self, timezone=None):
        self.timezone = timezone


def test_default_timezone_name():
    assert DEFAULT_TZ_NAME == "Asia/Jerusalem"


def test_get_timezone_valid_and_fallback():
    tz = get_timezone("Asia/Jerusalem")
    assert isinstance(tz, pytz.BaseTzInfo)
    # Fallback to default on invalid
    tz2 = get_timezone("Not/AZone")
    assert tz2.zone == DEFAULT_TZ_NAME


def test_get_user_timezone_name():
    assert get_user_timezone_name(DummyUser("Europe/London")) == "Europe/London"
    assert get_user_timezone_name(DummyUser(None)) == DEFAULT_TZ_NAME
    assert get_user_timezone_name(DummyUser("")) == DEFAULT_TZ_NAME


def test_ensure_aware_localize_and_convert_summer_winter_offsets():
    tz_name = "Asia/Jerusalem"
    tz = get_timezone(tz_name)

    # Summer date: expect UTC+3
    naive_summer = datetime(2024, 7, 1, 12, 0, 0)
    aware_summer = ensure_aware(naive_summer, tz)
    assert aware_summer.tzinfo is not None
    assert aware_summer.utcoffset().total_seconds() in (3 * 3600,)  # +03:00

    # Winter date: expect UTC+2
    naive_winter = datetime(2024, 12, 1, 12, 0, 0)
    aware_winter = ensure_aware(naive_winter, tz)
    assert aware_winter.tzinfo is not None
    assert aware_winter.utcoffset().total_seconds() in (2 * 3600,)  # +02:00

    # Convert aware from London to Israel
    london = get_timezone("Europe/London")
    aware_ldn = london.localize(datetime(2024, 7, 1, 10, 0, 0))
    converted = ensure_aware(aware_ldn, tz)
    assert converted.tzinfo.zone == tz_name


def test_now_in_timezone_is_aware():
    now_il = now_in_timezone("Asia/Jerusalem")
    assert now_il.tzinfo is not None
    assert now_il.utcoffset() is not None

