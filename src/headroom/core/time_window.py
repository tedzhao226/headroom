from datetime import datetime, time, timedelta, timezone


def is_within_window(now: time, start: time, end: time) -> bool:
    """Return True when `now` falls inside [start, end), supporting midnight crossing."""
    if start <= end:
        return start <= now < end
    return now >= start or now < end


def next_window_start_utc(start: time, now: datetime | None = None) -> datetime:
    """Return the next UTC datetime whose time component equals `start`.

    If `now` is already at or past today's `start`, returns tomorrow's.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    today_start = datetime.combine(now.date(), start, tzinfo=timezone.utc)
    if now < today_start:
        return today_start
    return today_start + timedelta(days=1)
