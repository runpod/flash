"""flash context detection.

reads environment variables to determine whether calls should use flash
sentinel resolution (deployed endpoints) or the live ephemeral flow.

dotenv files loaded at runpod_flash import time populate FLASH_APP and
FLASH_ENV, so a committed .env works the same as any other config surface.
"""

import logging
import os
from typing import Optional, Tuple

log = logging.getLogger(__name__)


def get_flash_context() -> Optional[Tuple[str, str]]:
    """get the flash app and environment for sentinel resolution.

    returns (app_name, env_name) when flash sentinel resolution should
    be used, or None when the live ephemeral flow should be used.

    precedence:
    1. FLASH_IS_LIVE_PROVISIONING=true forces live (flash dev)
    2. FLASH_APP + FLASH_ENV both set -> sentinel
    3. anything else -> live flow
    """
    if os.getenv("FLASH_IS_LIVE_PROVISIONING", "").lower() == "true":
        return None

    app = os.getenv("FLASH_APP")
    env = os.getenv("FLASH_ENV")

    if app and env:
        return (app, env)

    return None


def get_flash_app() -> Optional[str]:
    """get the flash app name from FLASH_APP env var, or None if unset."""
    return os.getenv("FLASH_APP")
