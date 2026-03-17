"""Agent rules generation command."""

from importlib import metadata
from pathlib import Path

from rich.console import Console

from ...rules.engine import generate_agent_files, update_dynamic_context

console = Console()


def _get_version() -> str:
    """Get the package version from metadata."""
    try:
        return metadata.version("runpod-flash")
    except metadata.PackageNotFoundError:
        return "unknown"


def rules_command() -> None:
    """Generate or regenerate AI agent context files."""
    project_dir = Path.cwd()

    version = _get_version()
    written = generate_agent_files(project_dir, version)
    update_dynamic_context(project_dir)

    if written:
        console.print(f"[green]Generated {len(written)} agent file(s):[/green]")
        for f in written:
            console.print(f"  {f}")
    else:
        console.print("[yellow]No agent files generated (all disabled).[/yellow]")
