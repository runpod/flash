"""Deployment environment management utilities."""

import asyncio
import json
import logging
import os
from typing import Dict, Any
from datetime import datetime
from pathlib import Path

from runpod_flash.config import get_paths
from runpod_flash.core.resources.app import FlashApp
from runpod_flash.core.resources.resource_manager import ResourceManager
from runpod_flash.runtime.resource_provisioner import create_resource_from_manifest

log = logging.getLogger(__name__)


async def upload_build(app_name: str, build_path: str | Path):
    app = await FlashApp.from_name(app_name)
    await app.upload_build(build_path)


def get_deployment_environments() -> Dict[str, Dict[str, Any]]:
    """Get all deployment environments."""
    paths = get_paths()
    deployments_file = paths.deployments_file

    if not deployments_file.exists():
        return {}

    try:
        with open(deployments_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def save_deployment_environments(environments: Dict[str, Dict[str, Any]]):
    """Save deployment environments to file."""
    paths = get_paths()
    deployments_file = paths.deployments_file

    # Ensure .flash directory exists
    paths.ensure_flash_dir()

    with open(deployments_file, "w") as f:
        json.dump(environments, f, indent=2)


def create_deployment_environment(name: str, config: Dict[str, Any]):
    """Create a new deployment environment."""
    environments = get_deployment_environments()

    # Mock environment creation
    environments[name] = {
        "status": "idle",
        "config": config,
        "created_at": datetime.now().isoformat(),
        "current_version": None,
        "last_deployed": None,
        "url": None,
        "version_history": [],
    }

    save_deployment_environments(environments)


def remove_deployment_environment(name: str):
    """Remove a deployment environment."""
    environments = get_deployment_environments()

    if name in environments:
        del environments[name]
        save_deployment_environments(environments)


async def provision_resources_for_build(
    app: FlashApp, build_id: str, environment_name: str, show_progress: bool = True
) -> Dict[str, str]:
    """Provision all resources upfront before environment activation.

    Args:
        app: FlashApp instance
        build_id: ID of the build to provision resources for
        environment_name: Name of environment (for logging/context)
        show_progress: Whether to show CLI progress

    Returns:
        Mapping of resource_name -> endpoint_url

    Raises:
        RuntimeError: If provisioning fails for any resource
    """
    # Load manifest from build
    manifest = await app.get_build_manifest(build_id)

    if not manifest or "resources" not in manifest:
        log.warning(f"No resources in manifest for build {build_id}")
        return {}

    # Create resource manager
    manager = ResourceManager()
    resources_to_provision = []

    # Create resource configs from manifest
    for resource_name, resource_config in manifest["resources"].items():
        resource = create_resource_from_manifest(
            resource_name,
            resource_config,
        )
        resources_to_provision.append((resource_name, resource))

    if show_progress:
        print(
            f"Provisioning {len(resources_to_provision)} resources for environment '{environment_name}'..."
        )

    # Provision resources in parallel
    resources_endpoints = {}
    provisioning_results = []

    try:
        # Use asyncio.gather for parallel provisioning
        tasks = [
            manager.get_or_deploy_resource(resource)
            for _, resource in resources_to_provision
        ]
        provisioning_results = await asyncio.gather(*tasks)

    except Exception as e:
        log.error(f"Provisioning failed: {e}")
        raise RuntimeError(f"Failed to provision resources: {e}") from e

    # Build resources_endpoints mapping
    lb_endpoint_url = None
    for (resource_name, _), deployed_resource in zip(
        resources_to_provision, provisioning_results
    ):
        # Get endpoint URL (both LoadBalancer and Serverless have endpoint_url)
        if hasattr(deployed_resource, "endpoint_url"):
            endpoint_url = deployed_resource.endpoint_url
        else:
            log.warning(f"Resource {resource_name} has no endpoint_url attribute")
            continue

        resources_endpoints[resource_name] = endpoint_url

        # Track load balancer URL for prominent logging
        if manifest["resources"][resource_name].get("is_load_balanced"):
            lb_endpoint_url = endpoint_url

        if show_progress:
            print(f"  ✓ {resource_name}: {endpoint_url}")

    # Update manifest in FlashApp with resources_endpoints
    manifest["resources_endpoints"] = resources_endpoints
    await app.update_build_manifest(build_id, manifest)

    if show_progress:
        print("✓ All resources provisioned and manifest updated")
        # Display load balancer URL prominently if present
        if lb_endpoint_url:
            print()
            print("=" * 60)
            print(f"Load Balancer Endpoint: {lb_endpoint_url}")
            print("=" * 60)

    return resources_endpoints


async def reconcile_and_provision_resources(
    app: FlashApp,
    build_id: str,
    environment_name: str,
    local_manifest: Dict[str, Any],
    environment_id: str | None = None,
    show_progress: bool = True,
) -> Dict[str, str]:
    """Reconcile local manifest with State Manager and provision resources.

    Compares local manifest to State Manager manifest to determine:
    - NEW resources to provision
    - CHANGED resources to update
    - REMOVED resources to delete

    Args:
        app: FlashApp instance
        build_id: ID of the build
        environment_name: Name of environment (for logging)
        local_manifest: Local manifest dictionary
        environment_id: Optional environment ID for endpoint provisioning
        show_progress: Whether to display progress information during
            reconciliation and provisioning

    Returns:
        Updated manifest with deployment information

    Raises:
        ValueError: If RUNPOD_API_KEY is missing when resources make remote calls
        RuntimeError: If reconciliation or provisioning fails
    """
    # Validate RUNPOD_API_KEY is available if any resource makes remote calls
    has_remote_callers = any(
        config.get("makes_remote_calls", False)
        for config in local_manifest.get("resources", {}).values()
    )
    if has_remote_callers and not os.getenv("RUNPOD_API_KEY"):
        raise ValueError(
            "RUNPOD_API_KEY environment variable is required when deploying "
            "resources that make remote calls. Set it in your environment "
            "before running flash deploy."
        )

    # Load State Manager manifest for comparison
    try:
        state_manifest = await app.get_build_manifest(build_id)
    except Exception as e:
        log.warning(f"Could not fetch State Manager manifest: {e}")
        state_manifest = {}  # First deployment, no state manifest yet

    # Reconcile: Determine actions
    local_resources = set(local_manifest.get("resources", {}).keys())
    state_resources = set(state_manifest.get("resources", {}).keys())

    to_provision = local_resources - state_resources  # New resources
    to_update = local_resources & state_resources  # Existing resources
    to_delete = state_resources - local_resources  # Removed resources

    if show_progress:
        log.debug(
            f"Reconciliation: {len(to_provision)} new, "
            f"{len(to_update)} existing, {len(to_delete)} to remove"
        )

    # Create resource manager
    manager = ResourceManager()
    actions = []

    # Provision new resources
    for resource_name in sorted(to_provision):
        resource_config = local_manifest["resources"][resource_name]
        resource = create_resource_from_manifest(
            resource_name,
            resource_config,
            flash_environment_id=environment_id,
        )
        actions.append(
            ("provision", resource_name, manager.get_or_deploy_resource(resource))
        )

    # Update existing resources (check if config changed OR if endpoint missing)
    for resource_name in sorted(to_update):
        local_config = local_manifest["resources"][resource_name]
        state_config = state_manifest.get("resources", {}).get(resource_name, {})

        # Simple hash comparison for config changes
        local_json = json.dumps(local_config, sort_keys=True)
        state_json = json.dumps(state_config, sort_keys=True)

        # Check if endpoint exists in state manifest
        has_endpoint = resource_name in state_manifest.get("resources_endpoints", {})

        if local_json != state_json or not has_endpoint:
            # Config changed OR no endpoint - need to provision/update
            resource = create_resource_from_manifest(
                resource_name,
                local_config,
                flash_environment_id=environment_id,
            )
            actions.append(
                ("update", resource_name, manager.get_or_deploy_resource(resource))
            )
        else:
            # Config unchanged AND endpoint exists - reuse existing endpoint info
            if "endpoint_id" in state_config:
                local_manifest["resources"][resource_name]["endpoint_id"] = (
                    state_config["endpoint_id"]
                )
            if resource_name in state_manifest.get("resources_endpoints", {}):
                local_manifest.setdefault("resources_endpoints", {})[resource_name] = (
                    state_manifest["resources_endpoints"][resource_name]
                )

    # Delete removed resources
    for resource_name in sorted(to_delete):
        log.debug(f"Resource {resource_name} marked for deletion (not implemented yet)")

    # Execute all actions in parallel with timeout
    if actions:
        try:
            provisioning_tasks = [action[2] for action in actions]
            provisioning_results = await asyncio.wait_for(
                asyncio.gather(*provisioning_tasks),
                timeout=600,  # 10 minutes
            )
        except asyncio.TimeoutError:
            raise RuntimeError(
                "Resource provisioning timed out after 10 minutes. "
                "Check RunPod dashboard for partial deployments."
            )
        except Exception as e:
            log.error(f"Provisioning failed: {e}")
            raise RuntimeError(f"Failed to provision resources: {e}") from e

        # Update local manifest with deployment info
        local_manifest.setdefault("resources_endpoints", {})

        for i, (action_type, resource_name, _) in enumerate(actions):
            deployed_resource = provisioning_results[i]

            # Extract endpoint info
            endpoint_id = getattr(deployed_resource, "endpoint_id", None)
            endpoint_url = getattr(deployed_resource, "endpoint_url", None)

            if endpoint_id:
                local_manifest["resources"][resource_name]["endpoint_id"] = endpoint_id
            if endpoint_url:
                local_manifest["resources_endpoints"][resource_name] = endpoint_url

            log.debug(
                f"{'Provisioned' if action_type == 'provision' else 'Updated'}: "
                f"{resource_name} -> {endpoint_url}"
            )

    # Validate load balancer was provisioned
    lb_resources = [
        name
        for name, config in local_manifest.get("resources", {}).items()
        if config.get("is_load_balanced", False)
    ]

    if lb_resources:
        missing = [
            name
            for name in lb_resources
            if name not in local_manifest.get("resources_endpoints", {})
        ]
        if missing:
            provisioned = list(local_manifest.get("resources_endpoints", {}).keys())
            raise RuntimeError(
                f"Load balancer resource(s) {missing} not provisioned. "
                f"Successfully provisioned: {provisioned}"
            )

    # Write updated manifest back to local file
    manifest_path = Path.cwd() / ".flash" / "flash_manifest.json"
    manifest_path.write_text(json.dumps(local_manifest, indent=2))

    log.debug(f"Local manifest updated at {manifest_path.relative_to(Path.cwd())}")

    # Overwrite State Manager manifest with local manifest
    await app.update_build_manifest(build_id, local_manifest)

    return local_manifest.get("resources_endpoints", {})


def validate_local_manifest() -> Dict[str, Any]:
    """Validate that local manifest exists and is valid.

    Returns:
        Loaded manifest dictionary

    Raises:
        FileNotFoundError: If manifest not found
        ValueError: If manifest is invalid
    """
    manifest_path = Path.cwd() / ".flash" / "flash_manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Manifest not found at {manifest_path}. "
            "Run 'flash deploy' to build and deploy your project."
        )

    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid manifest JSON at {manifest_path}: {e}") from e

    if not manifest or "resources" not in manifest:
        raise ValueError(
            f"Invalid manifest at {manifest_path}: missing 'resources' section"
        )

    return manifest


async def deploy_from_uploaded_build(
    app: FlashApp,
    build_id: str,
    env_name: str,
    local_manifest: Dict[str, Any],
) -> Dict[str, Any]:
    """Deploy an already-uploaded build to an environment.

    Args:
        app: FlashApp instance (already resolved)
        build_id: ID of the uploaded build
        env_name: Target environment name
        local_manifest: Validated local manifest dict

    Returns:
        Deployment result with resources_endpoints and local_manifest keys
    """
    environment = await app.get_environment_by_name(env_name)
    result = await app.deploy_build_to_environment(build_id, environment_name=env_name)

    try:
        resources_endpoints = await reconcile_and_provision_resources(
            app,
            build_id,
            env_name,
            local_manifest,
            environment_id=environment.get("id"),
            show_progress=False,
        )
        log.debug(f"Provisioned {len(resources_endpoints)} resources for {env_name}")
    except Exception as e:
        log.error(f"Resource provisioning failed: {e}")
        raise

    result["resources_endpoints"] = resources_endpoints
    result["local_manifest"] = local_manifest
    return result


def rollback_deployment(name: str, target_version: str):
    """Rollback deployment to a previous version (mock implementation)."""
    environments = get_deployment_environments()

    if name not in environments:
        raise ValueError(f"Environment {name} not found")

    # Find target version
    target_version_info = None
    for version in environments[name]["version_history"]:
        if version["version"] == target_version:
            target_version_info = version
            break

    if not target_version_info:
        raise ValueError(f"Version {target_version} not found")

    # Update current version
    environments[name]["current_version"] = target_version
    environments[name]["last_deployed"] = datetime.now().isoformat()

    # Update version history
    for version in environments[name]["version_history"]:
        version["is_current"] = version["version"] == target_version

    save_deployment_environments(environments)


def get_environment_info(name: str) -> Dict[str, Any]:
    """Get detailed information about an environment."""
    environments = get_deployment_environments()

    if name not in environments:
        raise ValueError(f"Environment {name} not found")

    env_info = environments[name].copy()

    # Add mock metrics and additional info
    if env_info["status"] == "active":
        env_info.update(
            {
                "uptime": "99.9%",
                "requests_24h": 145234,
                "avg_response_time": "245ms",
                "error_rate": "0.02%",
                "cpu_usage": "45%",
                "memory_usage": "62%",
            }
        )

    # Ensure version history exists and is properly formatted
    if "version_history" not in env_info:
        env_info["version_history"] = []

    # Add sample version history if empty
    if not env_info["version_history"] and env_info["current_version"]:
        env_info["version_history"] = [
            {
                "version": env_info["current_version"],
                "deployed_at": env_info.get(
                    "last_deployed", datetime.now().isoformat()
                ),
                "description": "Initial deployment",
                "is_current": True,
            }
        ]

    return env_info
