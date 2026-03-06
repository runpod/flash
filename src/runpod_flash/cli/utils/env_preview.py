"""Deploy-time env preview: show what env vars go to each endpoint."""

from __future__ import annotations

import re
from typing import Any

from rich.console import Console
from rich.table import Table

_SECRET_PATTERN = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)

_MASK_VISIBLE_CHARS = 6


def mask_env_value(key: str, value: str) -> str:
    """Mask value if key matches secret patterns.

    Keys containing KEY, TOKEN, SECRET, PASSWORD, or CREDENTIAL
    (case-insensitive) get masked: first 6 chars + '...****'.
    Short values are fully masked.
    """
    if not _SECRET_PATTERN.search(key):
        return value

    if len(value) <= _MASK_VISIBLE_CHARS:
        return "****"

    return value[:_MASK_VISIBLE_CHARS] + "...****"


def collect_env_for_preview(
    manifest: dict[str, Any],
) -> dict[str, list[tuple[str, str, str]]]:
    """Collect env vars per resource for preview display.

    Returns:
        Dict mapping resource_name -> list of (key, value, source) tuples.
        source is "user" for user-declared vars, "flash" for injected vars.
    """
    from runpod_flash.core.credentials import get_api_key

    resources = manifest.get("resources", {})
    result: dict[str, list[tuple[str, str, str]]] = {}

    api_key = get_api_key()

    for resource_name, config in resources.items():
        entries: list[tuple[str, str, str]] = []

        user_env = config.get("env") or {}
        for key, value in sorted(user_env.items()):
            entries.append((key, str(value), "user"))

        is_lb = config.get("is_load_balanced", False)

        # Mirror _do_deploy injection: QB endpoints get RUNPOD_API_KEY,
        # LB endpoints get FLASH_MODULE_PATH. LB endpoints do NOT get
        # RUNPOD_API_KEY injected at deploy time.
        if not is_lb and config.get("makes_remote_calls", False):
            if "RUNPOD_API_KEY" not in user_env and api_key:
                entries.append(("RUNPOD_API_KEY", api_key, "flash"))

        if is_lb:
            if "FLASH_MODULE_PATH" not in user_env:
                module_path = config.get("module_path", "")
                if module_path:
                    entries.append(("FLASH_MODULE_PATH", module_path, "flash"))

        result[resource_name] = entries

    return result


def render_env_preview(
    manifest: dict[str, Any],
    console: Console | None = None,
) -> None:
    """Render a compact deploy-time env preview table to console."""
    if console is None:
        console = Console()

    env_data = collect_env_for_preview(manifest)

    if not env_data:
        return

    # Single compact table: one row per (resource, var) pair
    table = Table(
        title="Deploy Env Vars",
        show_header=True,
        header_style="bold",
        padding=(0, 1),
    )
    table.add_column("Resource", style="cyan")
    table.add_column("Variable")
    table.add_column("Value")
    table.add_column("Source", style="dim")

    for resource_name, entries in sorted(env_data.items()):
        if not entries:
            table.add_row(resource_name, "(none)", "", "")
        else:
            for i, (key, value, source) in enumerate(entries):
                masked = mask_env_value(key, value)
                if source == "flash":
                    source_label = "flash"
                elif source == "user":
                    source_label = "user"
                else:
                    source_label = source or ""
                # Show resource name only on first row for that resource
                label = resource_name if i == 0 else ""
                table.add_row(label, key, masked, source_label)

    console.print(table)
