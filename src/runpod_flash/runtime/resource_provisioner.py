"""Resource creation from deployment manifests."""

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def create_resource_from_manifest(
    resource_name: str,
    resource_data: Dict[str, Any],
    flash_environment_id: Optional[str] = None,
) -> Any:
    """Create a deployable resource configuration from a manifest entry.

    Args:
        resource_name: Name of the resource
        resource_data: Resource configuration from manifest
        flash_environment_id: Optional flash environment ID to attach

    Returns:
        Configured resource instance ready for deployment

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

    # Create resource with environment variables from manifest
    # Manifest now includes deployment config (imageName, templateId, GPU/worker settings)
    # This enables auto-provisioning to create valid resource configurations

    # Create appropriate resource type based on manifest entry
    env = {
        "FLASH_RESOURCE_NAME": resource_name,
    }

    # Load-balanced endpoint environment variables
    if resource_data.get("is_load_balanced"):
        env["FLASH_ENDPOINT_TYPE"] = "lb"
        if "main_file" in resource_data:
            env["FLASH_MAIN_FILE"] = resource_data["main_file"]
        if "app_variable" in resource_data:
            env["FLASH_APP_VARIABLE"] = resource_data["app_variable"]

    # Inject RUNPOD_API_KEY for endpoints that make remote calls
    if resource_data.get("makes_remote_calls", False):
        api_key = os.getenv("RUNPOD_API_KEY")
        if api_key:
            env["RUNPOD_API_KEY"] = api_key

    # Add "tmp-" prefix for test deployments
    # Check environment variable set by test deployment command
    is_test_deployment = os.getenv("FLASH_IS_TEST_DEPLOYMENT", "").lower() == "true"

    if is_test_deployment and not resource_name.startswith("tmp-"):
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
