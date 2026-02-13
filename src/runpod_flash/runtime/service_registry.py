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

    Loads manifest to map functions to resource configs, queries mothership
    manifest for endpoint URLs, and determines if function calls are local
    or remote.
    """

    def __init__(
        self,
        manifest_path: Optional[Path] = None,
        cache_ttl: int = DEFAULT_CACHE_TTL,
    ):
        """Initialize service registry with peer-to-peer State Manager access.

        All endpoints query State Manager directly for manifest updates.
        No Mothership dependency - all endpoints are equal peers.

        Args:
            manifest_path: Path to flash_manifest.json. Defaults to
                FLASH_MANIFEST_PATH env var or auto-detection.
            cache_ttl: Manifest cache lifetime in seconds (default: 300).

        Environment Variables:
            FLASH_RESOURCE_NAME: Resource config name for this endpoint.
                Identifies which resource config this endpoint represents.
            RUNPOD_ENDPOINT_ID: Endpoint ID (used for State Manager queries and fallback).
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

        # Check for preview mode resources_endpoints from environment
        self._load_preview_endpoints()

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

    def _load_preview_endpoints(self) -> None:
        """Load resources_endpoints from environment for preview mode.

        In preview mode, the CLI passes resources_endpoints as a JSON-encoded
        environment variable. This allows containers to discover each other
        via Docker DNS without State Manager queries.
        """
        preview_endpoints_json = os.getenv("FLASH_RESOURCES_ENDPOINTS")
        if preview_endpoints_json:
            try:
                self._endpoint_registry = json.loads(preview_endpoints_json)
                self._endpoint_registry_loaded_at = time.time()
                logger.info(
                    f"Loaded {len(self._endpoint_registry)} endpoints from preview environment"
                )
            except json.JSONDecodeError as e:
                logger.warning(
                    f"Failed to parse FLASH_RESOURCES_ENDPOINTS environment variable: {e}"
                )

    def _check_makes_remote_calls(self, resource_name: Optional[str]) -> bool:
        """Check if current resource makes remote calls based on local manifest.

        Args:
            resource_name: Name of the resource config (FLASH_RESOURCE_NAME or RUNPOD_ENDPOINT_ID).

        Returns:
            True if resource makes remote calls, False if local-only,
            True (safe default) if manifest/resource not found or makes_remote_calls is null.
        """
        if not resource_name or not self._manifest.resources:
            return True  # Safe default - allow remote calls

        resource_config = self._manifest.resources.get(resource_name)
        if not resource_config:
            return True  # Safe default

        makes_remote_calls = resource_config.makes_remote_calls

        # Handle null/None as True (safe default - allow remote calls)
        if makes_remote_calls is None:
            return True

        return makes_remote_calls

    async def _ensure_manifest_loaded(self) -> None:
        """Load manifest from State Manager if cache expired or not loaded.

        Skips State Manager query if this endpoint doesn't make remote calls
        (makes_remote_calls=False in manifest).

        Peer-to-Peer Architecture:
            Each endpoint queries State Manager independently using its own
            RUNPOD_ENDPOINT_ID. No mothership dependency - all endpoints
            are equal peers discovering each other through the manifest.

        Query Flow:
            1. get_flash_environment(RUNPOD_ENDPOINT_ID) → activeBuildId
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
                    # Get API key from request context (set by middleware)
                    from .api_key_context import get_api_key

                    api_key = get_api_key()

                    # Use FLASH_ENVIRONMENT_ID (set during deployment) to query State Manager
                    # Fallback to RUNPOD_ENDPOINT_ID for backwards compatibility
                    environment_id = os.getenv("FLASH_ENVIRONMENT_ID") or os.getenv(
                        "RUNPOD_ENDPOINT_ID"
                    )
                    if not environment_id:
                        logger.warning(
                            "FLASH_ENVIRONMENT_ID not set, cannot query State Manager"
                        )
                        return

                    # Query State Manager directly for full manifest
                    # Pass API key explicitly to ensure it's available even if contextvars isn't propagated
                    full_manifest = await self._manifest_client.get_persisted_manifest(
                        environment_id, api_key=api_key
                    )

                    # Log what State Manager returned for troubleshooting
                    logger.info(
                        f"State Manager returned manifest with keys: {list(full_manifest.keys())}"
                    )

                    # Extract resources_endpoints mapping
                    resources_endpoints = full_manifest.get("resources_endpoints", {})

                    if not resources_endpoints:
                        logger.error(
                            f"State Manager returned empty resources_endpoints for environment {environment_id}!"
                        )
                    else:
                        logger.info(
                            f"State Manager provided {len(resources_endpoints)} endpoints"
                        )

                    self._endpoint_registry = resources_endpoints
                    self._endpoint_registry_loaded_at = now
                    logger.debug(
                        f"Manifest loaded from State Manager: {len(self._endpoint_registry)} endpoints, "
                        f"cache TTL {self.cache_ttl}s"
                    )
                except (ManifestServiceUnavailableError, Exception) as e:
                    logger.debug(
                        f"State Manager unavailable ({type(e).__name__}), "
                        f"using local manifest for cross-endpoint routing"
                    )
                    # Fall back to local manifest's resources_endpoints if available
                    if self._manifest and self._manifest.resources_endpoints:
                        self._endpoint_registry = self._manifest.resources_endpoints
                        logger.debug(
                            f"Loaded {len(self._endpoint_registry)} endpoints from local manifest"
                        )
                    else:
                        self._endpoint_registry = {}
                        logger.debug("No resources_endpoints in local manifest")

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

        Creates a LoadBalancerSlsResource with the correct endpoint ID if the function
        is remote, returns None if local.

        For remote functions, this creates a LoadBalancerSlsResource configured to connect
        to an existing endpoint (not deploy a new one). This enables the stub logic to
        make HTTP calls to user-defined routes instead of using the /execute endpoint.

        Args:
            function_name: Name of the function to route.

        Returns:
            LoadBalancerSlsResource with ID set if function is remote
            None if function runs on current endpoint

        Raises:
            ValueError: If function not in manifest.
        """
        endpoint_url = await self.get_endpoint_for_function(function_name)

        if endpoint_url is None:
            return None  # Local function

        # Get resource name and config from manifest
        await self._ensure_manifest_loaded()
        resource_name = self._manifest.function_registry.get(function_name)
        resource_config = (
            self._manifest.resources.get(resource_name) if resource_name else None
        )

        # Extract endpoint ID from URL
        # Supports formats:
        # - Queue-based: https://{domain}/v2/{endpoint_id}
        # - Load-balanced: https://{endpoint_id}.{domain}
        # - Preview/Docker: http://{container-name} (use container name as ID)
        try:
            parsed = urlparse(endpoint_url)

            # Check for queue-based format first (path contains /v2/{endpoint_id})
            if parsed.path and "/v2/" in parsed.path:
                path_parts = parsed.path.rstrip("/").split("/")
                endpoint_id = path_parts[-1] if path_parts else ""
            # Load-balanced format (hostname starts with endpoint ID, has subdomain)
            elif parsed.hostname and parsed.hostname.count(".") >= 2:
                endpoint_id = parsed.hostname.split(".")[0]
            # Preview/Docker format (hostname is container name, no dots or single dot for localhost)
            elif parsed.hostname:
                endpoint_id = parsed.hostname.replace("flash-preview-", "")
                logger.debug(
                    f"Using hostname as endpoint ID for preview mode: {endpoint_id}"
                )
            else:
                endpoint_id = ""

            if not endpoint_id:
                logger.warning(
                    f"Could not extract endpoint ID from URL: {endpoint_url}"
                )
                return None
        except Exception as e:
            logger.warning(f"Failed to parse endpoint URL '{endpoint_url}': {e}")
            return None

        # Create appropriate resource type based on manifest
        # Queue-based workers (LiveServerless) need direct URLs for preview mode
        # Load-balanced endpoints use LoadBalancerSlsResource
        resource_type = (
            resource_config.resource_type
            if resource_config
            else "LoadBalancerSlsResource"
        )

        logger.debug(
            f"Function '{function_name}' is remote (resource: {resource_name}, type: {resource_type}, id: {endpoint_id}, url: {endpoint_url})"
        )

        # For preview mode, use LoadBalancerSlsResource for all types
        # since containers expose HTTP endpoints regardless of deployment type
        from runpod_flash.core.resources.load_balancer_sls_resource import (
            LoadBalancerSlsResource,
        )

        # Create resource config with endpoint URL for preview mode
        # Note: In preview, all containers have HTTP endpoints at :80
        resource = LoadBalancerSlsResource(
            name=resource_name or f"remote_{function_name}",
            id=endpoint_id,
            flashboot=False,
            custom_endpoint_url=endpoint_url,  # Use preview Docker DNS URL
        )

        return resource

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
        """Force refresh manifest from mothership on next access."""
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
