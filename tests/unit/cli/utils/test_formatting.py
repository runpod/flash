"""Tests for CLI formatting utilities."""

from runpod_flash.cli.utils.formatting import format_datetime, state_dot


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
        # use a fixed-offset timestamp so the weekday is deterministic
        result = format_datetime("2025-06-15T00:00:00+00:00")
        # output should start with a 3-letter weekday abbreviation
        assert result[:3].isalpha() and result[3] == ","

    def test_includes_timezone(self):
        result = format_datetime("2025-06-15T14:30:00Z")
        # should have some tz abbreviation at the end
        parts = result.split()
        assert len(parts) >= 5

    def test_no_leading_zeros(self):
        # day "5" should not be zero-padded to "05"
        result = format_datetime("2025-01-05T12:00:00+00:00")
        assert " 5 " in result or " 5," in result


class TestStateDot:
    def test_healthy(self):
        assert "[green]●[/green]" in state_dot("HEALTHY")

    def test_building(self):
        assert "[cyan]●[/cyan]" in state_dot("BUILDING")

    def test_error(self):
        assert "[red]●[/red]" in state_dot("ERROR")

    def test_unknown_defaults_yellow(self):
        assert "[yellow]●[/yellow]" in state_dot("WHATEVER")
