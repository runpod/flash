"""Background deployment orchestrator with progress tracking."""

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from .exceptions import RunpodAPIKeyError
from .resources.base import DeployableResource
from .resources.resource_manager import ResourceManager
from .validation import validate_api_key

log = logging.getLogger(__name__)
console = Console()


class DeploymentStatus(Enum):
    """Status of a resource deployment."""

    PENDING = "pending"
    CHECKING = "checking"
    CACHED = "cached"
    DEPLOYING = "deploying"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class DeploymentResult:
    """Result of a resource deployment operation."""

    resource: DeployableResource
    status: DeploymentStatus
    duration: float
    error: str = ""
    endpoint_id: str = ""


class DeploymentOrchestrator:
    """Orchestrates parallel resource deployment with progress tracking."""

    def __init__(self, max_concurrent: int = 3):
        """Initialize deployment orchestrator.

        Args:
            max_concurrent: Maximum number of concurrent deployments
        """
        self.max_concurrent = max_concurrent
        self.manager = ResourceManager()
        self.results: List[DeploymentResult] = []

    def deploy_all_background(self, resources: List[DeployableResource]) -> None:
        """Deploy all resources in background thread.

        This method spawns a background thread to deploy resources without
        blocking the main thread. Progress is logged to console.

        Args:
            resources: List of resources to deploy
        """
        if not resources:
            console.print("[dim]No resources to deploy[/dim]")
            return

        def run_async_deployment():
            """Run async deployment in background thread."""
            try:
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                # Run deployment silently in background
                loop.run_until_complete(self.deploy_all(resources, show_progress=False))

            except Exception as e:
                log.error(f"Background deployment failed: {e}")
            finally:
                loop.close()

        # Start background thread
        thread = threading.Thread(target=run_async_deployment, daemon=True)
        thread.start()

        console.print(
            f"[dim]Auto-provisioning {len(resources)} resource(s) in background...[/dim]"
        )

    async def deploy_all(
        self, resources: List[DeployableResource], show_progress: bool = True
    ) -> List[DeploymentResult]:
        """Deploy all resources in parallel with progress tracking.

        Args:
            resources: List of resources to deploy
            show_progress: Whether to show progress indicator and summary (default: True)

        Returns:
            List of deployment results
        """
        if not resources:
            return []

        # Fail fast if no API key, before spawning parallel tasks
        validate_api_key()

        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(self.max_concurrent)

        # Create deployment tasks
        deploy_tasks = [
            self._deploy_with_semaphore(resource, semaphore) for resource in resources
        ]

        # Deploy with progress indication
        if show_progress:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task_id = progress.add_task(
                    f"Provisioning {len(resources)} resource(s)...",
                    total=None,
                )

                # Wait for all deployments
                self.results = await asyncio.gather(
                    *deploy_tasks, return_exceptions=False
                )

                progress.update(
                    task_id,
                    description=f"[green]✓ Provisioned {len(resources)} resource(s)",
                )
                progress.stop_task(task_id)

            # Display summary
            self._display_summary()
        else:
            # Silent deployment for background provisioning
            self.results = await asyncio.gather(*deploy_tasks, return_exceptions=False)

        return self.results

    async def _deploy_with_semaphore(
        self, resource: DeployableResource, semaphore: asyncio.Semaphore
    ) -> DeploymentResult:
        """Deploy single resource with semaphore control.

        Args:
            resource: Resource to deploy
            semaphore: Semaphore for concurrency limiting

        Returns:
            Deployment result
        """
        start_time = datetime.now()
        resource_name = getattr(resource, "name", "Unknown")

        async with semaphore:
            try:
                # Quick check if already deployed
                if await resource.is_deployed():
                    duration = (datetime.now() - start_time).total_seconds()
                    return DeploymentResult(
                        resource=resource,
                        status=DeploymentStatus.CACHED,
                        duration=duration,
                        endpoint_id=getattr(resource, "id", "N/A"),
                    )

                # Deploy resource
                deployed = await self.manager.get_or_deploy_resource(resource)
                duration = (datetime.now() - start_time).total_seconds()

                return DeploymentResult(
                    resource=deployed,
                    status=DeploymentStatus.SUCCESS,
                    duration=duration,
                    endpoint_id=getattr(deployed, "id", "N/A"),
                )

            except RunpodAPIKeyError:
                raise
            except Exception as e:
                duration = (datetime.now() - start_time).total_seconds()
                log.error(f"Failed to deploy {resource_name}: {e}")

                return DeploymentResult(
                    resource=resource,
                    status=DeploymentStatus.FAILED,
                    duration=duration,
                    error=str(e),
                )

    def _display_summary(self):
        """Display deployment summary."""
        if not self.results:
            return

        # Count statuses
        cached = sum(1 for r in self.results if r.status == DeploymentStatus.CACHED)
        deployed = sum(1 for r in self.results if r.status == DeploymentStatus.SUCCESS)
        failed = sum(1 for r in self.results if r.status == DeploymentStatus.FAILED)
        total_time = sum(r.duration for r in self.results)

        # Build summary message
        parts = []
        if cached > 0:
            parts.append(f"{cached} cached")
        if deployed > 0:
            parts.append(f"{deployed} deployed")
        if failed > 0:
            parts.append(f"{failed} failed")

        status_text = ", ".join(parts)

        console.print()
        if failed > 0:
            console.print(
                f"[yellow]⚠[/yellow] Provisioning completed: {len(self.results)} resources "
                f"({status_text}) in {total_time:.1f}s"
            )
            console.print(
                "[yellow]Note:[/yellow] Failed resources will deploy on-demand when first called"
            )
        else:
            console.print(
                f"[green]✓[/green] Provisioning completed: {len(self.results)} resources "
                f"({status_text}) in {total_time:.1f}s"
            )

        console.print()
