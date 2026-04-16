"""flash context detection and configuration.

reads flash.toml and environment variables to determine whether calls
should use flash sentinel resolution (deployed endpoints) or the live
ephemeral flow.
"""

import logging
import os
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger(__name__)


def _read_flash_toml() -> dict:
    """read flash.toml from the current working directory."""
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            log.debug("no toml library available, skipping flash.toml")
            return {}

    path = Path.cwd() / "flash.toml"
    if not path.exists():
        return {}

    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        log.warning("failed to read flash.toml: %s", e)
        return {}


def get_flash_context() -> Optional[Tuple[str, str]]:
    """get the flash app and environment for sentinel resolution.

    returns (app_name, env_name) when flash sentinel resolution should
    be used, or None when the live ephemeral flow should be used.

    precedence:
    1. FLASH_IS_LIVE_PROVISIONING=true forces live (flash dev)
    2. FLASH_APP + FLASH_ENV env vars (deployed worker or explicit)
    3. flash.toml app + env (local dev targeting deployed)
    4. FLASH_ENV env var overrides flash.toml env field
    5. no context -> live flow
    """
    if os.getenv("FLASH_IS_LIVE_PROVISIONING", "").lower() == "true":
        return None

    app = os.getenv("FLASH_APP")
    env = os.getenv("FLASH_ENV")

    if not app or not env:
        config = _read_flash_toml()
        app = app or config.get("app")
        env = env or config.get("env")

    if app and env:
        return (app, env)

    return None


def get_flash_app() -> Optional[str]:
    """get the flash app name from env or flash.toml."""
    app = os.getenv("FLASH_APP")
    if app:
        return app
    return _read_flash_toml().get("app")


def invalidate_config_cache() -> None:
    """no-op for backward compat. flash.toml is read on every call."""
    pass
