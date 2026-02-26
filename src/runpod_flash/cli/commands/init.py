"""Project initialization command."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from ..utils.skeleton import create_project_skeleton, detect_file_conflicts

console = Console()


def init_command(
    project_name: Optional[str] = typer.Argument(
        None, help="Project name or '.' for current directory"
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing files"),
):
    """Create new Flash project with Flash Server and GPU workers."""

    # Determine target directory and initialization mode
    if project_name is None or project_name == ".":
        # Initialize in current directory
        project_dir = Path.cwd()
        is_current_dir = True
        # Use current directory name as project name
        actual_project_name = project_dir.name
    else:
        # Create new directory
        project_dir = Path(project_name)
        is_current_dir = False
        actual_project_name = project_name

    # Create project directory if needed
    if not is_current_dir:
        project_dir.mkdir(parents=True, exist_ok=True)

    # Check for file conflicts in target directory
    conflicts = detect_file_conflicts(project_dir)
    should_overwrite = force  # Start with force flag value

    if conflicts and not force:
        # Show warning and prompt user
        console.print(
            Panel(
                "[yellow]Warning: The following files will be overwritten:[/yellow]\n\n"
                + "\n".join(f"  • {conflict}" for conflict in conflicts),
                title="File Conflicts Detected",
                expand=False,
            )
        )

        # Prompt user for confirmation
        proceed = typer.confirm("Continue and overwrite these files?", default=False)
        if not proceed:
            console.print("[yellow]Initialization aborted.[/yellow]")
            raise typer.Exit(0)

        # User confirmed, so we should overwrite
        should_overwrite = True

    # Create project skeleton
    status_msg = (
        "Initializing Flash project in current directory..."
        if is_current_dir
        else f"Creating Flash project '{project_name}'..."
    )
    with console.status(status_msg):
        create_project_skeleton(project_dir, should_overwrite)

    # Success output
    if is_current_dir:
        panel_content = f"Flash project '[bold]{actual_project_name}[/bold]' initialized in current directory!\n\n"
        panel_content += "Project structure:\n"
        panel_content += "  ./\n"
    else:
        panel_content = f"Flash project '[bold]{actual_project_name}[/bold]' created successfully!\n\n"
        panel_content += "Project structure:\n"
        panel_content += f"  {actual_project_name}/\n"

    panel_content += "  ├── gpu_worker.py        # GPU serverless worker\n"
    panel_content += "  ├── cpu_worker.py        # CPU serverless worker\n"
    panel_content += "  ├── lb_worker.py         # CPU load-balanced API\n"
    panel_content += "  ├── pyproject.toml\n"
    panel_content += "  ├── .env.example\n"
    panel_content += "  ├── requirements.txt\n"
    panel_content += "  └── README.md\n"

    title = "Project Initialized" if is_current_dir else "Project Created"
    console.print(Panel(panel_content, title=title, expand=False))

    # next steps
    console.print("\n[bold]Next steps:[/bold]")
    step_num = 1
    if not is_current_dir:
        console.print(f"  {step_num}. cd {actual_project_name}")
        step_num += 1
    console.print(f"  {step_num}. pip install -r requirements.txt")
    step_num += 1
    steps_table.add_row(
        f"{step_num}.", "Add your RUNPOD_API_KEY to .env (or run flash login)"
    )
    step_num += 1
    console.print(f"  {step_num}. flash dev")

    console.print(steps_table)

    console.print("\n[bold]Get your API key:[/bold]")
    console.print("  https://docs.runpod.io/get-started/api-keys")
    console.print("\n[bold]Or authenticate with flash:[/bold]")
    console.print("  flash login")
    console.print("\nVisit http://localhost:8888/docs after running")
    console.print("\nCheck out the README.md for more")
