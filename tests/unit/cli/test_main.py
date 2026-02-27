"""Unit tests for flash CLI main entry point (--version, callback behavior)."""

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from runpod_flash.cli.main import app, get_version


@pytest.fixture
def runner():
    return CliRunner()


class TestGetVersion:
    """Tests for get_version() helper."""

    def test_returns_installed_version(self):
        """get_version returns version string from package metadata."""
        with patch("runpod_flash.cli.main.metadata") as mock_metadata:
            mock_metadata.version.return_value = "1.4.1"
            assert get_version() == "1.4.1"
            mock_metadata.version.assert_called_once_with("runpod-flash")

    def test_returns_unknown_when_package_not_found(self):
        """get_version returns 'unknown' when package is not installed."""
        from importlib import metadata

        with patch("runpod_flash.cli.main.metadata") as mock_metadata:
            mock_metadata.PackageNotFoundError = metadata.PackageNotFoundError
            mock_metadata.version.side_effect = metadata.PackageNotFoundError(
                "runpod-flash"
            )
            assert get_version() == "unknown"


class TestVersionFlag:
    """Tests for flash --version / flash -v."""

    def test_version_long_flag(self, runner):
        """flash --version displays version and exits."""
        with patch("runpod_flash.cli.main.get_version", return_value="1.4.1"):
            result = runner.invoke(app, ["--version"])

        assert result.exit_code == 0
        assert "Runpod Flash CLI v1.4.1" in result.stdout

    def test_version_short_flag(self, runner):
        """flash -v displays version and exits."""
        with patch("runpod_flash.cli.main.get_version", return_value="1.4.1"):
            result = runner.invoke(app, ["-v"])

        assert result.exit_code == 0
        assert "Runpod Flash CLI v1.4.1" in result.stdout

    def test_version_unknown(self, runner):
        """flash --version shows 'unknown' when version not available."""
        with patch("runpod_flash.cli.main.get_version", return_value="unknown"):
            result = runner.invoke(app, ["--version"])

        assert result.exit_code == 0
        assert "Runpod Flash CLI vunknown" in result.stdout

    def test_no_args_shows_help(self, runner):
        """flash (no args) shows help/usage (no_args_is_help=True)."""
        result = runner.invoke(app, [])

        # Typer with no_args_is_help=True exits with code 0 and shows help,
        # or exits with 2 showing usage. Either way, output mentions flash.
        assert "flash" in result.stdout.lower() or "usage" in result.stdout.lower()
