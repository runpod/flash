import asyncio
from contextlib import asynccontextmanager
import cloudpickle
import logging
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

from ..exceptions import RunpodAPIKeyError
from ..utils.singleton import SingletonMixin
from ..utils.file_lock import file_lock, FileLockError

from .base import DeployableResource


log = logging.getLogger(__name__)

# Directory and file to persist state of resources
RUNPOD_FLASH_DIR = Path(".runpod")
RESOURCE_STATE_FILE = RUNPOD_FLASH_DIR / "resources.pkl"


class ResourceManager(SingletonMixin):
    """Manages dynamic provisioning and tracking of remote resources."""

    # Class variables shared across all instances (singleton)
    _resources: Dict[str, DeployableResource] = {}
    _resource_configs: Dict[str, str] = {}  # Tracks config hashes for drift detection
    _deployment_locks: Dict[str, asyncio.Lock] = {}
    _global_lock: Optional[asyncio.Lock] = None
    _lock_initialized = False
    _resources_initialized = False

    def __init__(self):
        # Ensure async locks are initialized properly for the singleton instance
        if not ResourceManager._lock_initialized:
            ResourceManager._global_lock = asyncio.Lock()
            ResourceManager._lock_initialized = True

        # Load resources immediately on initialization (only once)
        if not ResourceManager._resources_initialized:
            self._load_resources()
            self._migrate_to_name_based_keys()  # Auto-migrate legacy resources
            self._refresh_config_hashes()  # Refresh config hashes after code changes
            ResourceManager._resources_initialized = True

    def _load_resources(self) -> Dict[str, DeployableResource]:
        """Load persisted resource information using cross-platform file locking."""
        if RESOURCE_STATE_FILE.exists():
            try:
                with open(RESOURCE_STATE_FILE, "rb") as f:
                    # Acquire shared lock for reading (cross-platform)
                    with file_lock(f, exclusive=False):
                        data = cloudpickle.load(f)

                        # Handle both old (dict) and new (tuple) pickle formats
                        if isinstance(data, tuple) and len(data) == 2:
                            self._resources, self._resource_configs = data
                        else:
                            # Legacy format: just resources dict
                            self._resources = data
                            self._resource_configs = {}

                        log.debug(
                            f"Loaded {len(self._resources)} saved resources from {RESOURCE_STATE_FILE}:\n"
                            f"  Keys: {list(self._resources.keys())}"
                        )
            except (FileLockError, Exception) as e:
                log.error(f"Failed to load resources from {RESOURCE_STATE_FILE}: {e}")
        return self._resources

    def _migrate_to_name_based_keys(self) -> None:
        """Migrate from hash-based keys to name-based keys.

        Legacy format: {resource_id_hash: resource}
        New format: {ResourceType:name: resource}

        This enables config drift detection and updates.
        """
        migrated = {}
        migrated_configs = {}

        for key, resource in self._resources.items():
            # Check if already using name-based key format
            if ":" in key and not key.startswith(resource.__class__.__name__ + "_"):
                # Already migrated
                migrated[key] = resource
                migrated_configs[key] = self._resource_configs.get(
                    key, resource.config_hash
                )
                continue

            # Legacy hash-based key - migrate to name-based
            if hasattr(resource, "get_resource_key"):
                new_key = resource.get_resource_key()
                migrated[new_key] = resource
                migrated_configs[new_key] = resource.config_hash
                log.debug(f"Migrated resource: {key} → {new_key}")
            else:
                # Fallback: keep original key if no name available
                migrated[key] = resource
                migrated_configs[key] = self._resource_configs.get(key, "")

        if len(migrated) != len(self._resources):
            log.debug(f"Migrated {len(self._resources)} resources to name-based keys")
            self._resources = migrated
            self._resource_configs = migrated_configs
            self._save_resources()  # Persist migration

    def _refresh_config_hashes(self) -> None:
        """Refresh stored config hashes to match current code.

        This is needed when code changes affect how config_hash is computed
        (e.g., adding field_serializers, changing _input_only sets).

        Compares stored hash with freshly computed hash. If they differ,
        updates the stored hash to prevent false drift detection.
        """
        updated = False

        for key, resource in self._resources.items():
            if not hasattr(resource, "config_hash"):
                continue

            # Compute fresh hash with current code
            fresh_hash = resource.config_hash
            stored_hash = self._resource_configs.get(key, "")

            # If hashes differ, update stored hash
            if stored_hash != fresh_hash:
                log.debug(
                    f"Refreshing config hash for '{key}': "
                    f"{stored_hash[:8]}... → {fresh_hash[:8]}..."
                )
                self._resource_configs[key] = fresh_hash
                updated = True

        # Save if any hashes were updated
        if updated:
            log.debug("Refreshed config hashes after code changes")
            self._save_resources()

    def _save_resources(self) -> None:
        """Persist state of resources to disk using cross-platform file locking."""
        try:
            # Ensure directory exists
            RUNPOD_FLASH_DIR.mkdir(parents=True, exist_ok=True)

            with open(RESOURCE_STATE_FILE, "wb") as f:
                # Acquire exclusive lock for writing (cross-platform)
                with file_lock(f, exclusive=True):
                    # Save both resources and config hashes as tuple
                    data = (self._resources, self._resource_configs)
                    cloudpickle.dump(data, f)
                    f.flush()  # Ensure data is written to disk
                    log.debug(f"Saved resources in {RESOURCE_STATE_FILE}")
        except (FileLockError, Exception) as e:
            log.error(f"Failed to save resources to {RESOURCE_STATE_FILE}: {e}")
            raise

    def _add_resource(self, uid: str, resource: DeployableResource):
        """Add a resource to the manager (protected method for internal use)."""
        self._resources[uid] = resource
        self._resource_configs[uid] = resource.config_hash
        self._save_resources()

    def _remove_resource(self, uid: str):
        """Remove a resource from the manager (protected method for internal use)."""
        if uid not in self._resources:
            log.warning(f"Resource {uid} not found for removal")
            return

        del self._resources[uid]
        self._resource_configs.pop(uid, None)  # Remove config hash too
        log.debug(f"Removed resource {uid}")

        self._save_resources()

    async def register_resource(self, resource: DeployableResource) -> str:
        """Persist a resource config into pickled state. Not thread safe."""
        uid = resource.resource_id
        self._add_resource(uid, resource)
        return uid

    async def _deploy_with_error_context(
        self, config: DeployableResource
    ) -> DeployableResource:
        """Deploy resource with enhanced error context for RunpodAPIKeyError.

        Args:
            config: Resource configuration to deploy.

        Returns:
            Deployed resource instance.

        Raises:
            RunpodAPIKeyError: If deployment fails due to missing API key, with resource context.
        """
        try:
            return await config._do_deploy()
        except RunpodAPIKeyError as e:
            error_msg = f"Cannot deploy resource '{config.name}': {str(e)}"
            raise RunpodAPIKeyError(error_msg) from e

    async def get_resource_from_store(self, uid: str):
        return self._resources.get(uid)

    async def get_or_deploy_resource(
        self, config: DeployableResource
    ) -> DeployableResource:
        """Get existing, update if config changed, or deploy new resource.

        Uses name-based identity (ResourceType:name) instead of config hash.
        This enables automatic config drift detection and updates.

        Flow:
        1. Check if resource with same name exists
        2. If exists, compare config hashes
        3. If config changed, automatically update the endpoint
        4. If no resource exists, deploy new one

        Thread-safe implementation that prevents concurrent deployments.
        """
        # Use name-based key instead of hash
        resource_key = config.get_resource_key()
        new_config_hash = config.config_hash

        # Ensure global lock is initialized
        assert ResourceManager._global_lock is not None, "Global lock not initialized"

        # Get or create a per-resource lock (use name-based key)
        async with ResourceManager._global_lock:
            if resource_key not in ResourceManager._deployment_locks:
                ResourceManager._deployment_locks[resource_key] = asyncio.Lock()
            resource_lock = ResourceManager._deployment_locks[resource_key]

        # Acquire per-resource lock
        async with resource_lock:
            existing = self._resources.get(resource_key)

            if existing:
                # Resource exists - check if still valid
                if not existing.is_deployed():
                    log.warning(f"{existing} is no longer valid, redeploying.")
                    self._remove_resource(resource_key)
                    try:
                        deployed_resource = await self._deploy_with_error_context(
                            config
                        )
                        log.debug(f"URL: {deployed_resource.url}")
                        self._add_resource(resource_key, deployed_resource)
                        return deployed_resource
                    except Exception:
                        # Universal rule: If resource was created (has ID), track it for cleanup
                        if hasattr(config, "id") and config.id:
                            log.warning(
                                f"Deployment failed but resource '{config.name}' was created with ID {config.id}, "
                                f"caching for cleanup"
                            )
                            self._add_resource(resource_key, config)
                        raise

                # Check for config drift
                stored_config_hash = self._resource_configs.get(resource_key, "")

                if stored_config_hash != new_config_hash:
                    # Attempt update (will redeploy if structural changes detected)
                    if hasattr(existing, "update"):
                        updated_resource = await existing.update(config)
                        self._add_resource(resource_key, updated_resource)
                        return updated_resource
                    else:
                        # Fallback: redeploy if update not supported
                        log.warning(
                            f"{config.name}: Resource type doesn't support updates, "
                            "redeploying"
                        )
                        await existing.undeploy()
                        try:
                            deployed_resource = await self._deploy_with_error_context(
                                config
                            )
                            log.debug(f"URL: {deployed_resource.url}")
                            self._add_resource(resource_key, deployed_resource)
                            return deployed_resource
                        except Exception:
                            # Universal rule: If resource was created (has ID), track it for cleanup
                            if hasattr(config, "id") and config.id:
                                log.warning(
                                    f"Deployment failed but resource '{config.name}' was created with ID {config.id}, "
                                    f"caching for cleanup"
                                )
                                self._add_resource(resource_key, config)
                            raise

                # Config unchanged, reuse existing
                log.info(f"URL: {existing.url}")
                return existing

            # No existing resource, deploy new one
            try:
                deployed_resource = await self._deploy_with_error_context(config)
                log.debug(f"URL: {deployed_resource.url}")
                self._add_resource(resource_key, deployed_resource)
                return deployed_resource
            except Exception:
                # Universal rule: If resource was created (has ID), track it for cleanup
                if hasattr(config, "id") and config.id:
                    log.warning(
                        f"Deployment failed but resource '{config.name}' was created with ID {config.id}, "
                        f"caching for cleanup"
                    )
                    self._add_resource(resource_key, config)
                raise

    @asynccontextmanager
    async def resource_lock(self, uid: str):
        # Ensure global lock is initialized (should be done in __init__)
        assert ResourceManager._global_lock is not None, "Global lock not initialized"

        # Get or create a per-resource lock
        async with ResourceManager._global_lock:
            if uid not in ResourceManager._deployment_locks:
                ResourceManager._deployment_locks[uid] = asyncio.Lock()
            resource_lock = ResourceManager._deployment_locks[uid]

        async with resource_lock:
            yield

    def list_all_resources(self) -> Dict[str, DeployableResource]:
        """List all tracked resources.

        Returns:
            Dictionary of resource_id -> DeployableResource
        """
        return self._resources.copy()

    def find_resources_by_name(self, name: str) -> List[Tuple[str, DeployableResource]]:
        """Find resources matching the given name.

        Args:
            name: The name to search for (exact match)

        Returns:
            List of (resource_id, resource) tuples matching the name
        """
        matches = []
        for uid, resource in self._resources.items():
            if hasattr(resource, "name") and resource.name == name:
                matches.append((uid, resource))
        return matches

    def find_resources_by_provider_id(
        self, provider_id: str
    ) -> List[Tuple[str, DeployableResource]]:
        """Find resources matching the provider-assigned ID.

        Args:
            provider_id: The provider resource ID to search for (exact match)

        Returns:
            List of (resource_id, resource) tuples matching the provider ID
        """
        matches = []
        for uid, resource in self._resources.items():
            if getattr(resource, "id", None) == provider_id:
                matches.append((uid, resource))
        return matches

    async def undeploy_resource(
        self,
        resource_id: str,
        resource_name: Optional[str] = None,
        force_remove: bool = False,
    ) -> Dict[str, Any]:
        """Undeploy a resource and remove from tracking.

        This is the public interface for removing resources. It calls the resource's
        _do_undeploy() method (polymorphic) and removes from tracking on success.

        Args:
            resource_id: The resource ID to undeploy
            resource_name: Optional human-readable name for error messages
            force_remove: If True, remove from tracking even if undeploy fails.
                         Use this for cleanup scenarios where resource is already deleted remotely.

        Returns:
            Dict with keys:
                - success: bool indicating if undeploy succeeded
                - name: resource name (if available)
                - endpoint_id: resource endpoint ID (if available)
                - message: status message
        """
        resource = self._resources.get(resource_id)
        log.debug(f"existing resource IDs: {list(self._resources.keys())}")

        if not resource:
            return {
                "success": False,
                "name": resource_name or "Unknown",
                "endpoint_id": "N/A",
                "message": f"Resource {resource_id} not found in tracking",
            }

        # Get resource metadata for response
        name = resource_name or getattr(resource, "name", "Unknown")
        endpoint_id = getattr(resource, "id", "N/A")

        try:
            # Call polymorphic undeploy method
            success = await resource._do_undeploy()

            if success:
                # Remove from tracking on successful undeploy
                self._remove_resource(resource_id)
                return {
                    "success": True,
                    "name": name,
                    "endpoint_id": endpoint_id,
                    "message": f"Successfully undeployed '{name}' ({endpoint_id})",
                }
            else:
                # Force remove if requested (e.g., cleanup of already-deleted resources)
                if force_remove:
                    self._remove_resource(resource_id)
                return {
                    "success": False,
                    "name": name,
                    "endpoint_id": endpoint_id,
                    "message": f"Failed to undeploy '{name}' ({endpoint_id})",
                }

        except NotImplementedError as e:
            # Resource type doesn't support undeploy yet
            if force_remove:
                self._remove_resource(resource_id)
            return {
                "success": False,
                "name": name,
                "endpoint_id": endpoint_id,
                "message": f"Cannot undeploy '{name}': {str(e)}",
            }
        except Exception as e:
            # Unexpected error during undeploy (e.g., already deleted remotely)
            if force_remove:
                self._remove_resource(resource_id)
            return {
                "success": False,
                "name": name,
                "endpoint_id": endpoint_id,
                "message": f"Error undeploying '{name}': {str(e)}",
            }
