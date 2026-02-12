"""Helper functions for resource provisioning from manifest.

CLI-time provisioning utilities for deploying Flash resources. All provisioning
happens during `flash deploy` via CLI, not at runtime.
"""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from runpod_flash.core.resources.base import DeployableResource

logger = logging.getLogger(__name__)


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

    # Inject FLASH_ENVIRONMENT_ID if provided (for State Manager queries at runtime)
    if flash_environment_id:
        env["FLASH_ENVIRONMENT_ID"] = flash_environment_id

    # Only set FLASH_MOTHERSHIP_ID when running in mothership context
    # (i.e., when RUNPOD_ENDPOINT_ID is available).
    # During CLI provisioning, RUNPOD_ENDPOINT_ID is not set, so we don't
    # include FLASH_MOTHERSHIP_ID. This avoids Pydantic validation errors
    # (missing keys are fine, None values are not).
    mothership_id = os.getenv("RUNPOD_ENDPOINT_ID")
    if mothership_id:
        env["FLASH_MOTHERSHIP_ID"] = mothership_id

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
