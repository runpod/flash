"""Project initialization command."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from ..utils.skeleton import create_project_skeleton, detect_file_conflicts

console = Console()


def init_command(
    project_name: Optional[str] = typer.Argument(
        None, help="Project name or '.' for current directory"
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing files"),
):
    """Create new Flash project with Flash Server and GPU workers."""

    if project_name is None or project_name == ".":
        project_dir = Path.cwd()
        is_current_dir = True
        actual_project_name = project_dir.name
    else:
        project_dir = Path(project_name)
        is_current_dir = False
        actual_project_name = project_name

    if not is_current_dir:
        project_dir.mkdir(parents=True, exist_ok=True)

    conflicts = detect_file_conflicts(project_dir)
    should_overwrite = force

    if conflicts and not force:
        console.print("[yellow]Warning:[/yellow] The following files will be overwritten:\n")
        for conflict in conflicts:
            console.print(f"  [dim]{conflict}[/dim]")
        console.print()

        proceed = typer.confirm("Continue and overwrite these files?", default=False)
        if not proceed:
            console.print("[yellow]Cancelled[/yellow]")
            raise typer.Exit(0)

        should_overwrite = True

    status_msg = (
        "Initializing Flash project..."
        if is_current_dir
        else f"Creating Flash project '{project_name}'..."
    )
    with console.status(status_msg):
        create_project_skeleton(project_dir, should_overwrite)

    console.print(
        f"[green]Created[/green] [bold]{actual_project_name}[/bold]\n"
    )

    if is_current_dir:
        console.print("[bold]Structure:[/bold]")
        console.print("  [dim]./[/dim]")
    else:
        console.print("[bold]Structure:[/bold]")
        console.print(f"  [dim]{actual_project_name}/[/dim]")

    console.print("  [dim]├── main.py              Flash Server (FastAPI)[/dim]")
    console.print("  [dim]├── mothership.py        Mothership endpoint config[/dim]")
    console.print("  [dim]├── pyproject.toml       Python project config[/dim]")
    console.print("  [dim]├── workers/[/dim]")
    console.print("  [dim]│   ├── gpu/             GPU worker[/dim]")
    console.print("  [dim]│   └── cpu/             CPU worker[/dim]")
    console.print("  [dim]├── .env.example[/dim]")
    console.print("  [dim]├── requirements.txt[/dim]")
    console.print("  [dim]└── README.md[/dim]")

    console.print("\n[bold]Next steps:[/bold]")
    step_num = 1
    if not is_current_dir:
        console.print(f"  [dim]{step_num}. cd {actual_project_name}[/dim]")
        step_num += 1
    console.print(f"  [dim]{step_num}. Review and customize mothership.py (optional)[/dim]")
    step_num += 1
    console.print(f"  [dim]{step_num}. pip install -r requirements.txt[/dim]")
    step_num += 1
    console.print(f"  [dim]{step_num}. cp .env.example .env[/dim]")
    step_num += 1
    console.print(f"  [dim]{step_num}. Add your RUNPOD_API_KEY to .env[/dim]")
    step_num += 1
    console.print(f"  [dim]{step_num}. flash run[/dim]")

    console.print("\n[bold]API key:[/bold]")
    console.print("  [dim]https://docs.runpod.io/get-started/api-keys[/dim]")
    console.print("\n[dim]Visit http://localhost:8888/docs after running[/dim]")
