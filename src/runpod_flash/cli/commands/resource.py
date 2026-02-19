"""Resource management commands."""

import time
import typer
from rich.console import Console
from rich.live import Live

from ...core.resources.resource_manager import ResourceManager

console = Console()


def report_command(
    live: bool = typer.Option(False, "--live", "-l", help="Live updating status"),
    refresh: int = typer.Option(
        2, "--refresh", "-r", help="Refresh interval for live mode"
    ),
):
    """Show resource status dashboard."""

    resource_manager = ResourceManager()

    if live:
        try:
            with Live(
                _render_resource_report(resource_manager),
                console=console,
                refresh_per_second=1 / refresh,
                screen=True,
            ) as live_display:
                while True:
                    time.sleep(refresh)
                    live_display.update(_render_resource_report(resource_manager))
        except KeyboardInterrupt:
            console.print("\nStopped")
    else:
        output = _render_resource_report(resource_manager)
        console.print(output)


def _render_resource_report(resource_manager: ResourceManager):
    """Build a rich renderable for the current resource state."""
    from rich.text import Text

    resources = resource_manager._resources

    if not resources:
        return Text("No resources tracked.")

    lines = Text()
    lines.append("\nResources\n\n", style="bold")

    active_count = 0
    error_count = 0

    for uid, resource in resources.items():
        try:
            is_deployed = resource.is_deployed()
            if is_deployed:
                color, status_text = "green", "active"
                active_count += 1
            else:
                color, status_text = "red", "inactive"
                error_count += 1
        except Exception:
            color, status_text = "yellow", "unknown"

        resource_type = resource.__class__.__name__
        try:
            url = resource.url if hasattr(resource, "url") else ""
        except Exception:
            url = ""

        display_uid = uid[:20] + "..." if len(uid) > 20 else uid

        lines.append(f"  {display_uid}", style="bold")
        lines.append(f"  {status_text}", style=color)
        lines.append(f"  {resource_type}")
        if url:
            lines.append(f"  {url}")
        lines.append("\n")

    total = len(resources)
    idle_count = total - active_count - error_count
    parts = [f"{active_count} active"]
    if idle_count > 0:
        parts.append(f"{idle_count} idle")
    if error_count > 0:
        parts.append(f"{error_count} error")

    lines.append(f"\n{total} resources ({', '.join(parts)})\n")

    return lines
