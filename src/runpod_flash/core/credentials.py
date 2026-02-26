from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

try:
    import tomllib
except ImportError:  # python < 3.11
    import tomli as tomllib


def get_credentials_path() -> Path:
    credentials_file = os.getenv("RUNPOD_CREDENTIALS_FILE")
    if credentials_file:
        return Path(credentials_file).expanduser()

    config_home = os.getenv("XDG_CONFIG_HOME")
    base_dir = (
        Path(config_home).expanduser() if config_home else Path.home() / ".config"
    )
    return base_dir / "runpod" / "credentials.toml"


def _read_credentials() -> dict:
    path = get_credentials_path()
    if not path.exists():
        return {}

    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, ValueError):
        return {}


def get_api_key() -> Optional[str]:
    api_key = os.getenv("RUNPOD_API_KEY")
    if api_key and api_key.strip():
        return api_key

    stored = _read_credentials().get("api_key")
    if isinstance(stored, str) and stored.strip():
        return stored

    return None


def save_api_key(api_key: str) -> Path:
    path = get_credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'api_key = "{api_key}"\n', encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path
