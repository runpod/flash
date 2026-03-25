"""Credential management for runpod_flash.

Thin wrappers around runpod-python's credential functions.
Resolution priority: RUNPOD_API_KEY env var > .env > ~/.runpod/config.toml
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import runpod.cli.groups.config.functions as _runpod_config

from runpod.cli.groups.config.functions import (
    get_credentials,
    set_credentials,
)

log = logging.getLogger(__name__)

_OLD_XDG_PATH = Path.home() / ".config" / "runpod" / "credentials.toml"


def get_credentials_path() -> Path:
    """Return the path to the runpod credentials file."""
    return Path(_runpod_config.CREDENTIAL_FILE)


def get_api_key() -> Optional[str]:
    """Get API key with priority: env var > credentials file.

    Returns:
        API key string, or None if not found.
    """
    api_key = os.getenv("RUNPOD_API_KEY")
    if api_key and api_key.strip():
        return api_key

    try:
        creds = get_credentials()
    except Exception:
        log.debug("Failed to read credentials file", exc_info=True)
        return None
    if creds and isinstance(creds.get("api_key"), str) and creds["api_key"].strip():
        return creds["api_key"]

    return None


def save_api_key(api_key: str) -> Path:
    """Save API key to ~/.runpod/config.toml via runpod-python.

    Args:
        api_key: The API key to save.

    Returns:
        Path to the credentials file.
    """
    path = get_credentials_path()
    set_credentials(api_key, overwrite=True)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def check_and_migrate_legacy_credentials() -> None:
    """Check for credentials at old XDG path and migrate if needed.

    Called during flash login on successful auth. If an old credentials file
    exists and the new location has no credentials, automatically migrate the
    legacy API key to the new credentials file.
    """
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

    try:
        existing_creds = get_credentials()
    except Exception:
        log.debug(
            "Failed to read credentials file while checking for legacy migration",
            exc_info=True,
        )
        existing_creds = None

    if (
        existing_creds
        and isinstance(existing_creds.get("api_key"), str)
        and existing_creds["api_key"].strip()
    ):
        return

    new_path = get_credentials_path()
    old_path = _OLD_XDG_PATH

    if not old_path.exists():
        return

    try:
        with old_path.open("rb") as f:
            old_data = tomllib.load(f)
        old_key = old_data.get("api_key")
        if not isinstance(old_key, str) or not old_key.strip():
            return
    except (OSError, ValueError):
        return

    log.info("Found credentials at legacy path: %s", old_path)

    try:
        from rich.console import Console

        console = Console()
        console.print(
            f"\n[yellow]Found credentials at old location:[/yellow]"
            f"\n  {old_path}"
            f"\n[yellow]Migrating to:[/yellow]"
            f"\n  {new_path}\n"
        )
        save_api_key(old_key)
        old_path.unlink()
        try:
            old_path.parent.rmdir()
        except OSError:
            pass
        console.print("[green]Migrated.[/green] Old file removed.\n")
    except (OSError, ValueError):
        log.warning(
            "Could not migrate credentials from %s to %s. "
            "Run 'flash login' to create new credentials.",
            old_path,
            new_path,
        )
