from datetime import datetime
import os
import importlib.util
import pytz

# Dynamically import the time utilities module without importing the utils package
_TIME_PATH = os.path.join(os.path.dirname(__file__), os.pardir, "utils", "time.py")
_TIME_PATH = os.path.abspath(_TIME_PATH)
_spec = importlib.util.spec_from_file_location("time_utils", _TIME_PATH)
time_utils = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(time_utils)  # type: ignore[arg-type]


def test_get_timezone_fallback_and_valid():
    tz = time_utils.get_timezone(None)
    assert tz.zone == time_utils.get_default_timezone_name()
    tz2 = time_utils.get_timezone("Asia/Jerusalem")
    assert tz2.zone == "Asia/Jerusalem"
    tz3 = time_utils.get_timezone(" Invalid/Zone  ")
    assert tz3.zone == time_utils.get_default_timezone_name()


def test_ensure_aware_localize_and_convert():
    tz = time_utils.get_timezone("Asia/Jerusalem")
    # Naive datetime becomes aware localized
    naive = datetime(2024, 1, 15, 21, 0, 0)
    aware = time_utils.ensure_aware(naive, tz)
    assert aware.tzinfo is not None
    assert aware.utcoffset() is not None
    # Converting from another tz
    utc = pytz.timezone("UTC")
    aware_utc = time_utils.ensure_aware(datetime(2024, 1, 15, 19, 0, 0, tzinfo=utc), tz)
    assert aware_utc.tzinfo is not None
    # 19:00 UTC should be 21:00 Israel in winter
    assert aware_utc.hour == 21


def test_now_in_timezone_awareness():
    dt = time_utils.now_in_timezone("Asia/Jerusalem")
    assert dt.tzinfo is not None
    assert dt.tzinfo.zone == "Asia/Jerusalem"


def test_dst_offsets_asia_jerusalem():
    tz = pytz.timezone("Asia/Jerusalem")
    winter = tz.localize(datetime(2024, 1, 15, 12, 0, 0))
    summer = tz.localize(datetime(2024, 7, 1, 12, 0, 0))
    # Winter is UTC+2, Summer is UTC+3
    assert int(winter.utcoffset().total_seconds() // 3600) == 2
    assert int(summer.utcoffset().total_seconds() // 3600) == 3

