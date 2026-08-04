from datetime import time

import pytest

from utils.schedule import (
    INTERVAL_HOURS_CHOICES,
    describe_interval,
    expand_interval_times,
    format_times,
)


def test_every_choice_divides_a_day_exactly():
    """A non-divisor would leave a ragged gap at midnight, so none may be offered."""
    for hours in INTERVAL_HOURS_CHOICES:
        assert 24 % hours == 0, f"{hours} does not divide 24"


@pytest.mark.parametrize(
    "start,hours,expected",
    [
        (time(7, 0), 8, ["07:00", "15:00", "23:00"]),
        (time(8, 0), 12, ["08:00", "20:00"]),
        (time(6, 30), 6, ["00:30", "06:30", "12:30", "18:30"]),
        (time(0, 0), 4, ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"]),
        (time(9, 15), 2, ["01:15", "03:15", "05:15", "07:15", "09:15", "11:15",
                          "13:15", "15:15", "17:15", "19:15", "21:15", "23:15"]),
    ],
)
def test_expands_to_the_expected_times(start, hours, expected):
    assert [t.strftime("%H:%M") for t in expand_interval_times(start, hours)] == expected


@pytest.mark.parametrize("hours", INTERVAL_HOURS_CHOICES)
def test_dose_count_matches_the_interval(hours):
    times = expand_interval_times(time(7, 45), hours)
    assert len(times) == 24 // hours
    assert len(set(times)) == len(times), "no duplicate reminder times"


@pytest.mark.parametrize("hours", INTERVAL_HOURS_CHOICES)
def test_gaps_are_uniform_and_wrap_across_midnight(hours):
    """The gap from the last dose of one day to the first of the next must match too."""
    times = expand_interval_times(time(22, 20), hours)
    minutes = [t.hour * 60 + t.minute for t in times]
    gaps = [(minutes[(i + 1) % len(minutes)] - minutes[i]) % (24 * 60) for i in range(len(minutes))]
    assert set(gaps) == {hours * 60}


def test_result_is_sorted():
    times = expand_interval_times(time(23, 0), 6)
    assert times == sorted(times)
    assert [t.strftime("%H:%M") for t in times] == ["05:00", "11:00", "17:00", "23:00"]


def test_rejects_intervals_that_cannot_repeat_daily():
    for hours in (5, 7, 9, 13, 24, 0, -4):
        with pytest.raises(ValueError):
            expand_interval_times(time(8, 0), hours)


def test_format_and_describe():
    assert format_times([time(15, 0), time(7, 0)]) == "07:00, 15:00"
    assert describe_interval(time(7, 0), 8) == "כל 8 שעות (החל מ-07:00): 07:00, 15:00, 23:00"


# --- callback parsing -------------------------------------------------------

from utils.schedule import (  # noqa: E402
    BACK,
    CUSTOM,
    INVALID,
    MENU,
    PICK,
    START,
    parse_interval_callback,
)


def test_non_interval_callbacks_are_not_claimed():
    """The plain time buttons must fall through to the existing handler."""
    for data in ("time_08_00", "time_custom", "time_cancel", "medicine_view_3", "cancel"):
        assert parse_interval_callback(data) is None, data


def test_menu_and_back_are_distinguished():
    assert parse_interval_callback("time_interval").kind == MENU
    assert parse_interval_callback("time_ivl_back").kind == BACK


@pytest.mark.parametrize("hours", INTERVAL_HOURS_CHOICES)
def test_pick_and_custom_carry_the_interval(hours):
    picked = parse_interval_callback(f"time_ivl_{hours}")
    assert (picked.kind, picked.interval_hours) == (PICK, hours)

    custom = parse_interval_callback(f"time_ivlcustom_{hours}")
    assert (custom.kind, custom.interval_hours) == (CUSTOM, hours)


def test_start_carries_both_interval_and_time():
    parsed = parse_interval_callback("time_ivlstart_8_07_30")
    assert parsed.kind == START
    assert parsed.interval_hours == 8
    assert parsed.start_time == time(7, 30)


def test_start_is_not_confused_with_pick():
    """`time_ivlstart_...` also starts with `time_ivl`, so prefix order matters."""
    assert parse_interval_callback("time_ivlstart_12_09_00").kind == START
    assert parse_interval_callback("time_ivl_12").kind == PICK


@pytest.mark.parametrize(
    "data",
    [
        "time_ivl_5",  # not a divisor of 24
        "time_ivl_0",
        "time_ivl_abc",
        "time_ivlcustom_7",
        "time_ivlcustom_",
        "time_ivlstart_5_07_00",  # unsupported interval
        "time_ivlstart_8_25_00",  # impossible hour
        "time_ivlstart_8_07_61",  # impossible minute
        "time_ivlstart_8_07",  # missing minute
        "time_ivlstart_8_07_00_00",  # extra field
    ],
)
def test_unusable_callbacks_are_flagged_not_crashed(data):
    """Stale or crafted buttons must be reported, never reach expand_interval_times."""
    assert parse_interval_callback(data).kind == INVALID


def test_is_supported_interval():
    from utils.schedule import is_supported_interval

    assert all(is_supported_interval(h) for h in INTERVAL_HOURS_CHOICES)
    assert not is_supported_interval(5)
    assert not is_supported_interval(None)
    assert not is_supported_interval("8")
