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

    for resource_name, config in resources.items():
        entries: list[tuple[str, str, str]] = []

        user_env = config.get("env") or {}
        for key, value in sorted(user_env.items()):
            entries.append((key, str(value), "user"))

        if config.get("makes_remote_calls", False):
            if "RUNPOD_API_KEY" not in user_env:
                api_key = get_api_key()
                if api_key:
                    entries.append(("RUNPOD_API_KEY", api_key, "flash"))

        if config.get("is_load_balanced", False):
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
    """Render deploy-time env preview table to console."""
    if console is None:
        console = Console()

    env_data = collect_env_for_preview(manifest)

    if not env_data:
        return

    console.print("\n[bold]Environment Variables per Resource:[/bold]\n")

    for resource_name, entries in sorted(env_data.items()):
        table = Table(
            title=resource_name,
            show_header=True,
            header_style="bold",
            padding=(0, 1),
        )
        table.add_column("Variable", style="cyan")
        table.add_column("Value")
        table.add_column("Source", style="dim")

        if not entries:
            table.add_row("(none)", "", "")
        else:
            for key, value, source in entries:
                masked = mask_env_value(key, value)
                source_label = "injected by flash" if source == "flash" else ""
                table.add_row(key, masked, source_label)

        console.print(table)
        console.print()
