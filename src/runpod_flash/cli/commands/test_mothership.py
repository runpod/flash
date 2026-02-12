"""Flash test-mothership command - Test mothership boot locally with Docker."""

import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

logger = logging.getLogger(__name__)
console = Console()


def _clear_resource_cache() -> None:
    """Clear ResourceManager cache for clean test environment.

    Test-mothership deploys temporary endpoints that should not persist
    between test runs. Clearing the cache prevents:
    - Stale resources from previous tests being redeployed
    - Name conflicts between old and new test resources
    - Confusion from endpoints that no longer exist in the codebase
    """
    cache_file = Path.home() / ".runpod" / "resources.pkl"
    if cache_file.exists():
        try:
            cache_file.unlink()
            console.print(
                "[dim]Cleared resource cache for clean test environment[/dim]"
            )
            logger.debug(f"Removed cache file: {cache_file}")
        except Exception as e:
            console.print(f"[yellow]Warning: Could not clear cache: {e}[/yellow]")
            logger.warning(f"Failed to remove cache file {cache_file}: {e}")


def test_mothership_command(
    image: str = typer.Option(
        "runpod/flash-lb-cpu:local",
        "--image",
        help="Docker image to use for testing",
    ),
    port: int = typer.Option(8000, "--port", help="Local port to expose"),
    endpoint_id: Optional[str] = typer.Option(
        None, "--endpoint-id", help="RunPod endpoint ID (auto-generated if omitted)"
    ),
    build_dir: str = typer.Option(
        ".flash/.build", "--build-dir", help="Path to build directory"
    ),
    no_build: bool = typer.Option(
        False, "--no-build", help="Skip running flash build first"
    ),
):
    """
    Test mothership boot locally with Docker.

    Runs the application in a Docker container with CLI-time resource provisioning.
    This simulates the deployment process by provisioning all resources from the
    manifest before starting the server. On shutdown (Ctrl+C or docker stop),
    automatically cleans up all deployed endpoints.

    Examples:
      flash test-mothership                       # Default setup
      flash test-mothership --port 9000           # Custom port
      flash test-mothership --image custom:latest # Custom Docker image
      flash test-mothership --no-build            # Skip flash build step
    """
    try:
        # Verify prerequisites
        _verify_prerequisites()

        # Clear resource cache to prevent stale entries in test mode
        _clear_resource_cache()

        # Build if needed
        if not no_build:
            _run_flash_build()

        # Generate endpoint ID if not provided
        if not endpoint_id:
            endpoint_id = f"test-mothership-{int(time.time())}"

        # Create entrypoint script for cleanup on shutdown
        _create_entrypoint_script(build_dir)

        # Display configuration
        _display_test_objectives()
        _display_config(build_dir, image, port, endpoint_id)

        # Build Docker command
        docker_cmd = _build_docker_command(image, port, endpoint_id, build_dir)

        # Run Docker container
        _run_docker_container(docker_cmd, port)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        logger.exception("Unexpected error in test_mothership_command")
        raise typer.Exit(1)


def _verify_prerequisites() -> None:
    """Verify that Docker and RUNPOD_API_KEY are available."""
    # Check Docker
    result = shutil.which("docker")
    if not result:
        console.print("[red]Error:[/red] Docker is not installed or not in PATH")
        console.print(
            "Install Docker from: https://www.docker.com/products/docker-desktop"
        )
        raise typer.Exit(1)

    # Check Docker daemon
    try:
        subprocess.run(
            ["docker", "ps"],
            capture_output=True,
            check=True,
            timeout=5,
        )
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        console.print("[red]Error:[/red] Docker daemon is not running")
        console.print("Start Docker and try again")
        raise typer.Exit(1)

    # Check RUNPOD_API_KEY
    import os

    if not os.getenv("RUNPOD_API_KEY"):
        console.print("[red]Error:[/red] RUNPOD_API_KEY environment variable not set")
        console.print("Set it with: export RUNPOD_API_KEY=your-api-key")
        raise typer.Exit(1)


def _run_flash_build() -> None:
    """Run flash build command."""
    console.print("[cyan]Running flash build...[/cyan]")
    result = subprocess.run(
        ["flash", "build", "--keep-build", "--use-local-flash"],
        capture_output=False,
    )
    if result.returncode != 0:
        console.print("[red]Error:[/red] flash build failed")
        raise typer.Exit(1)


def _get_manifest_provisioning_code() -> str:
    """Generate Python code to provision resources from flash_manifest.json.

    Uses the manifest as a guide to discover which modules contain resource configs.
    Imports the actual resource configs from source (endpoint files) to get full
    configuration (workers, GPUs, etc.). This ensures test-mothership provisions
    exactly what was built, without discovering skeleton templates.

    Returns:
        Python code as a string to be executed
    """
    return """
import asyncio
import importlib
import json
import logging
import os
import sys
from pathlib import Path
from runpod_flash.core.deployment import DeploymentOrchestrator

logger = logging.getLogger(__name__)

# Configure logging to match the rest of the system
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

async def provision_from_manifest():
    manifest_path = Path("flash_manifest.json")
    if not manifest_path.exists():
        print("[dim]No flash_manifest.json found, skipping manifest-based provisioning[/dim]")
        return

    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except Exception as e:
        logger.error(f"Error loading manifest: {e}")
        return

    # Set test-mothership mode for resource naming
    os.environ["FLASH_IS_TEST_MOTHERSHIP"] = "true"

    resources = []
    for resource_name, resource_data in manifest.get("resources", {}).items():
        try:
            # Get list of modules that contain this resource's functions
            functions = resource_data.get("functions", [])
            if not functions:
                logger.warning(f"No functions found for resource {resource_name}")
                continue

            # Import the first function's module to get access to the config
            first_func = functions[0]
            module_name = first_func.get("module")
            if not module_name:
                logger.warning(f"No module found for resource {resource_name}")
                continue

            # Import the module and look for resource config variable
            try:
                module = importlib.import_module(module_name)

                config = None

                # Try config_variable from manifest first (most reliable)
                config_variable = resource_data.get("config_variable")
                if config_variable and hasattr(module, config_variable):
                    config = getattr(module, config_variable)
                    logger.info(f"Loaded resource config from {module_name}: {config.name} (variable: {config_variable})")
                else:
                    # Fallback to old search logic for backward compatibility
                    config_names = [
                        "gpu_config", "cpu_config",
                        "resource_config", "config",
                        f"{resource_name.lower()}_config",
                    ]

                    for config_name in config_names:
                        if hasattr(module, config_name):
                            config = getattr(module, config_name)
                            break

                    if config:
                        logger.info(f"Loaded resource config from {module_name}: {config.name}")
                    else:
                        logger.warning(f"No config variable found in {module_name} for {resource_name}")

                if config:
                    # Apply test-mothership naming convention
                    if not resource_name.startswith("tmp-"):
                        config.name = f"tmp-{resource_name}"
                    else:
                        config.name = resource_name

                    resources.append(config)

            except Exception as e:
                logger.warning(f"Failed to import resource config from {module_name}: {e}")

        except Exception as e:
            logger.error(f"Failed to process resource {resource_name}: {e}")

    if resources:
        try:
            logger.info(f"Provisioning {len(resources)} resource(s)...")
            orchestrator = DeploymentOrchestrator()
            await orchestrator.deploy_all(resources, show_progress=True)
        except Exception as e:
            logger.warning(f"Provisioning error: {e}")
    else:
        logger.warning("No resources loaded from manifest")

asyncio.run(provision_from_manifest())
"""


def _create_entrypoint_script(build_dir: str) -> None:
    """Create entrypoint.sh script for Docker container.

    This script handles signal trapping and cleanup on shutdown.
    It runs manifest-based provisioning then flash run.
    """
    build_path = Path(build_dir)

    # Ensure build directory exists
    if not build_path.exists():
        console.print(
            f"[yellow]Warning:[/yellow] Build directory {build_dir} does not exist"
        )
        return

    script_path = build_path / "entrypoint.sh"
    provisioning_script_path = build_path / "provision_from_manifest.py"

    # Write provisioning script to file
    provisioning_code = _get_manifest_provisioning_code()
    provisioning_script_path.write_text(provisioning_code)

    script_content = """#!/bin/bash
set -e

# Ensure bundled dependencies are available to Python
# /workspace contains all the pip-installed packages (.so files, pure Python modules, etc)
export PYTHONPATH="/workspace:${PYTHONPATH}"

# Signal test-mothership provisioning context for resource naming
export FLASH_IS_TEST_MOTHERSHIP="true"

cleanup() {
    echo ""
    echo "=========================================="
    echo "Shutting down test-mothership..."
    echo "Cleaning up all temporary endpoints..."
    echo "=========================================="
    python -m runpod_flash.cli.main undeploy --all --force || true
    echo "Cleanup complete"
    exit 0
}

trap cleanup SIGTERM SIGINT

echo "=========================================="
echo "Starting mothership test environment"
echo "Phase 1: Mothership container startup"
echo "=========================================="

# Provision resources from manifest before starting server
# All resources are provisioned upfront (CLI-time provisioning)
python3 provision_from_manifest.py

# Start server
python -m runpod_flash.cli.main run --host 0.0.0.0 --port 8000 &
PID=$!

wait $PID
"""

    script_path.write_text(script_content)
    script_path.chmod(0o755)


def _display_test_objectives() -> None:
    """Display what test-mothership tests and important warnings."""
    objectives_text = """[bold cyan]What this tests:[/bold cyan]
• Mothership container deployment
• CLI-time resource provisioning from manifest
• State Manager integration for endpoint discovery

[bold yellow]⚠ Important:[/bold yellow]
• Uses peer-to-peer architecture
• All endpoints query State Manager directly
• Test endpoints are [bold]temporary[/bold] - prefixed with 'tmp-'
• All endpoints will be [bold]automatically cleaned up[/bold] on shutdown

[dim]These are test deployments only. Use 'flash deploy' for production.[/dim]"""

    console.print(
        Panel(
            objectives_text,
            title="Test-Mothership Overview",
            border_style="cyan",
        )
    )
    console.print()


def _display_config(build_dir: str, image: str, port: int, endpoint_id: str) -> None:
    """Display test configuration."""
    config_text = f"""[bold]Build directory:[/bold] {build_dir}
[bold]Command:[/bold] flash run
[bold]Docker image:[/bold] {image}
[bold]Endpoint ID:[/bold] {endpoint_id}
[bold]Port:[/bold] http://localhost:{port}"""

    console.print(Panel(config_text, title="🚀 Starting mothership test container"))


def _build_docker_command(
    image: str, port: int, endpoint_id: str, build_dir: str
) -> list:
    """Build the docker run command."""
    import os

    build_path = Path(build_dir).resolve()

    cmd = [
        "docker",
        "run",
        "--platform",
        "linux/amd64",
        "--rm",
    ]

    # Add interactive flags only if running in a TTY environment
    if sys.stdin.isatty() and sys.stdout.isatty():
        cmd.extend(["-it"])

    cmd.extend(
        [
            "-e",
            "FLASH_IS_TEST_MOTHERSHIP=true",
            "-e",
            f"RUNPOD_ENDPOINT_ID={endpoint_id}",
            "-e",
            f"RUNPOD_API_KEY={os.getenv('RUNPOD_API_KEY')}",
            "-e",
            "FLASH_MANIFEST_PATH=/workspace/flash_manifest.json",
            "-v",
            f"{build_path}:/workspace",
            "-p",
            f"{port}:8000",
            "--workdir",
            "/workspace",
            image,
            "/workspace/entrypoint.sh",
        ]
    )

    return cmd


def _run_docker_container(docker_cmd: list, port: int) -> None:
    """Run the Docker container with helpful output."""
    console.print("[cyan]✅ Container started successfully[/cyan]\n")
    console.print(f"[dim]Local: http://localhost:{port}[/dim]\n")
    console.print("[dim]Verification commands:[/dim]")
    console.print(f"[dim]  Health: curl http://localhost:{port}/ping[/dim]")
    console.print(
        "[dim]  State Manager Query: All endpoints query State Manager directly[/dim]"
    )
    console.print("[dim]  No /manifest endpoint - peer-to-peer architecture[/dim]\n")
    console.print("[bold]Test phases:[/bold]")
    console.print("  [dim]1. Mothership startup and health check[/dim]")
    console.print(
        "  [dim]2. CLI-time provisioning of endpoints (prefixed with 'tmp-')[/dim]"
    )
    console.print("  [dim]3. State Manager update with endpoint URLs[/dim]")
    console.print()
    console.print("[dim]Watch container logs below for provisioning progress...[/dim]")
    console.print("[dim]Press Ctrl+C to stop and cleanup all endpoints.\n[/dim]")

    try:
        result = subprocess.run(docker_cmd, check=False, capture_output=False)
        if result.returncode != 0:
            console.print(
                "\n[yellow]Container exited with an error.[/yellow] "
                "Check the logs above for details. Common issues: missing RUNPOD_API_KEY, "
                "port already in use, or Docker daemon not running."
            )
    except KeyboardInterrupt:
        console.print("\n[yellow]Container stopped[/yellow]")
    except Exception as e:
        console.print(f"[red]Error running container:[/red] {e}")
        raise typer.Exit(1)
