"""Tests for the runpod-flash package deprecation (sunset) notice."""

import warnings

import pytest
from typer.testing import CliRunner

import runpod_flash
from runpod_flash import sunset
from runpod_flash.cli.main import app

_WORKER_ENV_VARS = ("RUNPOD_ENDPOINT_ID", "RUNPOD_POD_ID")
_SILENCE_ENV_VAR = "RUNPOD_FLASH_SILENCE_DEPRECATION"


@pytest.fixture(autouse=True)
def fresh_notice_state(monkeypatch):
    """Each test starts as a fresh process: notice not yet shown, not on a worker."""
    monkeypatch.setattr(sunset, "_notice_shown", False)
    for var in (*_WORKER_ENV_VARS, _SILENCE_ENV_VAR):
        monkeypatch.delenv(var, raising=False)


def _future_warnings(caught: list[warnings.WarningMessage]) -> list[str]:
    return [str(w.message) for w in caught if issubclass(w.category, FutureWarning)]


class TestSunsetMessage:
    def test_message_states_date_no_updates_and_migration_guide(self):
        assert "October 29, 2026" in sunset.SUNSET_MESSAGE
        assert "no fixes or updates" in sunset.SUNSET_MESSAGE
        assert "Runpod Python SDK 2.0" in sunset.SUNSET_MESSAGE
        assert sunset.MIGRATION_GUIDE_URL in sunset.SUNSET_MESSAGE


class TestImportWarning:
    def test_public_api_access_emits_future_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _ = runpod_flash.Endpoint

        assert _future_warnings(caught) == [sunset.SUNSET_MESSAGE]

    def test_warning_points_at_caller(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _ = runpod_flash.Endpoint

        future = [w for w in caught if issubclass(w.category, FutureWarning)]
        assert future[0].filename == __file__

    def test_warning_emitted_once_per_process(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _ = runpod_flash.Endpoint
            _ = runpod_flash.GpuType
            _ = runpod_flash.Endpoint

        assert len(_future_warnings(caught)) == 1

    def test_non_public_attribute_lookup_does_not_warn(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert not hasattr(runpod_flash, "__wrapped__")

        assert _future_warnings(caught) == []

    @pytest.mark.parametrize("env_var", _WORKER_ENV_VARS)
    def test_no_warning_on_deployed_worker(self, monkeypatch, env_var):
        monkeypatch.setenv(env_var, "abc123")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _ = runpod_flash.Endpoint

        assert _future_warnings(caught) == []


class TestCliNotice:
    def test_cli_prints_notice_to_stderr(self):
        result = CliRunner().invoke(app, ["--version"])

        assert result.exit_code == 0
        assert "October 29, 2026" in result.stderr
        assert sunset.MIGRATION_GUIDE_URL in result.stderr

    def test_cli_notice_keeps_stdout_clean(self):
        result = CliRunner().invoke(app, ["--version"])

        assert "October 29, 2026" not in result.stdout
        assert "Runpod Flash CLI v" in result.stdout

    def test_cli_notice_suppresses_later_import_warning(self):
        CliRunner().invoke(app, ["--version"])

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _ = runpod_flash.Endpoint

        assert _future_warnings(caught) == []


class TestSilenceEscapeHatch:
    @pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
    def test_silences_import_warning(self, monkeypatch, value):
        monkeypatch.setenv(_SILENCE_ENV_VAR, value)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _ = runpod_flash.Endpoint

        assert _future_warnings(caught) == []

    def test_silences_cli_notice(self, monkeypatch):
        monkeypatch.setenv(_SILENCE_ENV_VAR, "1")

        result = CliRunner().invoke(app, ["--version"])

        assert result.exit_code == 0
        assert result.stderr == ""

    @pytest.mark.parametrize("value", ["", "0", "false", "no"])
    def test_falsy_values_do_not_silence(self, monkeypatch, value):
        monkeypatch.setenv(_SILENCE_ENV_VAR, value)

        result = CliRunner().invoke(app, ["--version"])

        assert "October 29, 2026" in result.stderr
