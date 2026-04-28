"""Deployment environment management utilities."""

import asyncio
import copy
import json
import logging
from typing import Dict, Any
from pathlib import Path

from runpod_flash.core.resources.serverless import ServerlessResource
from runpod_flash.core.resources.app import FlashApp
from runpod_flash.core.resources.resource_manager import ResourceManager
from runpod_flash.runtime.resource_provisioner import create_resource_from_manifest

log = logging.getLogger(__name__)

RUNTIME_RESOURCE_FIELDS = set(ServerlessResource.RUNTIME_FIELDS) | {
    "id",
    "endpoint_id",
}


def _normalized_resource_attr(resource: Any, *names: str) -> str | None:
    for name in names:
        value = getattr(resource, name, None)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _manifest_without_ai_keys(manifest: Dict[str, Any]) -> Dict[str, Any]:
    sanitized_manifest = copy.deepcopy(manifest)
    resources = sanitized_manifest.get("resources")
    if not isinstance(resources, dict):
        return sanitized_manifest

    for config in resources.values():
        if isinstance(config, dict):
            config.pop("aiKey", None)

    return sanitized_manifest


def _resource_config_for_compare(config: Dict[str, Any]) -> Dict[str, Any]:
    compare_config = copy.deepcopy(config)
    for field in RUNTIME_RESOURCE_FIELDS:
        compare_config.pop(field, None)
    return compare_config


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
    from runpod_flash.core.credentials import get_api_key

    if has_remote_callers and not get_api_key():
        raise ValueError(
            "RUNPOD_API_KEY is required when deploying resources that make "
            "remote calls. Set it via 'flash login' or in your environment."
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
    manifest_python_version = local_manifest.get("python_version")

    # Inject source fingerprint into each resource's env so that code-only
    # changes (no resource config diff) still trigger a rolling release.
    # The fingerprint is computed during flash build from user source files.
    # Mutation intentional: persisted to state manifest via update_build_manifest below.
    source_fingerprint = local_manifest.get("source_fingerprint")
    if source_fingerprint:
        for resource_config in local_manifest.get("resources", {}).values():
            env = resource_config.setdefault("env", {})
            env["_FLASH_SOURCE_FINGERPRINT"] = source_fingerprint

    # Provision new resources
    for resource_name in sorted(to_provision):
        resource_config = local_manifest["resources"][resource_name]
        resource = create_resource_from_manifest(
            resource_name,
            resource_config,
            flash_environment_id=environment_id,
            python_version=manifest_python_version,
            flash_app_name=app.name,
            flash_env_name=environment_name,
        )
        actions.append(
            ("provision", resource_name, manager.get_or_deploy_resource(resource))
        )

    # Update existing resources (check if config changed OR if endpoint missing)
    for resource_name in sorted(to_update):
        local_config = local_manifest["resources"][resource_name]
        state_config = state_manifest.get("resources", {}).get(resource_name, {})

        # Compare only user-managed config fields (exclude runtime metadata)
        local_json = json.dumps(
            _resource_config_for_compare(local_config),
            sort_keys=True,
        )
        state_json = json.dumps(
            _resource_config_for_compare(state_config),
            sort_keys=True,
        )

        # Check if endpoint exists in state manifest
        has_endpoint = resource_name in state_manifest.get("resources_endpoints", {})

        if local_json != state_json or not has_endpoint:
            # Config changed OR no endpoint - need to provision/update
            resource = create_resource_from_manifest(
                resource_name,
                local_config,
                flash_environment_id=environment_id,
                python_version=manifest_python_version,
                flash_app_name=app.name,
                flash_env_name=environment_name,
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
            if "aiKey" in state_config:
                local_manifest["resources"][resource_name]["aiKey"] = state_config[
                    "aiKey"
                ]
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
            endpoint_id = _normalized_resource_attr(
                deployed_resource, "endpoint_id", "id"
            )
            endpoint_url = getattr(deployed_resource, "endpoint_url", None)
            if isinstance(endpoint_url, str):
                endpoint_url = endpoint_url.strip() or None
            else:
                endpoint_url = None
            ai_key = _normalized_resource_attr(deployed_resource, "aiKey", "ai_key")
            if endpoint_id:
                local_manifest["resources"][resource_name]["endpoint_id"] = endpoint_id
            if endpoint_url:
                local_manifest["resources_endpoints"][resource_name] = endpoint_url
            if ai_key:
                local_manifest["resources"][resource_name]["aiKey"] = ai_key

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

    local_manifest_for_disk = _manifest_without_ai_keys(local_manifest)

    # Write updated manifest back to local file
    manifest_path = Path.cwd() / ".flash" / "flash_manifest.json"
    manifest_path.write_text(json.dumps(local_manifest_for_disk, indent=2))

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
