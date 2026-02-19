"""CLI output formatting helpers."""

from datetime import datetime

STATE_STYLE = {"HEALTHY": "green", "BUILDING": "cyan", "ERROR": "red"}


def state_dot(state: str) -> str:
    """Colored ● indicator for a resource/environment state."""
    color = STATE_STYLE.get(state, "yellow")
    return f"[{color}]●[/{color}]"


def format_datetime(value: str | None) -> str:
    """Format an ISO 8601 datetime string into a human-readable local time.

    Returns a string like "Thu, Feb 19 2026 1:33 PM PST".
    Returns "-" for None/empty/unparseable values.
    """
    if not value:
        return "-"

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        local_dt = dt.astimezone()
        tz_name = local_dt.strftime("%Z")
        # strftime with manual zero-strip for cross-platform compat
        # (%-d and %-I are glibc extensions, not available on windows)
        day = local_dt.day
        hour = int(local_dt.strftime("%I"))
        return local_dt.strftime(f"%a, %b {day} %Y {hour}:%M %p {tz_name}")
    except (ValueError, TypeError):
        return value
