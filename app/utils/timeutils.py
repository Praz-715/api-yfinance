"""Time-zone aware helpers centred on the Jakarta (IDX) trading calendar."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

JAKARTA_TZ = ZoneInfo("Asia/Jakarta")
UTC = timezone.utc

# IDX regular trading session (local Jakarta time), used for "market open" hints.
_SESSION_OPEN = time(9, 0)
_SESSION_CLOSE = time(16, 0)


def now_utc() -> datetime:
    """Current instant as a timezone-aware UTC datetime."""
    return datetime.now(tz=UTC)


def now_jakarta() -> datetime:
    """Current instant in Jakarta local time."""
    return datetime.now(tz=JAKARTA_TZ)


def to_epoch_seconds(dt: datetime) -> int:
    """Convert an aware datetime to integer Unix epoch seconds (UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.astimezone(UTC).timestamp())


def epoch_to_jakarta(epoch_seconds: int | float) -> datetime:
    """Convert Unix epoch seconds to an aware Jakarta datetime."""
    return datetime.fromtimestamp(float(epoch_seconds), tz=UTC).astimezone(JAKARTA_TZ)


def date_to_epoch(value: date, *, end_of_day: bool = False) -> int:
    """Convert a calendar date (interpreted in Jakarta time) to epoch seconds."""
    t = _SESSION_CLOSE if end_of_day else time(0, 0)
    dt = datetime.combine(value, t, tzinfo=JAKARTA_TZ)
    return to_epoch_seconds(dt)


def is_market_open(reference: datetime | None = None) -> bool:
    """Best-effort check whether the IDX regular session is open.

    Considers Jakarta weekday and session hours. Exchange holidays are not
    encoded here; callers should treat the result as an indicative hint and rely
    on the upstream ``regular_market_time`` for authoritative freshness.
    """
    local = (reference or now_jakarta()).astimezone(JAKARTA_TZ)
    if local.weekday() >= 5:  # Saturday/Sunday
        return False
    return _SESSION_OPEN <= local.time() <= _SESSION_CLOSE
