"""Runtime service registry for cross-endpoint function routing."""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

from runpod_flash.core.resources.serverless import ServerlessResource

from .config import DEFAULT_CACHE_TTL
from .state_manager_client import StateManagerClient, ManifestServiceUnavailableError
from .models import Manifest

logger = logging.getLogger(__name__)


class ServiceRegistry:
    """Service discovery and routing for cross-endpoint function calls.

    Loads manifest to map functions to resource configs, queries State Manager
    for endpoint URLs, and determines if function calls are local or remote.
    """

    def __init__(
        self,
        manifest_path: Optional[Path] = None,
        cache_ttl: int = DEFAULT_CACHE_TTL,
    ):
        """Initialize service registry with peer-to-peer State Manager access.

        All endpoints query State Manager directly for manifest updates.
        No central dependency - all endpoints are equal peers.

        Args:
            manifest_path: Path to flash_manifest.json. Defaults to
                FLASH_MANIFEST_PATH env var or auto-detection.
            cache_ttl: Manifest cache lifetime in seconds (default: 300).

        Environment Variables:
            FLASH_RESOURCE_NAME: Resource config name for this endpoint.
                Identifies which resource config this endpoint represents.
            FLASH_ENVIRONMENT_ID: Flash environment ID for State Manager manifest queries.
            RUNPOD_API_KEY: API key for State Manager GraphQL access.

        Raises:
            FileNotFoundError: If manifest_path doesn't exist.
        """
        self.cache_ttl = cache_ttl
        self._endpoint_registry: Dict[str, str] = {}
        self._endpoint_registry_loaded_at = 0.0
        self._manifest: Manifest = Manifest(
            version="1.0",
            generated_at="",
            project_name="",
            function_registry={},
            resources={},
        )
        self._endpoint_registry_lock = asyncio.Lock()

        # Load manifest
        self._load_manifest(manifest_path)

        # Peer-to-peer: All endpoints use StateManagerClient directly
        try:
            self._manifest_client = StateManagerClient()
        except Exception as e:
            logger.warning(f"Failed to initialize State Manager client: {e}")
            self._manifest_client = None

        # Current endpoint identification for local vs remote detection
        self._current_endpoint = os.getenv("FLASH_RESOURCE_NAME") or os.getenv(
            "RUNPOD_ENDPOINT_ID"
        )

        # Determine if this endpoint makes remote calls
        self._makes_remote_calls = self._check_makes_remote_calls(
            self._current_endpoint
        )

    def _load_manifest(self, manifest_path: Optional[Path]) -> None:
        """Load flash_manifest.json.

        Args:
            manifest_path: Explicit path to manifest. Tries env var and
                auto-detection if not provided.

        Raises:
            FileNotFoundError: If manifest not found.
        """
        paths_to_try = []

        # Explicit path
        if manifest_path:
            paths_to_try.append(manifest_path)

        # Environment variable
        env_path = os.getenv("FLASH_MANIFEST_PATH")
        if env_path:
            paths_to_try.append(Path(env_path))

        # Auto-detection: same directory as this file, or cwd
        paths_to_try.extend(
            [
                Path(__file__).parent.parent.parent / "flash_manifest.json",
                Path.cwd() / "flash_manifest.json",
            ]
        )

        # Try each path
        for path in paths_to_try:
            if path and path.exists():
                try:
                    with open(path) as f:
                        manifest_dict = json.load(f)
                    self._manifest = Manifest.from_dict(manifest_dict)
                    logger.debug(f"Manifest loaded from {path}")
                    return
                except Exception as e:
                    logger.warning(f"Failed to load manifest from {path}: {e}")
                    continue

        # No manifest found - log warning but don't fail
        logger.warning(
            "flash_manifest.json not found. Cross-endpoint routing disabled. "
            "Manifest is required for routing functions between endpoints."
        )
        self._manifest = Manifest(
            version="1.0",
            generated_at="",
            project_name="",
            function_registry={},
            resources={},
        )

    def _check_makes_remote_calls(self, resource_name: Optional[str]) -> bool:
        """Check if current resource makes remote calls based on local manifest.

        Args:
            resource_name: Name of the resource config (FLASH_RESOURCE_NAME or RUNPOD_ENDPOINT_ID).

        Returns:
            True if resource makes remote calls, False if local-only,
            True (safe default) if manifest/resource not found.
        """
        if not resource_name or not self._manifest.resources:
            return True  # Safe default - allow remote calls

        resource_config = self._manifest.resources.get(resource_name)
        if not resource_config:
            return True  # Safe default

        return resource_config.makes_remote_calls

    async def _ensure_manifest_loaded(self) -> None:
        """Load manifest from State Manager if cache expired or not loaded.

        Skips State Manager query if this endpoint doesn't make remote calls
        (makes_remote_calls=False in manifest).

        Peer-to-Peer Architecture:
            Each endpoint queries State Manager independently using its own
            FLASH_ENVIRONMENT_ID. All endpoints are equal peers discovering
            each other through the manifest.

        Query Flow:
            1. get_flash_environment(FLASH_ENVIRONMENT_ID) → activeBuildId
            2. get_flash_build(activeBuildId) → manifest
            3. Extract manifest["resources_endpoints"] mapping
            4. Cache for 300s (DEFAULT_CACHE_TTL)

        State Manager Consistency:
            - CLI updates manifest after provisioning all endpoints
            - Endpoints cache manifest to reduce API calls
            - TTL ensures eventual consistency (300s by default)

        Returns:
            None. Updates self._endpoint_registry internally.
        """
        # Skip if endpoint is local-only
        if not self._makes_remote_calls:
            logger.debug(
                "Endpoint does not make remote calls (makes_remote_calls=False), "
                "skipping State Manager query"
            )
            return

        async with self._endpoint_registry_lock:
            now = time.time()
            cache_age = now - self._endpoint_registry_loaded_at

            if cache_age > self.cache_ttl:
                if self._manifest_client is None:
                    logger.debug("State Manager client not available, skipping refresh")
                    return

                try:
                    flash_env_id = os.getenv("FLASH_ENVIRONMENT_ID")
                    if not flash_env_id:
                        logger.debug(
                            "FLASH_ENVIRONMENT_ID not set, skipping State Manager query"
                        )
                        return

                    # Query State Manager directly for full manifest
                    full_manifest = await self._manifest_client.get_persisted_manifest(
                        flash_env_id
                    )

                    # Extract resources_endpoints mapping
                    resources_endpoints = full_manifest.get("resources_endpoints", {})

                    self._endpoint_registry = resources_endpoints
                    self._endpoint_registry_loaded_at = now
                    logger.debug(
                        f"Manifest loaded from State Manager: {len(self._endpoint_registry)} endpoints, "
                        f"cache TTL {self.cache_ttl}s"
                    )
                except ManifestServiceUnavailableError as e:
                    logger.warning(
                        f"Failed to load manifest from State Manager: {e}. "
                        f"Cross-endpoint routing unavailable."
                    )
                    self._endpoint_registry = {}

    async def get_endpoint_for_function(self, function_name: str) -> Optional[str]:
        """Get endpoint URL for a function.

        Determines if function is local (same endpoint) or remote (different
        endpoint), returning None for local and URL for remote.

        Queries State Manager if endpoint registry cache is expired.

        Args:
            function_name: Name of the function to route.

        Returns:
            Endpoint URL if function is remote, None if local.

        Raises:
            ValueError: If function not in manifest.
        """
        # Ensure manifest is loaded from State Manager (with caching)
        await self._ensure_manifest_loaded()

        function_registry = self._manifest.function_registry

        if function_name not in function_registry:
            raise ValueError(
                f"Function '{function_name}' not found in manifest. "
                f"Available functions: {list(function_registry.keys())}"
            )

        resource_config_name = function_registry[function_name]

        # Check if this is the current endpoint (local)
        if resource_config_name == self._current_endpoint:
            return None

        # Check manifest for remote endpoint URL
        endpoint_url = self._endpoint_registry.get(resource_config_name)
        if not endpoint_url:
            logger.debug(
                f"Endpoint URL for '{resource_config_name}' not in manifest. "
                f"Manifest has: {list(self._endpoint_registry.keys())}"
            )

        return endpoint_url

    async def get_resource_for_function(
        self, function_name: str
    ) -> Optional[ServerlessResource]:
        """Get ServerlessResource for a function.

        Creates a ServerlessResource with the correct endpoint ID if the function
        is remote, returns None if local.

        Args:
            function_name: Name of the function to route.

        Returns:
            ServerlessResource with ID set if function is remote
            None if function runs on current endpoint

        Raises:
            ValueError: If function not in manifest.
        """
        endpoint_url = await self.get_endpoint_for_function(function_name)

        if endpoint_url is None:
            return None  # Local function

        # Extract endpoint ID from URL (format: https://{endpoint_base_url}/v2/{endpoint_id})
        try:
            parsed = urlparse(endpoint_url)
            # Get the last path component (the endpoint ID)
            path_parts = parsed.path.rstrip("/").split("/")
            endpoint_id = path_parts[-1] if path_parts else ""

            if not endpoint_id:
                raise ValueError(
                    f"Invalid endpoint URL format: {endpoint_url} - no endpoint ID found"
                )
        except Exception as e:
            raise ValueError(
                f"Failed to parse endpoint URL '{endpoint_url}': {e}"
            ) from e

        # Create and return ServerlessResource
        resource = ServerlessResource(name=f"remote_{function_name}")
        resource.id = endpoint_id

        return resource

    async def get_routing_info(self, function_name: str) -> Optional[dict]:
        """Get complete routing metadata for a remote function.

        Combines endpoint URL lookup with resource type and per-function route
        metadata from the manifest. Used by ProductionWrapper to determine
        QB vs LB dispatch strategy.

        Args:
            function_name: Name of the function to route.

        Returns:
            None if function is local. For remote functions returns:
            {
                "resource_name": str,
                "endpoint_url": str,
                "is_load_balanced": bool,
                "http_method": Optional[str],  # LB only
                "http_path": Optional[str],     # LB only
            }

        Raises:
            ValueError: If function not in manifest.
        """
        await self._ensure_manifest_loaded()

        function_registry = self._manifest.function_registry

        if function_name not in function_registry:
            raise ValueError(
                f"Function '{function_name}' not found in manifest. "
                f"Available functions: {list(function_registry.keys())}"
            )

        resource_config_name = function_registry[function_name]

        # Local function
        if resource_config_name == self._current_endpoint:
            return None

        endpoint_url = self._endpoint_registry.get(resource_config_name)
        if not endpoint_url:
            logger.debug(
                f"Endpoint URL for '{resource_config_name}' not in registry. "
                f"Manifest has: {list(self._endpoint_registry.keys())}"
            )

        resource_config = self._manifest.resources.get(resource_config_name)
        is_load_balanced = (
            resource_config.is_load_balanced if resource_config else False
        )

        # Find per-function route metadata (http_method, http_path) for LB targets
        http_method = None
        http_path = None
        if resource_config and is_load_balanced:
            for func_meta in resource_config.functions:
                if func_meta.name == function_name:
                    http_method = func_meta.http_method
                    http_path = func_meta.http_path
                    break

        return {
            "resource_name": resource_config_name,
            "endpoint_url": endpoint_url,
            "is_load_balanced": is_load_balanced,
            "http_method": http_method,
            "http_path": http_path,
        }

    async def is_local_function(self, function_name: str) -> bool:
        """Check if function executes on current endpoint.

        Args:
            function_name: Name of the function.

        Returns:
            True if function is local, False if remote or not found.
        """
        try:
            endpoint_url = await self.get_endpoint_for_function(function_name)
            return endpoint_url is None
        except ValueError:
            # Function not in manifest, assume local (will execute and fail)
            return True

    def get_current_endpoint_id(self) -> Optional[str]:
        """Get ID of current endpoint from environment.

        Returns:
            Endpoint ID from FLASH_RESOURCE_NAME or RUNPOD_ENDPOINT_ID, or None if not set.
        """
        return self._current_endpoint

    def refresh_manifest(self) -> None:
        """Force refresh manifest from State Manager on next access."""
        self._endpoint_registry_loaded_at = 0

    def get_manifest(self) -> Manifest:
        """Get loaded manifest.

        Returns:
            Loaded Manifest object.
        """
        return self._manifest

    def get_all_resources(self) -> Dict[str, Dict]:
        """Get all resource configs from manifest.

        Returns:
            Dictionary of resource configs as dictionaries.
        """
        from dataclasses import asdict

        return {
            name: asdict(config) for name, config in self._manifest.resources.items()
        }

    def get_resource_functions(self, resource_name: str) -> list:
        """Get list of functions for a resource.

        Args:
            resource_name: Name of the resource config.

        Returns:
            List of function metadata dictionaries.
        """
        resource = self._manifest.resources.get(resource_name)
        if not resource:
            return []
        from dataclasses import asdict

        return [asdict(func) for func in resource.functions]
