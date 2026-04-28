"""flash context detection.

reads environment variables to determine whether calls should use flash
sentinel resolution (deployed endpoints) or the live ephemeral flow
(flash dev).

dotenv files loaded at runpod_flash import time populate FLASH_APP and
FLASH_ENV, so a committed .env works the same as any other config surface.

defaults:
- FLASH_APP defaults to the current working directory name
- FLASH_ENV defaults to "production"

flash dev sets FLASH_IS_LIVE_PROVISIONING=true, which causes
get_flash_context() to return None so callers fall through to the
live provisioning path. all other invocations use sentinel resolution.
"""

import logging
import os
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger(__name__)

DEFAULT_ENV = "production"


def _default_app_name() -> str:
    """derive the default app name from the current working directory."""
    return Path.cwd().name


def get_flash_context() -> Optional[Tuple[str, str]]:
    """get the flash app and environment for sentinel resolution.

    returns (app_name, env_name) for sentinel resolution, or None when
    flash dev is active (FLASH_IS_LIVE_PROVISIONING=true).

    precedence:
    1. FLASH_IS_LIVE_PROVISIONING=true -> None (flash dev live flow)
    2. otherwise -> (app, env) for sentinel resolution

    defaults:
    - app: FLASH_APP env var, or current directory name
    - env: FLASH_ENV env var, or "production"
    """
    if os.getenv("FLASH_IS_LIVE_PROVISIONING", "").lower() == "true":
        return None

    app = os.getenv("FLASH_APP") or _default_app_name()
    env = os.getenv("FLASH_ENV") or DEFAULT_ENV

    return (app, env)


def get_flash_app() -> Optional[str]:
    """get the flash app name from FLASH_APP env var, or None if unset."""
    return os.getenv("FLASH_APP")
