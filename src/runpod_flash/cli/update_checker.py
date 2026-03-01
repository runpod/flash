"""Passive background update check for the flash CLI.

Spawns a daemon thread that checks PyPI (at most once per 24h, cached to disk).
An atexit handler prints a one-line notice to stderr if a newer version exists.
The thread never blocks the command -- if the network is slow, the notice is
silently skipped.
"""

from __future__ import annotations

import atexit
import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from .commands.update import _fetch_pypi_metadata, _get_current_version, _parse_version

CACHE_FILENAME = "update_check.json"
CHECK_INTERVAL_HOURS = 24

_newer_version: str | None = None
_result_lock = threading.Lock()
_check_done = threading.Event()


def _get_cache_path() -> Path:
    """Return path to the update check cache file.

    Follows XDG_CONFIG_HOME convention, same directory as credentials.toml.
    """
    config_home = os.getenv("XDG_CONFIG_HOME")
    base_dir = (
        Path(config_home).expanduser() if config_home else Path.home() / ".config"
    )
    return base_dir / "runpod" / CACHE_FILENAME


def _read_cache(path: Path) -> dict | None:
    """Read the cache JSON file. Return None on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _write_cache(path: Path, latest_version: str) -> None:
    """Write cache with current UTC timestamp and latest version.

    Creates parent directories if needed. Silently ignores write failures.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "last_checked_utc": datetime.now(timezone.utc).isoformat(),
            "latest_version": latest_version,
        }
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def _is_cache_fresh(cache: dict) -> bool:
    """Return True if the cache was written within CHECK_INTERVAL_HOURS."""
    try:
        last_checked = datetime.fromisoformat(cache["last_checked_utc"])
        elapsed_hours = (
            datetime.now(timezone.utc) - last_checked
        ).total_seconds() / 3600
        return elapsed_hours < CHECK_INTERVAL_HOURS
    except (KeyError, ValueError, TypeError):
        return False


def _run_check() -> None:
    """Thread body: check PyPI for a newer version.

    Reads cache first. If fresh, uses cached latest_version. Otherwise fetches
    from PyPI and updates cache. Compares against current installed version.
    All exceptions are swallowed -- this must never crash the CLI.
    """
    global _newer_version  # noqa: PLW0603
    try:
        current = _get_current_version()
        if current == "unknown":
            return

        cache_path = _get_cache_path()
        cache = _read_cache(cache_path)

        if cache and _is_cache_fresh(cache):
            latest = cache.get("latest_version")
        else:
            latest, _ = _fetch_pypi_metadata()
            _write_cache(cache_path, latest)

        if not latest:
            return

        current_tuple = _parse_version(current)
        latest_tuple = _parse_version(latest)

        if latest_tuple > current_tuple:
            with _result_lock:
                _newer_version = latest
    except Exception:  # noqa: BLE001
        pass
    finally:
        _check_done.set()


def _print_update_notice() -> None:
    """atexit handler: print update notice to stderr if a newer version was found.

    If the background thread hasn't finished yet, skip silently.
    Uses plain text (no Rich markup) since atexit runs after Rich teardown.
    """
    if not _check_done.is_set():
        return

    with _result_lock:
        version = _newer_version

    if version:
        print(
            f"\nA new version of runpod-flash is available: {version}"
            "  Run 'flash update' to upgrade.",
            file=sys.stderr,
        )


def start_background_check() -> None:
    """Start the passive update check.

    Skips if FLASH_NO_UPDATE_CHECK or CI environment variables are set.
    Spawns a daemon thread and registers an atexit handler.
    """
    if os.getenv("FLASH_NO_UPDATE_CHECK"):
        return
    if os.getenv("CI"):
        return

    thread = threading.Thread(target=_run_check, daemon=True)
    thread.start()
    atexit.register(_print_update_notice)
