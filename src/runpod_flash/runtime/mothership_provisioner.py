"""Mothership auto-provisioning logic with manifest reconciliation."""

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from runpod_flash.core.resources.base import DeployableResource
from runpod_flash.core.resources.constants import ENDPOINT_DOMAIN
from runpod_flash.core.resources.resource_manager import ResourceManager

from .state_manager_client import StateManagerClient

logger = logging.getLogger(__name__)


@dataclass
class ManifestDiff:
    """Result of manifest reconciliation."""

    new: List[str]  # Resources to deploy
    changed: List[str]  # Resources to update
    removed: List[str]  # Resources to delete
    unchanged: List[str]  # Resources to skip


def get_mothership_url() -> str:
    """Construct mothership URL from RUNPOD_ENDPOINT_ID env var.

    Returns:
        Mothership URL in format: https://{endpoint_id}.{ENDPOINT_DOMAIN}

    Raises:
        RuntimeError: If RUNPOD_ENDPOINT_ID not set
    """
    endpoint_id = os.getenv("RUNPOD_ENDPOINT_ID")
    if not endpoint_id:
        raise RuntimeError("RUNPOD_ENDPOINT_ID environment variable not set")
    return f"https://{endpoint_id}.{ENDPOINT_DOMAIN}"


def is_mothership() -> bool:
    """Check if current endpoint is mothership.

    Returns:
        True if FLASH_IS_MOTHERSHIP env var is 'true'
    """
    return os.getenv("FLASH_IS_MOTHERSHIP", "").lower() == "true"


def load_manifest(manifest_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load flash_manifest.json.

    Args:
        manifest_path: Explicit path to manifest. Tries env var and
            auto-detection if not provided.

    Returns:
        Manifest dictionary

    Raises:
        FileNotFoundError: If manifest not found
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
                logger.debug(f"Manifest loaded from {path}")
                return manifest_dict
            except Exception as e:
                logger.warning(f"Failed to load manifest from {path}: {e}")
                continue

    raise FileNotFoundError(
        f"flash_manifest.json not found. Searched paths: {paths_to_try}"
    )


def compute_resource_hash(resource_data: Dict[str, Any]) -> str:
    """Compute hash of resource configuration for drift detection.

    Args:
        resource_data: Resource configuration from manifest

    Returns:
        SHA-256 hash of resource config
    """
    # Convert to JSON and hash to detect changes
    config_json = json.dumps(resource_data, sort_keys=True)
    return hashlib.sha256(config_json.encode()).hexdigest()


def filter_resources_by_manifest(
    all_resources: Dict[str, DeployableResource],
    manifest: Dict[str, Any],
) -> Dict[str, DeployableResource]:
    """Filter cached resources to only those defined in manifest.

    Prevents stale cache entries from being deployed by checking:
    1. Resource name exists in manifest
    2. Resource type matches manifest entry

    Stale entries can occur when codebase is refactored but the resource
    cache still contains endpoints from an older version.

    Args:
        all_resources: All resources from ResourceManager cache
        manifest: Current deployment manifest

    Returns:
        Filtered dict containing only manifest-matching resources
    """
    manifest_resources = manifest.get("resources", {})
    filtered = {}
    removed_count = 0

    for key, resource in all_resources.items():
        resource_name = resource.name if hasattr(resource, "name") else None

        if not resource_name:
            logger.warning(f"Skipping cached resource without name: {key}")
            removed_count += 1
            continue

        # Check if resource exists in manifest
        if resource_name not in manifest_resources:
            logger.info(
                f"Removing stale cached resource '{resource_name}' "
                f"(not in current manifest)"
            )
            removed_count += 1
            continue

        # Check if type matches
        manifest_entry = manifest_resources[resource_name]
        expected_type = manifest_entry.get("resource_type")
        actual_type = resource.__class__.__name__

        if expected_type and expected_type != actual_type:
            logger.warning(
                f"Removing stale cached resource '{resource_name}' "
                f"(type mismatch: cached={actual_type}, manifest={expected_type})"
            )
            removed_count += 1
            continue

        filtered[key] = resource

    if removed_count > 0:
        logger.info(
            f"Cache validation: Removed {removed_count} stale "
            f"resource(s) not matching manifest"
        )

    return filtered


def reconcile_manifests(
    local_manifest: Dict[str, Any],
    persisted_manifest: Optional[Dict[str, Any]],
) -> ManifestDiff:
    """Compare local and persisted manifests to detect changes.

    Args:
        local_manifest: Current manifest from flash_manifest.json
        persisted_manifest: Last known manifest from State Manager (None if first boot)

    Returns:
        ManifestDiff with categorized resources
    """
    local_resources = local_manifest.get("resources", {})
    persisted_resources = (
        persisted_manifest.get("resources", {}) if persisted_manifest else {}
    )

    new = []
    changed = []
    unchanged = []

    for name, local_data in local_resources.items():
        if name not in persisted_resources:
            new.append(name)
        else:
            # Compare config hashes to detect changes
            local_hash = compute_resource_hash(local_data)
            persisted_hash = persisted_resources[name].get("config_hash")

            if local_hash != persisted_hash:
                changed.append(name)
            else:
                unchanged.append(name)

    # Detect removed resources (in persisted, not in local)
    removed = [name for name in persisted_resources if name not in local_resources]

    return ManifestDiff(new=new, changed=changed, removed=removed, unchanged=unchanged)


def create_resource_from_manifest(
    resource_name: str,
    resource_data: Dict[str, Any],
    mothership_url: str = "",
    flash_environment_id: Optional[str] = None,
) -> DeployableResource:
    """Create DeployableResource config from manifest entry.

    Args:
        resource_name: Name of the resource
        resource_data: Resource configuration from manifest
        mothership_url: Optional mothership URL (for future use with child env vars)
        flash_environment_id: Optional flash environment ID to attach

    Returns:
        Configured DeployableResource ready for deployment

    Raises:
        ValueError: If resource type not supported
    """
    from runpod_flash.core.resources.live_serverless import (
        CpuLiveLoadBalancer,
        CpuLiveServerless,
        LiveLoadBalancer,
        LiveServerless,
    )
    from runpod_flash.core.resources.load_balancer_sls_resource import (
        LoadBalancerSlsResource,
    )
    from runpod_flash.core.resources.serverless import ServerlessResource

    resource_type = resource_data.get("resource_type", "ServerlessResource")

    # Support both Serverless and LoadBalancer resource types
    if resource_type not in [
        "ServerlessResource",
        "LiveServerless",
        "CpuLiveServerless",
        "LoadBalancerSlsResource",
        "LiveLoadBalancer",
        "CpuLiveLoadBalancer",
    ]:
        raise ValueError(
            f"Unsupported resource type for auto-provisioning: {resource_type}"
        )

    # Create resource with mothership environment variables
    # Manifest now includes deployment config (imageName, templateId, GPU/worker settings)
    # This enables auto-provisioning to create valid resource configurations

    # Create appropriate resource type based on manifest entry
    import os

    env = {
        "FLASH_RESOURCE_NAME": resource_name,
    }

    # Only set FLASH_MOTHERSHIP_ID when running in mothership context
    # (i.e., when RUNPOD_ENDPOINT_ID is available).
    # During CLI provisioning, RUNPOD_ENDPOINT_ID is not set, so we don't
    # include FLASH_MOTHERSHIP_ID. This avoids Pydantic validation errors
    # (missing keys are fine, None values are not).
    mothership_id = os.getenv("RUNPOD_ENDPOINT_ID")
    if mothership_id:
        env["FLASH_MOTHERSHIP_ID"] = mothership_id

    # Load-balanced endpoint environment variables
    if resource_data.get("is_mothership") or resource_data.get("is_load_balanced"):
        env["FLASH_ENDPOINT_TYPE"] = "lb"
        env["FLASH_IS_MOTHERSHIP"] = "true"  # backward compat during transition
        if "main_file" in resource_data:
            env["FLASH_MAIN_FILE"] = resource_data["main_file"]
        if "app_variable" in resource_data:
            env["FLASH_APP_VARIABLE"] = resource_data["app_variable"]

    # Add "tmp-" prefix for test-mothership deployments
    # Check environment variable set by test-mothership command

    is_test_mothership = os.getenv("FLASH_IS_TEST_MOTHERSHIP", "").lower() == "true"

    if is_test_mothership and not resource_name.startswith("tmp-"):
        prefixed_name = f"tmp-{resource_name}"
        logger.info(f"Test mode: Using temporary name '{prefixed_name}'")
    else:
        prefixed_name = resource_name

    # Extract deployment config from manifest
    deployment_kwargs = {"name": prefixed_name, "env": env}

    if flash_environment_id:
        deployment_kwargs["flashEnvironmentId"] = flash_environment_id

    # Add imageName or templateId if present (required for validation)
    if "imageName" in resource_data:
        deployment_kwargs["imageName"] = resource_data["imageName"]
    elif "templateId" in resource_data:
        deployment_kwargs["templateId"] = resource_data["templateId"]

    # Optional: Add GPU/worker config if present
    if "gpuIds" in resource_data:
        deployment_kwargs["gpuIds"] = resource_data["gpuIds"]
    if "workersMin" in resource_data:
        deployment_kwargs["workersMin"] = resource_data["workersMin"]
    if "workersMax" in resource_data:
        deployment_kwargs["workersMax"] = resource_data["workersMax"]

    # Note: template is extracted but not passed to resource constructor
    # Let resources create their own templates with proper initialization
    # Templates are created by resource's _create_new_template() method

    # Create resource with full deployment config
    if resource_type == "CpuLiveLoadBalancer":
        resource = CpuLiveLoadBalancer(**deployment_kwargs)
    elif resource_type == "CpuLiveServerless":
        resource = CpuLiveServerless(**deployment_kwargs)
    elif resource_type == "LiveLoadBalancer":
        resource = LiveLoadBalancer(**deployment_kwargs)
    elif resource_type == "LiveServerless":
        resource = LiveServerless(**deployment_kwargs)
    elif resource_type == "LoadBalancerSlsResource":
        resource = LoadBalancerSlsResource(**deployment_kwargs)
    else:
        # ServerlessResource (default)
        resource = ServerlessResource(**deployment_kwargs)

    return resource


async def reconcile_children(
    manifest_path: Path,
    mothership_url: str,
    state_client: StateManagerClient,
) -> None:
    """Reconcile all child resources based on manifest differences.

    Orchestrates deployment/update/delete of resources based on manifest differences.

    Args:
        manifest_path: Path to flash_manifest.json
        mothership_url: Mothership endpoint URL to set on children
        state_client: State Manager API client
    """
    try:
        # Load local manifest
        local_manifest = load_manifest(manifest_path)

        # Get persisted manifest from State Manager
        mothership_id = os.getenv("RUNPOD_ENDPOINT_ID")
        if not mothership_id:
            logger.error("RUNPOD_ENDPOINT_ID not set, cannot load persisted manifest")
            return

        persisted_manifest = await state_client.get_persisted_manifest(mothership_id)

        # Reconcile manifests
        logger.info(
            f"Starting reconciliation: {len(local_manifest.get('resources', {}))} manifest resources"
        )

        diff = reconcile_manifests(local_manifest, persisted_manifest)

        logger.info(
            f"Reconciliation plan: {len(diff.new)} to deploy, "
            f"{len(diff.changed)} to update, "
            f"{len(diff.removed)} to remove, "
            f"{len(diff.unchanged)} unchanged"
        )

        manager = ResourceManager()

        # Filter cached resources to prevent stale entries from being deployed
        # This ensures resources from old codebase versions don't get redeployed
        all_cached = manager.list_all_resources()
        if all_cached:
            valid_cached = filter_resources_by_manifest(all_cached, local_manifest)
            logger.info(
                f"Cache validation: {len(all_cached)} cached, "
                f"{len(valid_cached)} valid, "
                f"{len(local_manifest.get('resources', {}))} in manifest"
            )

        # Deploy NEW resources
        for resource_name in diff.new:
            try:
                resource_data = local_manifest["resources"][resource_name]
                config = create_resource_from_manifest(
                    resource_name, resource_data, mothership_url
                )
                deployed = await manager.get_or_deploy_resource(config)

                # Update State Manager
                await state_client.update_resource_state(
                    mothership_id,
                    resource_name,
                    {
                        "config_hash": compute_resource_hash(resource_data),
                        "endpoint_url": deployed.endpoint_url
                        if hasattr(deployed, "endpoint_url")
                        else deployed.url,
                        "status": "deployed",
                    },
                )
                logger.info(f"Deployed new resource: {resource_name}")

            except Exception as e:
                logger.error(f"Failed to deploy {resource_name}: {e}")
                try:
                    await state_client.update_resource_state(
                        mothership_id,
                        resource_name,
                        {"status": "failed", "error": str(e)},
                    )
                except Exception as sm_error:
                    logger.error(
                        f"Failed to update State Manager for {resource_name}: {sm_error}"
                    )

        # Update CHANGED resources
        for resource_name in diff.changed:
            try:
                resource_data = local_manifest["resources"][resource_name]
                config = create_resource_from_manifest(
                    resource_name, resource_data, mothership_url
                )
                updated = await manager.get_or_deploy_resource(config)

                await state_client.update_resource_state(
                    mothership_id,
                    resource_name,
                    {
                        "config_hash": compute_resource_hash(resource_data),
                        "endpoint_url": updated.endpoint_url
                        if hasattr(updated, "endpoint_url")
                        else updated.url,
                        "status": "updated",
                    },
                )
                logger.info(f"Updated resource: {resource_name}")

            except Exception as e:
                logger.error(f"Failed to update {resource_name}: {e}")
                try:
                    await state_client.update_resource_state(
                        mothership_id,
                        resource_name,
                        {"status": "failed", "error": str(e)},
                    )
                except Exception as sm_error:
                    logger.error(
                        f"Failed to update State Manager for {resource_name}: {sm_error}"
                    )

        # Delete REMOVED resources
        for resource_name in diff.removed:
            try:
                # Find resource in ResourceManager
                matches = manager.find_resources_by_name(resource_name)
                if matches:
                    resource_id, _ = matches[0]
                    result = await manager.undeploy_resource(resource_id, resource_name)

                    if result["success"]:
                        try:
                            await state_client.remove_resource_state(
                                mothership_id, resource_name
                            )
                        except Exception as sm_error:
                            logger.error(
                                f"Failed to remove {resource_name} from State Manager: {sm_error}"
                            )
                        logger.info(f"Deleted removed resource: {resource_name}")
                    else:
                        logger.error(
                            f"Failed to delete {resource_name}: {result['message']}"
                        )
                else:
                    logger.warning(
                        f"Removed resource {resource_name} not found in ResourceManager"
                    )

            except Exception as e:
                logger.error(f"Failed to delete {resource_name}: {e}")

        logger.info("=" * 60)
        logger.info("Provisioning complete - All child endpoints deployed")
        logger.info(f"Total endpoints: {len(local_manifest.get('resources', {}))}")
        logger.info("Test phase: Manifest updated with child endpoint URLs")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Provisioning failed: {e}", exc_info=True)
