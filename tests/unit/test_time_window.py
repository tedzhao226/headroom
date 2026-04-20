from datetime import datetime, time, timezone

from headroom.core.time_window import is_within_window, next_window_start_utc


def test_is_within_window_same_day() -> None:
    assert is_within_window(time(hour=3), time(hour=2), time(hour=6))
    assert not is_within_window(time(hour=7), time(hour=2), time(hour=6))


def test_is_within_window_start_inclusive_end_exclusive() -> None:
    assert is_within_window(time(hour=2), time(hour=2), time(hour=6))
    assert not is_within_window(time(hour=6), time(hour=2), time(hour=6))


def test_is_within_window_crosses_midnight() -> None:
    start, end = time(hour=22), time(hour=6)
    assert is_within_window(time(hour=23), start, end)
    assert is_within_window(time(hour=5), start, end)
    assert not is_within_window(time(hour=12), start, end)


def test_next_window_start_before_today_returns_today() -> None:
    now = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)
    result = next_window_start_utc(time(hour=22), now=now)
    assert result == datetime(2026, 4, 17, 22, 0, 0, tzinfo=timezone.utc)


def test_next_window_start_after_today_returns_tomorrow() -> None:
    now = datetime(2026, 4, 17, 23, 0, 0, tzinfo=timezone.utc)
    result = next_window_start_utc(time(hour=22), now=now)
    assert result == datetime(2026, 4, 18, 22, 0, 0, tzinfo=timezone.utc)
