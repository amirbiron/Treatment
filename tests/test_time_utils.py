from datetime import datetime, time as dt_time

import pytz

from utils.time import get_timezone, ensure_aware, build_local_datetime_for_time, DEFAULT_TZ_NAME


def test_default_timezone_is_jerusalem():
    tz = get_timezone(None)
    assert tz.zone == DEFAULT_TZ_NAME


def test_ensure_aware_localizes_naive_to_given_tz():
    naive = datetime(2025, 3, 28, 21, 0, 0)
    aware = ensure_aware(naive, "Asia/Jerusalem")
    assert aware.tzinfo is not None
    assert aware.tzinfo.utcoffset(aware) is not None
    assert aware.astimezone(pytz.timezone("Asia/Jerusalem")).hour == 21


def test_build_local_datetime_for_time_today_dst_safe():
    # Time around DST is tricky; we just assert tz-awareness and hour match
    dt = build_local_datetime_for_time(dt_time(21, 0), "Asia/Jerusalem")
    assert dt.tzinfo is not None
    assert dt.hour == 21

