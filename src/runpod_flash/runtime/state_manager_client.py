"""GraphQL client for State Manager API to persist and reconcile manifests."""

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from runpod_flash.core.api.runpod import RunpodGraphQLClient

from .config import DEFAULT_MAX_RETRIES
from .exceptions import GraphQLError, ManifestServiceUnavailableError

logger = logging.getLogger(__name__)


class StateManagerClient:
    """GraphQL client for State Manager manifest persistence.

    The State Manager persists manifest state via RunPod GraphQL API,
    providing reconciliation capabilities for the mothership to track
    deployed resources across boots.

    Thread Safety:
        Uses asyncio.Lock to serialize read-modify-write operations,
        preventing race conditions during concurrent resource updates.

    Architecture:
        Manifest updates follow a read-modify-write pattern:
        1. Fetch environment -> activeBuildId
        2. Fetch build -> manifest
        3. Merge changes into manifest
        4. Call updateFlashBuildManifest mutation

    Performance:
        Each update requires 3 GraphQL roundtrips. Consider batching
        updates when provisioning multiple resources.
    """

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        """Initialize State Manager client.

        Args:
            max_retries: Maximum retry attempts for operations.

        Raises:
            RunpodAPIKeyError: If RUNPOD_API_KEY environment variable is not set (raised by RunpodGraphQLClient).
        """
        self.max_retries = max_retries
        self._manifest_lock = asyncio.Lock()

    async def get_persisted_manifest(
        self, mothership_id: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch persisted manifest from State Manager.

        Args:
            mothership_id: ID of the mothership endpoint.

        Returns:
            Manifest dict.

        Raises:
            ManifestServiceUnavailableError: If State Manager unavailable after retries.
        """
        last_exception: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                async with RunpodGraphQLClient() as client:
                    _, manifest = await self._fetch_build_and_manifest(
                        client, mothership_id
                    )

                # Log what we're returning to understand State Manager response
                logger.info(
                    f"get_persisted_manifest returning manifest with keys: "
                    f"{list(manifest.keys())}"
                )
                if "resources_endpoints" in manifest:
                    logger.info(
                        f"Manifest contains resources_endpoints with "
                        f"{len(manifest['resources_endpoints'])} entries"
                    )
                else:
                    logger.warning(
                        f"Manifest missing resources_endpoints field! "
                        f"Full manifest structure: {json.dumps(manifest, indent=2)}"
                    )

                logger.debug(f"Persisted manifest loaded for {mothership_id}")
                return manifest

            except (
                asyncio.TimeoutError,
                ManifestServiceUnavailableError,
                GraphQLError,
                ConnectionError,
            ) as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    backoff = 2**attempt
                    logger.warning(
                        f"State Manager request failed (attempt {attempt + 1}): {e}, "
                        f"retrying in {backoff}s..."
                    )
                    await asyncio.sleep(backoff)
                    continue

        raise ManifestServiceUnavailableError(
            f"Failed to fetch persisted manifest after {self.max_retries} attempts: "
            f"{last_exception}"
        )

    async def update_resource_state(
        self,
        mothership_id: str,
        resource_name: str,
        resource_data: Dict[str, Any],
    ) -> None:
        """Update single resource entry in State Manager.

        Uses locking to prevent race conditions when multiple resources
        are deployed concurrently.

        Args:
            mothership_id: ID of the mothership endpoint.
            resource_name: Name of the resource.
            resource_data: Resource metadata (config_hash, endpoint_url, status, etc).

        Raises:
            ManifestServiceUnavailableError: If State Manager unavailable.
        """
        last_exception: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                async with self._manifest_lock:
                    async with RunpodGraphQLClient() as client:
                        build_id, manifest = await self._fetch_build_and_manifest(
                            client, mothership_id
                        )
                        resources = manifest.setdefault("resources", {})
                        existing = resources.get(resource_name)
                        if not isinstance(existing, dict):
                            existing = {}
                        resources[resource_name] = {**existing, **resource_data}
                        await client.update_build_manifest(build_id, manifest)

                logger.debug(
                    f"Updated resource state in State Manager: {mothership_id}/{resource_name}"
                )
                return

            except (
                asyncio.TimeoutError,
                ManifestServiceUnavailableError,
                GraphQLError,
                ConnectionError,
            ) as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    backoff = 2**attempt
                    logger.warning(
                        f"State Manager request failed (attempt {attempt + 1}): {e}, "
                        f"retrying in {backoff}s..."
                    )
                    await asyncio.sleep(backoff)
                    continue

        raise ManifestServiceUnavailableError(
            f"Failed to update resource state after {self.max_retries} attempts: "
            f"{last_exception}"
        )

    async def remove_resource_state(
        self, mothership_id: str, resource_name: str
    ) -> None:
        """Remove resource entry from State Manager.

        Uses locking to prevent race conditions when multiple resources
        are deployed concurrently.

        Args:
            mothership_id: ID of the mothership endpoint.
            resource_name: Name of the resource.

        Raises:
            ManifestServiceUnavailableError: If State Manager unavailable.
        """
        last_exception: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                async with self._manifest_lock:
                    async with RunpodGraphQLClient() as client:
                        build_id, manifest = await self._fetch_build_and_manifest(
                            client, mothership_id
                        )
                        resources = manifest.setdefault("resources", {})
                        resources.pop(resource_name, None)
                        await client.update_build_manifest(build_id, manifest)

                logger.debug(
                    f"Removed resource state from State Manager: {mothership_id}/{resource_name}"
                )
                return

            except (
                asyncio.TimeoutError,
                ManifestServiceUnavailableError,
                GraphQLError,
                ConnectionError,
            ) as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    backoff = 2**attempt
                    logger.warning(
                        f"State Manager request failed (attempt {attempt + 1}): {e}, "
                        f"retrying in {backoff}s..."
                    )
                    await asyncio.sleep(backoff)
                    continue

        raise ManifestServiceUnavailableError(
            f"Failed to remove resource state after {self.max_retries} attempts: "
            f"{last_exception}"
        )

    async def _fetch_build_and_manifest(
        self, client: RunpodGraphQLClient, mothership_id: str
    ) -> tuple[str, Dict[str, Any]]:
        """Fetch active build ID and manifest for an environment.

        Args:
            client: Authenticated GraphQL client.
            mothership_id: Flash environment ID.

        Returns:
            Tuple of (build_id, manifest_dict).

        Raises:
            ManifestServiceUnavailableError: If environment, build, or manifest not found.
        """
        environment = await client.get_flash_environment(
            {"flashEnvironmentId": mothership_id}
        )
        build_id = environment.get("activeBuildId")
        if not build_id:
            raise ManifestServiceUnavailableError(
                f"Active build not found for environment {mothership_id}. "
                f"Environment may not be fully initialized or has no deployed build."
            )

        build = await client.get_flash_build(build_id)
        manifest = build.get("manifest")
        if not manifest:
            raise ManifestServiceUnavailableError(
                f"Manifest not found for build {build.get('id', build_id)}. "
                f"Build may be corrupted, not yet published, or manifest was not generated."
            )

        return build_id, manifest
