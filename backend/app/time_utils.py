from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple

import pytz


def get_timezone(tz_name: Optional[str]) -> pytz.BaseTzInfo:
    if not tz_name:
        return pytz.UTC
    try:
        return pytz.timezone(tz_name)
    except Exception:
        return pytz.UTC


def safe_localize(tz: pytz.BaseTzInfo, naive_dt: datetime) -> datetime:
    """Localize a naive datetime in a pytz timezone, handling DST edge cases."""
    try:
        return tz.localize(naive_dt)
    except Exception:
        # Best-effort fallback: treat as DST time if ambiguous/non-existent.
        try:
            return tz.localize(naive_dt, is_dst=True)
        except Exception:
            return naive_dt.replace(tzinfo=timezone.utc)


def to_utc(dt: Optional[datetime], tz_name: Optional[str]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        tz = get_timezone(tz_name)
        dt = safe_localize(tz, dt)
    return dt.astimezone(timezone.utc)


def parse_hhmm(value: Optional[str], default: str = "15:00") -> Tuple[int, int]:
    raw = (value or default or "00:00").strip()
    parts = raw.split(":")
    try:
        hour = int(parts[0])
    except Exception:
        hour = int(default.split(":")[0])
    try:
        minute = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        minute = int(default.split(":")[1]) if ":" in default else 0
    hour = max(0, min(23, hour))
    minute = max(0, min(59, minute))
    return hour, minute


def minutes_since_midnight(dt: datetime) -> int:
    return int(dt.hour) * 60 + int(dt.minute)


def is_within_daily_window(current_minutes: int, start_minutes: int, end_minutes: int) -> bool:
    # Treat equal start/end as "always allowed".
    if start_minutes == end_minutes:
        return True
    if start_minutes < end_minutes:
        return start_minutes <= current_minutes < end_minutes
    # Window crosses midnight (e.g. 22:00 -> 02:00)
    return current_minutes >= start_minutes or current_minutes < end_minutes

