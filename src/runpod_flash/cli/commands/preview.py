"""Flash preview command - Launch local distributed system test environment."""

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from runpod_flash.core.resources.constants import (
    FLASH_CPU_IMAGE,
    FLASH_CPU_LB_IMAGE,
    FLASH_GPU_IMAGE,
    FLASH_LB_IMAGE,
)

logger = logging.getLogger(__name__)
console = Console()

# Container archive mount path - expected location where containers unpack the archive
CONTAINER_ARCHIVE_PATH = "/root/.runpod/artifact.tar.gz"


@dataclass
class ContainerInfo:
    """Information about a running preview container."""

    id: str  # Docker container ID
    name: str  # Resource name (e.g., "mothership", "gpu_config")
    port: int  # Local port
    is_mothership: bool
    url: str  # Connection URL


def launch_preview(
    build_dir: Path,
    manifest_path: Path,
) -> None:
    """Launch full distributed system preview locally.

    Creates one Docker container per resource config:
    - Mothership (orchestrator)
    - All child endpoints (gpu, cpu, etc.)

    All containers connected via Docker network with inter-container
    communication via Docker DNS.

    Args:
        build_dir: Path to .flash/.build directory
        manifest_path: Path to flash_manifest.json

    Raises:
        typer.Exit: On errors (Docker issues, container startup failures)
    """
    try:
        # Verify prerequisites
        _verify_docker_prerequisites()

        # Load and parse manifest
        manifest = _load_manifest(manifest_path)
        resources = _parse_resources_from_manifest(manifest)

        if not resources:
            console.print("[red]Error:[/red] No resources found in manifest")
            raise typer.Exit(1)

        # Create Docker network
        network_name = _create_docker_network()
        console.print(f"[dim]Docker network: {network_name}[/dim]\n")

        # Build resources_endpoints mapping for cross-endpoint discovery
        resources_endpoints = _build_resources_endpoints(resources)

        # Start containers for each resource
        containers = []
        try:
            for resource_name, resource_config in resources.items():
                container = _start_resource_container(
                    resource_name=resource_name,
                    resource_config=resource_config,
                    build_dir=build_dir,
                    network=network_name,
                    resources_endpoints=resources_endpoints,
                )
                containers.append(container)
        except Exception as e:
            # Cleanup on partial failure
            console.print(f"[red]Error starting containers:[/red] {e}")
            _cleanup_preview(containers, network_name)
            raise typer.Exit(1)

        # Display connection info
        _display_preview_info(containers)

        # Wait for user interrupt
        try:
            _wait_for_shutdown()
        except KeyboardInterrupt:
            console.print("\n[yellow]Shutting down preview...[/yellow]")
        finally:
            # Cleanup
            _cleanup_preview(containers, network_name)
            console.print("[green]✓ Preview stopped[/green]")

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Preview error:[/red] {e}")
        logger.exception("Preview launch failed")
        raise typer.Exit(1)


def _verify_docker_prerequisites() -> None:
    """Verify Docker and Docker daemon are available."""
    # Check Docker command exists
    if not shutil.which("docker"):
        console.print("[red]Error:[/red] Docker is not installed or not in PATH")
        console.print(
            "Install Docker from: https://www.docker.com/products/docker-desktop"
        )
        raise typer.Exit(1)

    # Check Docker daemon is running
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


def _load_manifest(manifest_path: Path) -> dict:
    """Load and parse manifest JSON file.

    Args:
        manifest_path: Path to flash_manifest.json

    Returns:
        Parsed manifest dictionary

    Raises:
        typer.Exit: If manifest not found or invalid
    """
    if not manifest_path.exists():
        console.print(f"[red]Error:[/red] Manifest not found at {manifest_path}")
        raise typer.Exit(1)

    try:
        with open(manifest_path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        console.print(f"[red]Error:[/red] Invalid manifest JSON: {e}")
        raise typer.Exit(1)


def _parse_resources_from_manifest(manifest: dict) -> dict:
    """Parse resource configs from manifest.

    Args:
        manifest: Parsed manifest dictionary

    Returns:
        Dictionary of resource_name -> resource_config
    """
    resources = {}

    # Parse resources from manifest
    manifest_resources = manifest.get("resources", {})
    for resource_name, resource_data in manifest_resources.items():
        resources[resource_name] = {
            "is_mothership": resource_data.get("is_mothership", False),
            "imageName": resource_data.get("imageName", FLASH_CPU_LB_IMAGE),
            "functions": resource_data.get("functions", []),
            "makes_remote_calls": resource_data.get("makes_remote_calls", False),
        }

    # Fallback: If no mothership found in manifest, create default
    has_mothership = any(r.get("is_mothership") for r in resources.values())
    if not has_mothership:
        resources["mothership"] = {
            "is_mothership": True,
            "imageName": FLASH_CPU_LB_IMAGE,
            "makes_remote_calls": False,
        }

    return resources


def _create_docker_network() -> str:
    """Create Docker network for preview containers.

    Returns:
        Docker network name

    Raises:
        typer.Exit: If network creation fails
    """
    network_name = f"flash-preview-{int(time.time())}"

    try:
        subprocess.run(
            ["docker", "network", "create", network_name],
            capture_output=True,
            check=True,
        )
        return network_name
    except subprocess.CalledProcessError as e:
        console.print("[red]Error:[/red] Failed to create Docker network")
        error_detail = e.stderr.decode() if e.stderr else str(e)
        console.print(f"[dim]{error_detail}[/dim]")
        raise typer.Exit(1)


def _start_resource_container(
    resource_name: str,
    resource_config: dict,
    build_dir: Path,
    network: str,
    resources_endpoints: dict,
) -> ContainerInfo:
    """Start a single resource container.

    Args:
        resource_name: Name of resource (e.g., "gpu_config")
        resource_config: Resource configuration dictionary
        build_dir: Path to .flash/.build directory
        network: Docker network name
        resources_endpoints: Mapping of resource names to endpoint URLs

    Returns:
        ContainerInfo with container details

    Raises:
        Exception: If container startup fails
    """
    # Determine Docker image
    # For preview mode, use load-balancer images that expose HTTP /execute endpoints
    # instead of queue-based worker images (which expect test_input.json)
    image = _get_preview_image(resource_config.get("imageName", FLASH_CPU_LB_IMAGE))
    is_mothership = resource_name in ("mothership", "mothership-entrypoint")

    # Assign port
    port = _assign_container_port(resource_name, is_mothership)

    # Container name for Docker network DNS
    container_name = f"flash-preview-{resource_name}"

    # Verify archive exists
    archive_path = build_dir.parent / "artifact.tar.gz"
    if not archive_path.exists():
        raise FileNotFoundError(
            f"Archive not found at {archive_path}. Run 'flash build' first."
        )

    # Build Docker command
    docker_cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        container_name,
        "--network",
        network,
        "-v",
        f"{archive_path}:{CONTAINER_ARCHIVE_PATH}:ro",
        "-v",
        f"{build_dir}:/workspace",
        "-e",
        f"FLASH_RESOURCE_NAME={resource_name}",
        "-e",
        f"RUNPOD_ENDPOINT_ID=preview-{resource_name}",
        "-e",
        f"FLASH_RESOURCES_ENDPOINTS={json.dumps(resources_endpoints)}",
    ]

    # Inject RUNPOD_API_KEY for resources that make remote calls
    makes_remote_calls = resource_config.get("makes_remote_calls", False)
    if makes_remote_calls:
        api_key = os.getenv("RUNPOD_API_KEY")
        if api_key:
            docker_cmd.extend(["-e", f"RUNPOD_API_KEY={api_key}"])
            logger.info(f"{resource_name}: Injected RUNPOD_API_KEY for remote calls")
        else:
            console.print(
                f"[yellow]Warning:[/yellow] {resource_name} makes remote calls but "
                f"RUNPOD_API_KEY is not set. Remote calls will fail."
            )

    docker_cmd.extend(["-p", f"{port}:80"])

    # Use image's default CMD (uvicorn lb_handler:app)
    docker_cmd.append(image)

    # Execute
    try:
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        container_id = result.stdout.strip()

        logger.info(f"Started container {resource_name}: {container_id}")

        # Verify container is actually running (not crashed immediately)
        _verify_container_health(container_id, resource_name)

        return ContainerInfo(
            id=container_id,
            name=resource_name,
            port=port,
            is_mothership=is_mothership,
            url=f"http://localhost:{port}",
        )

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        console.print(f"[red]Error:[/red] Failed to start {resource_name} container")
        console.print(f"[dim]{error_msg}[/dim]")
        raise


def _verify_container_health(container_id: str, resource_name: str) -> None:
    """Verify container is running and didn't crash immediately.

    Args:
        container_id: Docker container ID
        resource_name: Name of resource (for error messages)

    Raises:
        Exception: If container is not running or crashed
    """
    # Wait briefly for container to start and unpack archive
    time.sleep(2)

    # Check container status
    check_result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", container_id],
        capture_output=True,
        text=True,
    )

    status = check_result.stdout.strip()
    if status != "running":
        # Get logs for debugging
        logs_result = subprocess.run(
            ["docker", "logs", container_id],
            capture_output=True,
            text=True,
        )
        error_msg = f"Container {resource_name} failed to start (status: {status})"
        if logs_result.stderr:
            error_msg += f"\n{logs_result.stderr[:500]}"
        if logs_result.stdout:
            error_msg += f"\n{logs_result.stdout[:500]}"
        raise Exception(error_msg)


def _get_preview_image(original_image: str) -> str:
    """Map queue-based worker images to load-balancer images for preview mode.

    Queue-based worker images (flash, flash-cpu) expect job queue inputs and
    test_input.json for validation. For preview mode, we need HTTP endpoints,
    so we use load-balancer images (flash-lb, flash-lb-cpu) instead.

    Args:
        original_image: Image name from manifest (e.g., "runpod/flash:wip")

    Returns:
        Load-balancer image name for preview mode
    """
    # Map queue-based to load-balancer images
    # Format: runpod/flash:tag → runpod/flash-lb:tag
    if "flash-cpu:" in original_image or original_image == FLASH_CPU_IMAGE:
        # CPU queue-based → CPU load-balancer
        return FLASH_CPU_LB_IMAGE
    elif "flash:" in original_image or original_image == FLASH_GPU_IMAGE:
        # GPU queue-based → GPU load-balancer
        return FLASH_LB_IMAGE
    elif "flash-lb" in original_image:
        # Already a load-balancer image
        return original_image
    else:
        # Unknown image, default to CPU LB
        logger.warning(
            f"Unknown image '{original_image}', defaulting to {FLASH_CPU_LB_IMAGE}"
        )
        return FLASH_CPU_LB_IMAGE


def _build_resources_endpoints(resources: dict) -> dict:
    """Build resources_endpoints mapping for preview environment.

    Creates Docker DNS URLs for all resources so containers can
    discover and communicate with each other.

    Args:
        resources: Dictionary of resource_name -> resource_config

    Returns:
        Dictionary mapping resource names to Docker DNS URLs
    """
    resources_endpoints = {}
    for resource_name in resources.keys():
        # Docker DNS URL: http://container-name:80 (internal port)
        container_name = f"flash-preview-{resource_name}"
        resources_endpoints[resource_name] = f"http://{container_name}:80"

    logger.info(f"Built resources_endpoints for preview: {resources_endpoints}")
    return resources_endpoints


def _assign_container_port(resource_name: str, is_mothership: bool) -> int:
    """Assign a local port for the container.

    Mothership uses 8000, workers use 8001+

    Args:
        resource_name: Name of resource
        is_mothership: Whether this is mothership

    Returns:
        Port number to use
    """
    if is_mothership:
        return 8000

    # For workers, assign incrementally: 8001, 8002, etc.
    # Built-in resources have fixed ports in the map; unknown resources are assigned
    # deterministically based on name hash (guaranteed same port for same resource name
    # across runs, but possible collisions if hash values wrap). This simple strategy
    # works well for local preview testing.
    port_map = {
        "gpu_config": 8001,
        "cpu_config": 8002,
    }

    return port_map.get(resource_name, 8001 + (hash(resource_name) % 99))


def _display_preview_info(containers: list[ContainerInfo]) -> None:
    """Display information about running containers.

    Args:
        containers: List of ContainerInfo objects
    """
    table = Table(title="Preview Environment Running", show_header=True)
    table.add_column("Resource", style="cyan")
    table.add_column("Port", style="magenta")
    table.add_column("URL", style="green")
    table.add_column("Type", style="blue")

    # Sort: mothership first, then others
    sorted_containers = sorted(containers, key=lambda c: (not c.is_mothership, c.name))

    for container in sorted_containers:
        container_type = "Mothership" if container.is_mothership else "Worker"
        table.add_row(
            container.name, str(container.port), container.url, container_type
        )

    console.print()
    console.print(table)
    console.print()

    # Display usage instructions
    console.print("[bold]Access your application:[/bold]")
    mothership = next((c for c in containers if c.is_mothership), None)
    if mothership:
        console.print(f"  [dim]Main: {mothership.url}[/dim]")
        console.print(f"  [dim]Health: curl {mothership.url}/ping[/dim]")

    console.print()
    console.print("[bold]Container communication:[/bold]")
    console.print(
        "  [dim]Containers communicate via Docker DNS on internal port 80[/dim]"
    )
    console.print("  [dim]Example: http://flash-preview-gpu_config:80[/dim]")

    console.print()
    console.print("[bold][yellow]Press Ctrl+C to stop and cleanup[/yellow][/bold]")
    console.print()


def _wait_for_shutdown() -> None:
    """Block until user requests shutdown (Ctrl+C)."""
    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        raise


def _cleanup_preview(containers: list[ContainerInfo], network: str) -> None:
    """Stop all containers and remove Docker network.

    Args:
        containers: List of ContainerInfo objects
        network: Docker network name
    """
    # Stop containers
    for container in containers:
        try:
            subprocess.run(
                ["docker", "stop", container.id],
                capture_output=True,
                timeout=10,
            )
            logger.info(f"Stopped container {container.name}")
        except Exception as e:
            logger.warning(f"Failed to stop container {container.name}: {e}")

    # Remove containers
    for container in containers:
        try:
            subprocess.run(
                ["docker", "rm", container.id],
                capture_output=True,
                timeout=10,
            )
            logger.info(f"Removed container {container.name}")
        except Exception as e:
            logger.warning(f"Failed to remove container {container.name}: {e}")

    # Remove network
    try:
        subprocess.run(
            ["docker", "network", "rm", network],
            capture_output=True,
            timeout=10,
        )
        logger.info(f"Removed Docker network {network}")
    except Exception as e:
        logger.warning(f"Failed to remove Docker network: {e}")
