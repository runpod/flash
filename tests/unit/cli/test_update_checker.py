"""Unit tests for passive background update checker."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from runpod_flash.cli import update_checker
from runpod_flash.cli.update_checker import (
    _get_cache_path,
    _is_cache_fresh,
    _print_update_notice,
    _read_cache,
    _run_check,
    _write_cache,
    start_background_check,
    CHECK_INTERVAL_HOURS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_module_state() -> None:
    """Reset module-level state between tests."""
    update_checker._newer_version = None
    update_checker._check_done = threading.Event()


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset module state before and after each test."""
    _reset_module_state()
    yield
    _reset_module_state()


# ---------------------------------------------------------------------------
# _get_cache_path
# ---------------------------------------------------------------------------


class TestGetCachePath:
    def test_default_path(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        path = _get_cache_path()
        assert path == Path.home() / ".config" / "runpod" / "update_check.json"

    def test_custom_xdg(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        path = _get_cache_path()
        assert path == tmp_path / "runpod" / "update_check.json"


# ---------------------------------------------------------------------------
# _read_cache
# ---------------------------------------------------------------------------


class TestReadCache:
    def test_missing_file(self, tmp_path: Path):
        result = _read_cache(tmp_path / "nonexistent.json")
        assert result is None

    def test_valid_json(self, tmp_path: Path):
        cache_file = tmp_path / "cache.json"
        data = {
            "last_checked_utc": "2026-01-01T00:00:00+00:00",
            "latest_version": "2.0.0",
        }
        cache_file.write_text(json.dumps(data))

        result = _read_cache(cache_file)
        assert result == data

    def test_malformed_json(self, tmp_path: Path):
        cache_file = tmp_path / "cache.json"
        cache_file.write_text("not valid json {{{")

        result = _read_cache(cache_file)
        assert result is None


# ---------------------------------------------------------------------------
# _write_cache
# ---------------------------------------------------------------------------


class TestWriteCache:
    def test_writes_correct_json(self, tmp_path: Path):
        cache_file = tmp_path / "runpod" / "update_check.json"

        _write_cache(cache_file, "1.6.0")

        data = json.loads(cache_file.read_text())
        assert data["latest_version"] == "1.6.0"
        assert "last_checked_utc" in data
        # Verify timestamp is parseable and recent
        ts = datetime.fromisoformat(data["last_checked_utc"])
        assert (datetime.now(timezone.utc) - ts).total_seconds() < 10

    def test_creates_parent_dirs(self, tmp_path: Path):
        cache_file = tmp_path / "a" / "b" / "c" / "cache.json"
        _write_cache(cache_file, "1.0.0")
        assert cache_file.exists()

    def test_silent_on_oserror(self):
        """Writing to an unwritable path does not raise."""
        _write_cache(Path("/proc/nonexistent/cache.json"), "1.0.0")


# ---------------------------------------------------------------------------
# _is_cache_fresh
# ---------------------------------------------------------------------------


class TestIsCacheFresh:
    def test_fresh_cache(self):
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        assert _is_cache_fresh({"last_checked_utc": one_hour_ago}) is True

    def test_stale_cache(self):
        old = (
            datetime.now(timezone.utc) - timedelta(hours=CHECK_INTERVAL_HOURS + 1)
        ).isoformat()
        assert _is_cache_fresh({"last_checked_utc": old}) is False

    def test_missing_key(self):
        assert _is_cache_fresh({}) is False

    def test_invalid_timestamp(self):
        assert _is_cache_fresh({"last_checked_utc": "not-a-date"}) is False


# ---------------------------------------------------------------------------
# _run_check
# ---------------------------------------------------------------------------


class TestRunCheck:
    @patch("runpod_flash.cli.update_checker._get_current_version", return_value="1.5.0")
    @patch(
        "runpod_flash.cli.update_checker._fetch_pypi_metadata",
        return_value=("1.6.0", {"1.5.0", "1.6.0"}),
    )
    @patch("runpod_flash.cli.update_checker._get_cache_path")
    def test_fetches_when_stale(
        self,
        mock_cache_path: MagicMock,
        mock_fetch: MagicMock,
        mock_version: MagicMock,
        tmp_path: Path,
    ):
        cache_file = tmp_path / "update_check.json"
        mock_cache_path.return_value = cache_file

        _run_check()

        mock_fetch.assert_called_once()
        assert update_checker._check_done.is_set()
        assert update_checker._newer_version == "1.6.0"
        # Cache should be written
        assert cache_file.exists()

    @patch("runpod_flash.cli.update_checker._get_current_version", return_value="1.5.0")
    @patch("runpod_flash.cli.update_checker._fetch_pypi_metadata")
    @patch("runpod_flash.cli.update_checker._get_cache_path")
    def test_uses_cache_when_fresh(
        self,
        mock_cache_path: MagicMock,
        mock_fetch: MagicMock,
        mock_version: MagicMock,
        tmp_path: Path,
    ):
        cache_file = tmp_path / "update_check.json"
        fresh_data = {
            "last_checked_utc": datetime.now(timezone.utc).isoformat(),
            "latest_version": "1.6.0",
        }
        cache_file.write_text(json.dumps(fresh_data))
        mock_cache_path.return_value = cache_file

        _run_check()

        mock_fetch.assert_not_called()
        assert update_checker._newer_version == "1.6.0"

    @patch("runpod_flash.cli.update_checker._get_current_version", return_value="1.6.0")
    @patch(
        "runpod_flash.cli.update_checker._fetch_pypi_metadata",
        return_value=("1.6.0", {"1.6.0"}),
    )
    @patch("runpod_flash.cli.update_checker._get_cache_path")
    def test_no_update_when_current(
        self,
        mock_cache_path: MagicMock,
        mock_fetch: MagicMock,
        mock_version: MagicMock,
        tmp_path: Path,
    ):
        mock_cache_path.return_value = tmp_path / "update_check.json"

        _run_check()

        assert update_checker._newer_version is None
        assert update_checker._check_done.is_set()

    @patch("runpod_flash.cli.update_checker._get_current_version", return_value="1.5.0")
    @patch(
        "runpod_flash.cli.update_checker._fetch_pypi_metadata",
        side_effect=ConnectionError("network down"),
    )
    @patch("runpod_flash.cli.update_checker._get_cache_path")
    def test_sets_done_on_network_failure(
        self,
        mock_cache_path: MagicMock,
        mock_fetch: MagicMock,
        mock_version: MagicMock,
        tmp_path: Path,
    ):
        mock_cache_path.return_value = tmp_path / "update_check.json"

        _run_check()

        assert update_checker._check_done.is_set()
        assert update_checker._newer_version is None

    @patch(
        "runpod_flash.cli.update_checker._get_current_version", return_value="unknown"
    )
    def test_skips_when_version_unknown(self, mock_version: MagicMock):
        _run_check()

        assert update_checker._check_done.is_set()
        assert update_checker._newer_version is None


# ---------------------------------------------------------------------------
# _print_update_notice
# ---------------------------------------------------------------------------


class TestPrintUpdateNotice:
    def test_prints_when_newer_available(self, capsys: pytest.CaptureFixture[str]):
        update_checker._newer_version = "2.0.0"
        update_checker._check_done.set()

        _print_update_notice()

        captured = capsys.readouterr()
        assert "2.0.0" in captured.err
        assert "flash update" in captured.err

    def test_silent_when_no_update(self, capsys: pytest.CaptureFixture[str]):
        update_checker._newer_version = None
        update_checker._check_done.set()

        _print_update_notice()

        captured = capsys.readouterr()
        assert captured.err == ""

    def test_silent_when_thread_not_done(self, capsys: pytest.CaptureFixture[str]):
        update_checker._newer_version = "2.0.0"
        # _check_done is NOT set

        _print_update_notice()

        captured = capsys.readouterr()
        assert captured.err == ""


# ---------------------------------------------------------------------------
# start_background_check
# ---------------------------------------------------------------------------


class TestStartBackgroundCheck:
    @patch("runpod_flash.cli.update_checker.atexit.register")
    @patch("runpod_flash.cli.update_checker.threading.Thread")
    def test_spawns_daemon_thread(
        self,
        mock_thread_cls: MagicMock,
        mock_register: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.delenv("FLASH_NO_UPDATE_CHECK", raising=False)
        monkeypatch.delenv("CI", raising=False)

        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        start_background_check()

        mock_thread_cls.assert_called_once_with(target=_run_check, daemon=True)
        mock_thread.start.assert_called_once()
        mock_register.assert_called_once_with(_print_update_notice)

    @patch("runpod_flash.cli.update_checker.atexit.register")
    @patch("runpod_flash.cli.update_checker.threading.Thread")
    def test_skips_on_flash_no_update_check(
        self,
        mock_thread_cls: MagicMock,
        mock_register: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("FLASH_NO_UPDATE_CHECK", "1")
        monkeypatch.delenv("CI", raising=False)

        start_background_check()

        mock_thread_cls.assert_not_called()
        mock_register.assert_not_called()

    @patch("runpod_flash.cli.update_checker.atexit.register")
    @patch("runpod_flash.cli.update_checker.threading.Thread")
    def test_skips_on_ci(
        self,
        mock_thread_cls: MagicMock,
        mock_register: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.delenv("FLASH_NO_UPDATE_CHECK", raising=False)
        monkeypatch.setenv("CI", "true")

        start_background_check()

        mock_thread_cls.assert_not_called()
        mock_register.assert_not_called()
