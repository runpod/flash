"""Tests for CLI formatting utilities."""

from runpod_flash.cli.utils.formatting import format_datetime


class TestFormatDatetime:
    def test_iso_utc_z_suffix(self):
        result = format_datetime("2025-06-15T14:30:00Z")
        assert "Jun" in result
        assert "2025" in result
        assert "AM" in result or "PM" in result

    def test_iso_with_offset(self):
        result = format_datetime("2025-06-15T14:30:00+00:00")
        assert "Jun" in result
        assert "2025" in result

    def test_none_returns_dash(self):
        assert format_datetime(None) == "-"

    def test_empty_returns_dash(self):
        assert format_datetime("") == "-"

    def test_unparseable_returns_original(self):
        assert format_datetime("not-a-date") == "not-a-date"

    def test_includes_day_of_week(self):
        result = format_datetime("2025-06-15T14:30:00Z")
        # june 15 2025 is a sunday
        assert result.startswith("Sun,")

    def test_includes_timezone(self):
        result = format_datetime("2025-06-15T14:30:00Z")
        # should have some tz abbreviation at the end
        parts = result.split()
        assert len(parts) >= 5
