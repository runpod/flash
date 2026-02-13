"""Deployment environment management utilities."""

import asyncio
import json
import logging
from typing import Dict, Any
from datetime import datetime
from pathlib import Path

from runpod_flash.config import get_paths
from runpod_flash.core.resources.app import FlashApp
from runpod_flash.core.resources.resource_manager import ResourceManager
from runpod_flash.runtime.mothership_provisioner import create_resource_from_manifest

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
    mothership_url = None
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

        # Track mothership URL for prominent logging
        if resource_name in ("mothership", "mothership-entrypoint"):
            mothership_url = endpoint_url

        if show_progress:
            print(f"  ✓ {resource_name}: {endpoint_url}")

    # Log what we're uploading to State Manager
    log.info(
        f"Uploading manifest to State Manager with {len(resources_endpoints)} endpoints:"
    )
    for resource_name, url in resources_endpoints.items():
        log.info(f"  {resource_name} → {url}")

    # DIAGNOSTIC: Log the full resources_endpoints mapping for debugging
    log.info(
        f"[DEPLOY SYNC] resources_endpoints mapping: {json.dumps(resources_endpoints, indent=2)}"
    )

    # Update manifest in FlashApp with resources_endpoints
    manifest["resources_endpoints"] = resources_endpoints
    await app.update_build_manifest(build_id, manifest)

    # Verify upload succeeded
    log.debug(f"Manifest uploaded to State Manager for build {build_id}")

    if show_progress:
        print("✓ All resources provisioned and manifest updated")
        # Display mothership URL prominently if present
        if mothership_url:
            print()
            print("=" * 60)
            print(f"Mothership Endpoint: {mothership_url}")
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
        show_progress: Whether to show CLI progress

    Returns:
        Updated manifest with deployment information

    Raises:
        RuntimeError: If reconciliation or provisioning fails
    """
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
        print(
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
        log.info(f"Resource {resource_name} marked for deletion (not implemented yet)")

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

            if show_progress:
                action_label = (
                    "✓ Provisioned" if action_type == "provision" else "✓ Updated"
                )
                print(f"{action_label}: {resource_name} → {endpoint_url}")

    # Validate mothership was provisioned
    mothership_resources = [
        name
        for name in local_manifest.get("resources", {}).keys()
        if name in ("mothership", "mothership-entrypoint")
    ]

    if mothership_resources:
        missing = [
            name
            for name in mothership_resources
            if name not in local_manifest.get("resources_endpoints", {})
        ]
        if missing:
            provisioned = list(local_manifest.get("resources_endpoints", {}).keys())
            raise RuntimeError(
                f"Mothership resource(s) {missing} not provisioned. "
                f"Successfully provisioned: {provisioned}"
            )

    # Write updated manifest back to local file
    manifest_path = Path.cwd() / ".flash" / "flash_manifest.json"
    manifest_path.write_text(json.dumps(local_manifest, indent=2))

    if show_progress:
        print(f"✓ Local manifest updated at {manifest_path.relative_to(Path.cwd())}")

    # Log what we're uploading to State Manager
    resources_endpoints = local_manifest.get("resources_endpoints", {})
    log.info(
        f"Uploading manifest to State Manager with {len(resources_endpoints)} endpoints:"
    )
    for resource_name, url in resources_endpoints.items():
        log.info(f"  {resource_name} → {url}")

    # DIAGNOSTIC: Log what we're uploading to State Manager
    log.info(
        f"[DEPLOY SYNC] Uploading manifest to State Manager - "
        f"build_id={build_id}, environment_id={environment_id}"
    )
    log.info(
        f"[DEPLOY SYNC] Manifest contains resources_endpoints: "
        f"{json.dumps(local_manifest.get('resources_endpoints', {}), indent=2)}"
    )

    # Overwrite State Manager manifest with local manifest
    await app.update_build_manifest(build_id, local_manifest)

    # Verify upload succeeded
    log.debug(f"Manifest uploaded to State Manager for build {build_id}")

    if show_progress:
        print("✓ State Manager manifest updated")
        print()

        # Display mothership in simplified format
        resources_endpoints = local_manifest.get("resources_endpoints", {})

        for resource_name in sorted(resources_endpoints.keys()):
            # Display mothership endpoint prominently
            if resource_name in ("mothership", "mothership-entrypoint"):
                print(f"🚀 Deployed: {app.name}")
                print(f"   Environment: {environment_name}")
                print(f"   URL:  {resources_endpoints[resource_name]}")
                print()
                break

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


async def deploy_to_environment(
    app_name: str, env_name: str, build_path: Path
) -> Dict[str, str]:
    """Deploy current project to environment.

    Args:
        app_name: Name of the Flash app
        env_name: Target environment name
        build_path: Path to the build archive

    Returns:
        Mapping of resource_name -> endpoint_url (resources_endpoints)

    Raises:
        runpod_flash.core.resources.app.FlashEnvironmentNotFoundError: If the environment does not exist
        FileNotFoundError: If manifest not found
        ValueError: If manifest is invalid
    """
    # Validate manifest exists before proceeding
    local_manifest = validate_local_manifest()

    app = await FlashApp.from_name(app_name)
    # Verify environment exists (will raise FlashEnvironmentNotFoundError if not)
    environment = await app.get_environment_by_name(env_name)

    build = await app.upload_build(build_path)
    build_id = build["id"]

    await app.deploy_build_to_environment(build_id, environment_name=env_name)

    # DIAGNOSTIC: Log environment activation
    log.info(f"[DEPLOY] Environment {env_name} activated with build_id={build_id}")

    try:
        resources_endpoints = await reconcile_and_provision_resources(
            app,
            build_id,
            env_name,
            local_manifest,
            environment_id=environment.get("id"),
            show_progress=True,
        )
        log.debug(f"Provisioned {len(resources_endpoints)} resources for {env_name}")
    except Exception as e:
        log.error(f"Resource provisioning failed: {e}")
        raise

    return resources_endpoints


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
