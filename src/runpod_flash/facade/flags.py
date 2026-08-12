"""feature flag gating the apps-dispatch facade."""

import os


def use_apps_dispatch() -> bool:
    """true when FLASH_USE_APPS_DISPATCH selects the apps dispatch path."""
    return os.getenv("FLASH_USE_APPS_DISPATCH", "").lower() == "true"
