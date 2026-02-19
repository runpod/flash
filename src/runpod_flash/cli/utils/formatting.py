"""CLI output formatting helpers."""

from datetime import datetime, timezone


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
        return local_dt.strftime(f"%a, %b %-d %Y %-I:%M %p {tz_name}")
    except (ValueError, TypeError):
        return value
