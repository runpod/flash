"""Unit tests for flash CLI main entry point (--version, callback behavior)."""

from unittest.mock import patch, MagicMock

import typer
import pytest
from typer.testing import CliRunner

from runpod_flash.cli.main import app, main, get_version, _UPDATE_CHECK_EXCLUDED


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


class TestUpdateCheckExclusionSet:
    """Verify the exclusion set contains the expected commands."""

    def test_run_excluded(self):
        assert "run" in _UPDATE_CHECK_EXCLUDED

    def test_update_excluded(self):
        assert "update" in _UPDATE_CHECK_EXCLUDED

    def test_build_not_excluded(self):
        assert "build" not in _UPDATE_CHECK_EXCLUDED

    def test_deploy_not_excluded(self):
        assert "deploy" not in _UPDATE_CHECK_EXCLUDED


class TestCallbackWiring:
    """Verify main callback triggers start_background_check for the right subcommands.

    Tests call the main() callback directly with a mock typer.Context to avoid
    executing actual subcommands (which may start servers or hit the network).
    """

    def _make_ctx(self, subcommand: str | None) -> MagicMock:
        ctx = MagicMock(spec=typer.Context)
        ctx.invoked_subcommand = subcommand
        return ctx

    @pytest.mark.parametrize(
        "subcommand",
        ["build", "deploy", "init", "login", "env", "undeploy"],
    )
    def test_non_excluded_subcommand_triggers_check(self, subcommand: str):
        with patch("runpod_flash.cli.main.start_background_check") as mock_check:
            main(ctx=self._make_ctx(subcommand), version=False)
            mock_check.assert_called_once()

    @pytest.mark.parametrize("subcommand", ["run", "update"])
    def test_excluded_subcommand_does_not_trigger_check(self, subcommand: str):
        with patch("runpod_flash.cli.main.start_background_check") as mock_check:
            main(ctx=self._make_ctx(subcommand), version=False)
            mock_check.assert_not_called()

    def test_no_subcommand_does_not_trigger_check(self):
        with patch("runpod_flash.cli.main.start_background_check") as mock_check:
            main(ctx=self._make_ctx(None), version=False)
            mock_check.assert_not_called()

    def test_version_flag_exits_before_check(self):
        with patch("runpod_flash.cli.main.start_background_check") as mock_check:
            with pytest.raises(typer.Exit):
                main(ctx=self._make_ctx("build"), version=True)
            mock_check.assert_not_called()
