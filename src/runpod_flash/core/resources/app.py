from pathlib import Path
import asyncio
import json
from typing import Dict, Optional, Union, Tuple, TYPE_CHECKING, Any, List
import logging

from ..api.runpod import RunpodGraphQLClient
from ..resources.resource_manager import ResourceManager
from ..resources.serverless import ServerlessEndpoint, NetworkVolume
from ..resources.constants import (
    TARBALL_CONTENT_TYPE,
    MAX_TARBALL_SIZE_MB,
    VALID_TARBALL_EXTENSIONS,
    GZIP_MAGIC_BYTES,
)

if TYPE_CHECKING:
    from . import ServerlessResource

log = logging.getLogger(__name__)


class FlashAppError(Exception):
    """Base exception for Flash app operations."""

    pass


class FlashAppNotFoundError(FlashAppError):
    """Raised when a Flash app cannot be found."""

    pass


class FlashEnvironmentNotFoundError(FlashAppError):
    """Raised when a Flash environment cannot be found."""

    pass


class FlashBuildNotFoundError(FlashAppError):
    """Raised when a Flash build cannot be found."""

    pass


def _validate_exclusive_params(
    param1: Any, param2: Any, name1: str, name2: str
) -> None:
    """Validate that exactly one of two parameters is provided (XOR).

    Args:
        param1: First parameter value
        param2: Second parameter value
        name1: Name of first parameter (for error message)
        name2: Name of second parameter (for error message)

    Raises:
        ValueError: If both or neither parameters are provided
    """
    if (not param1 and not param2) or (param1 and param2):
        raise ValueError(f"Provide exactly one of {name1} or {name2}")


def _validate_tarball_file(tar_path: Path) -> None:
    """Validate tarball file before upload.

    Validates:
    - File exists
    - File extension is valid (.tar.gz or .tgz)
    - File is a gzip file (magic bytes check)
    - File size is within limits

    Args:
        tar_path: Path to the tarball file

    Raises:
        FileNotFoundError: If file does not exist
        ValueError: If file is invalid (extension, magic bytes, or size)
    """
    # Check file exists
    if not tar_path.exists():
        raise FileNotFoundError(f"Tarball file not found: {tar_path}")

    # Check if it's a file, not directory
    if not tar_path.is_file():
        raise ValueError(f"Path is not a file: {tar_path}")

    # Check extension (check filename only, not full path)
    if not any(tar_path.name.endswith(ext) for ext in VALID_TARBALL_EXTENSIONS):
        raise ValueError(
            f"Invalid file extension. Expected one of {VALID_TARBALL_EXTENSIONS}, "
            f"got: {tar_path.suffix}"
        )

    # Check magic bytes (first 2 bytes should be gzip signature)
    with tar_path.open("rb") as f:
        magic = f.read(2)
        if len(magic) < 2 or (magic[0], magic[1]) != GZIP_MAGIC_BYTES:
            raise ValueError(
                f"File is not a valid gzip file. Expected magic bytes "
                f"{GZIP_MAGIC_BYTES}, got: {tuple(magic) if magic else 'empty file'}"
            )

    # Check file size
    size_bytes = tar_path.stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    if size_mb > MAX_TARBALL_SIZE_MB:
        raise ValueError(
            f"Tarball exceeds maximum size. "
            f"File size: {size_mb:.2f}MB, Max: {MAX_TARBALL_SIZE_MB}MB"
        )


class FlashApp:
    """Flash app resource for managing applications, environments, and builds.

    FlashApp provides the interface for Flash application lifecycle management including:
    - Creating and managing flash apps
    - Managing environments within apps
    - Uploading and deploying builds
    - Registering endpoints and network volumes to environments

    Lifecycle Management:
        - Constructor (__init__): Creates instance without I/O by default
        - Factory methods (from_name, create, get_or_create): Recommended for async contexts
        - Hydration: Lazy-loads app ID from server via _hydrate()
        - All API methods call _hydrate() automatically before execution

    Thread Safety:
        - Hydration is protected by asyncio.Lock to prevent concurrent API calls
        - Safe to call _hydrate() multiple times from different coroutines
        - All async methods are safe for concurrent use after hydration

    Usage Patterns:
        # Factory method (recommended in async context)
        app = await FlashApp.from_name("my-app")

        # Constructor with eager hydration (blocks, creates event loop)
        app = FlashApp("my-app", eager_hydrate=True)

        # Constructor without hydration (deferred until first API call)
        app = FlashApp("my-app")
        await app._hydrate()  # Explicit hydration

    GraphQL Query Philosophy:
        - List operations fetch only top-level attributes
        - Child resources queried separately by ID or name
        - Direct queries fetch one level deeper (app + envs/builds, not env resources)
    """

    def __init__(self, name: str, id: Optional[str] = "", eager_hydrate: bool = False):
        self.name: str = name
        self.id: Optional[str] = id
        self.resources: Dict[str, "ServerlessResource"] = {}
        self._hydrated = False
        self._hydrate_lock = asyncio.Lock()
        if eager_hydrate:
            asyncio.run(self._hydrate())

    def remote(self, *args, **kwargs):
        from runpod_flash.client import remote as remote_decorator

        resource_config = kwargs.get("resource_config")

        if resource_config is None and args:
            candidate = args[0]
            if hasattr(candidate, "resource_id"):
                self.resources[candidate.resource_id] = candidate

        return remote_decorator(*args, **kwargs)

    async def _hydrate(self) -> None:
        """Ensure app is loaded from the server or created if it doesn't exist.

        This method handles the lazy-loading logic for FlashApp instances.
        If the app already exists on the server, it retrieves its ID.
        If it doesn't exist, it creates a new app with the given name.

        Thread-safe: Uses asyncio.Lock to prevent concurrent hydration attempts.

        Returns:
            None (modifies self.id and self._hydrated in-place)
        """
        async with self._hydrate_lock:
            if self._hydrated:
                return

            async with RunpodGraphQLClient() as client:
                try:
                    result = await client.get_flash_app_by_name(self.name)
                    found_id = result["id"]

                    # if an id is attached to instance check if it makes sense
                    if self.id:
                        if self.id != found_id:
                            raise ValueError(
                                "provided id for app class does not match existing app resource."
                            )
                        self._hydrated = True
                        return
                    self.id = found_id
                    self._hydrated = True
                    return

                except Exception as exc:
                    if "app not found" not in str(exc).lower():
                        raise
                result = await client.create_flash_app({"name": self.name})
                self.id = result["id"]

            self._hydrated = True
            return

    async def _get_id_by_name(self) -> str:
        """Get the app ID from the server by name.

        Returns:
            The app ID string

        Raises:
            FlashAppNotFoundError: If the app is not found on the server
        """
        async with RunpodGraphQLClient() as client:
            result = await client.get_flash_app_by_name(self.name)
        if not result.get("id"):
            raise FlashAppNotFoundError(f"Flash app '{self.name}' not found")
        return result["id"]

    async def create_environment(self, environment_name: str) -> Dict[str, Any]:
        """Create an environment within an app.

        Args:
            environment_name: Name for the new environment

        Returns:
            Dictionary containing environment data including id and name

        Raises:
            RuntimeError: If app is not hydrated (no ID available)
        """
        await self._hydrate()
        async with RunpodGraphQLClient() as client:
            result = await client.create_flash_environment(
                {"flashAppId": self.id, "name": environment_name}
            )
        return result

    async def _get_tarball_upload_url(self, tarball_size: int) -> Dict[str, str]:
        """Get a pre-signed URL for uploading a build tarball.

        Args:
            tarball_size: Size of the tarball in bytes

        Returns:
            Dictionary with 'uploadUrl' and 'objectKey' keys

        Raises:
            RuntimeError: If app is not hydrated (no ID available)
        """
        await self._hydrate()
        async with RunpodGraphQLClient() as client:
            return await client.prepare_artifact_upload(
                {"flashAppId": self.id, "tarballSize": tarball_size}
            )

    async def _get_active_artifact(self, environment_id: str) -> Dict[str, Any]:
        """Get the active artifact for an environment.

        Args:
            environment_id: ID of the environment

        Returns:
            Dictionary containing artifact information including downloadUrl

        Raises:
            RuntimeError: If app is not hydrated (no ID available)
            ValueError: If environment has no active artifact
        """
        await self._hydrate()
        async with RunpodGraphQLClient() as client:
            result = await client.get_flash_artifact_url(environment_id)
            if not result.get("activeArtifact"):
                raise ValueError(
                    f"No active artifact found for environment ID: {environment_id}"
                )
            return result["activeArtifact"]

    async def deploy_build_to_environment(
        self,
        build_id: str,
        environment_id: Optional[str] = "",
        environment_name: Optional[str] = "",
    ) -> Dict[str, Any]:
        """Deploy a build to an environment.

        Args:
            build_id: ID of the build to deploy
            environment_id: ID of the environment (exclusive with environment_name)
            environment_name: Name of the environment (exclusive with environment_id)

        Returns:
            Dictionary containing deployment result

        Raises:
            ValueError: If both or neither environment_id and environment_name are provided
            RuntimeError: If app is not hydrated (no ID available)
        """
        _validate_exclusive_params(
            environment_id, environment_name, "environment_id", "environment_name"
        )

        await self._hydrate()
        async with RunpodGraphQLClient() as client:
            if not environment_id:
                environment = await client.get_flash_environment_by_name(
                    {"flashAppId": self.id, "name": environment_name}
                )
                environment_id = environment["id"]
            result = await client.deploy_build_to_environment(
                {"flashEnvironmentId": environment_id, "flashBuildId": build_id}
            )
            return result

    async def download_tarball(self, environment_id: str, dest_file: str) -> None:
        """Download the active build tarball from an environment.

        Args:
            environment_id: ID of the environment to download from
            dest_file: Path where the tarball should be saved

        Raises:
            RuntimeError: If app is not hydrated (no ID available)
            ValueError: If environment has no active artifact
            requests.HTTPError: If download fails
        """
        from runpod_flash.core.utils.http import get_authenticated_requests_session

        await self._hydrate()
        result = await self._get_active_artifact(environment_id)
        url = result["downloadUrl"]

        with open(dest_file, "wb") as stream:
            with get_authenticated_requests_session() as session:
                with session.get(url, stream=True) as resp:
                    resp.raise_for_status()
                    for chunk in resp.iter_content():
                        if chunk:
                            stream.write(chunk)

    async def _finalize_upload_build(
        self, object_key: str, manifest: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Finalize the upload of a build tarball.

        After uploading the tarball to the pre-signed URL, this method
        must be called to inform the server that the upload is complete.

        Args:
            object_key: The object key returned by _get_tarball_upload_url
            manifest: The manifest dictionary (read from .flash/flash_manifest.json)

        Returns:
            Dictionary containing build information including the build ID

        Raises:
            RuntimeError: If app is not hydrated (no ID available)
        """
        await self._hydrate()
        async with RunpodGraphQLClient() as client:
            result = await client.finalize_artifact_upload(
                {"flashAppId": self.id, "objectKey": object_key, "manifest": manifest}
            )
            return result

    async def _register_endpoint_to_environment(
        self, environment_id: str, endpoint_id: str
    ) -> Dict[str, Any]:
        """Register a serverless endpoint to an environment.

        Args:
            environment_id: ID of the environment
            endpoint_id: ID of the endpoint to register

        Returns:
            Dictionary containing registration result

        Raises:
            RuntimeError: If app is not hydrated (no ID available)
        """
        await self._hydrate()
        async with RunpodGraphQLClient() as client:
            result = await client.register_endpoint_to_environment(
                {"flashEnvironmentId": environment_id, "endpointId": endpoint_id}
            )
            return result

    async def _register_network_volume_to_environment(
        self, environment_id: str, network_volume_id: str
    ) -> Dict[str, Any]:
        """Register a network volume to an environment.

        Args:
            environment_id: ID of the environment
            network_volume_id: ID of the network volume to register

        Returns:
            Dictionary containing registration result

        Raises:
            RuntimeError: If app is not hydrated (no ID available)
        """
        await self._hydrate()
        async with RunpodGraphQLClient() as client:
            result = await client.register_network_volume_to_environment(
                {
                    "flashEnvironmentId": environment_id,
                    "networkVolumeId": network_volume_id,
                }
            )
            return result

    async def upload_build(self, tar_path: Union[str, Path]) -> Dict[str, Any]:
        """Upload a build tarball to the server.

        Validates the tarball file before upload (extension, magic bytes, size limits).
        Manifest is read from .flash/flash_manifest.json during deployment, not extracted
        from tarball.

        Args:
            tar_path: Path to the tarball file (string or Path object)
                     Must be .tar.gz or .tgz, under 500MB

        Returns:
            Dictionary containing build information including the build ID

        Raises:
            RuntimeError: If app is not hydrated (no ID available)
            FileNotFoundError: If tar_path does not exist
            ValueError: If file is invalid (extension, magic bytes, or size)
            requests.HTTPError: If upload fails

        TODO: Add integration tests for tarball upload flow including:
              - Network failures and retry behavior
              - Large file uploads (edge cases near size limit)
              - Corrupted tarball handling
              - Pre-signed URL expiration scenarios
        """
        # Convert to Path and validate before hydrating
        if isinstance(tar_path, str):
            tar_path = Path(tar_path)
        _validate_tarball_file(tar_path)

        # Read manifest from .flash/flash_manifest.json
        manifest_path = Path.cwd() / ".flash" / "flash_manifest.json"
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"Manifest not found at {manifest_path}. Run 'flash build' first."
            ) from e
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid manifest JSON at {manifest_path}: {e}") from e

        from runpod_flash.core.utils.http import get_authenticated_requests_session

        await self._hydrate()
        tarball_size = tar_path.stat().st_size

        result = await self._get_tarball_upload_url(tarball_size)
        url = result["uploadUrl"]
        object_key = result["objectKey"]

        with get_authenticated_requests_session() as session:
            # Override Content-Type for tarball upload
            session.headers["Content-Type"] = TARBALL_CONTENT_TYPE

            with tar_path.open("rb") as fh:
                resp = session.put(url, data=fh)

            try:
                resp.raise_for_status()
            finally:
                resp.close()
        resp = await self._finalize_upload_build(object_key, manifest)
        return resp

    async def _set_environment_state(self, environment_id: str, status: str) -> None:
        """Set the state of an environment.

        Args:
            environment_id: ID of the environment
            status: State to set (e.g., "HEALTHY", "DEPLOYING", "PENDING")

        Raises:
            RuntimeError: If app is not hydrated (no ID available)
        """
        await self._hydrate()
        async with RunpodGraphQLClient() as client:
            await client.set_environment_state(
                {"flashEnvironmentId": environment_id, "status": status}
            )

    async def _get_environment_by_name(self, environment_name: str) -> Dict[str, Any]:
        """Get an environment by name.

        Args:
            environment_name: Name of the environment to retrieve

        Returns:
            Dictionary containing environment data

        Raises:
            RuntimeError: If app is not hydrated (no ID available)
            ValueError: If environment is not found
        """
        await self._hydrate()
        async with RunpodGraphQLClient() as client:
            result = await client.get_flash_environment_by_name(
                {"flashAppId": self.id, "name": environment_name}
            )
            return result["flashEnvironmentByName"]

    async def deploy_resources(self, environment_name: str) -> None:
        """Deploy all registered resources to an environment.

        This method iterates through all resources registered with the app
        (via @remote decorator with resource_config) and deploys them,
        then registers them to the specified environment.

        Args:
            environment_name: Name of the environment to deploy resources to

        Raises:
            RuntimeError: If app is not hydrated (no ID available)
            ValueError: If environment is not found
        """
        await self._hydrate()
        resource_manager = ResourceManager()
        environment = await self._get_environment_by_name(environment_name)

        # NOTE(jhcipar) it's pretty fragile to have client managed state like this
        # we should enforce this on the server side eventually and either debounce or not allow subsequent deploys
        await self._set_environment_state(environment["id"], "DEPLOYING")

        for resource_id, resource in self.resources.items():
            deployed_resource = await resource_manager.get_or_deploy_resource(resource)
            if isinstance(deployed_resource, ServerlessEndpoint):
                if deployed_resource.id:
                    await self._register_endpoint_to_environment(
                        environment["id"], deployed_resource.id
                    )
            if isinstance(deployed_resource, NetworkVolume):
                if deployed_resource.id:
                    await self._register_network_volume_to_environment(
                        environment["id"], deployed_resource.id
                    )

        # NOTE(jhcipar) we should healthcheck endpoints after provisioning them, for right now we just
        # assume this is healthy
        await self._set_environment_state(environment["id"], "HEALTHY")

    @classmethod
    async def from_name(cls, app_name: str) -> "FlashApp":
        async with RunpodGraphQLClient() as client:
            result = await client.get_flash_app_by_name(app_name)
        return cls(app_name, id=result["id"], eager_hydrate=False)

    @classmethod
    async def create(cls, app_name: str) -> "FlashApp":
        async with RunpodGraphQLClient() as client:
            result = await client.create_flash_app({"name": app_name})
        return cls(app_name, id=result["id"], eager_hydrate=False)

    @classmethod
    async def get_or_create(cls, app_name: str) -> "FlashApp":
        async with RunpodGraphQLClient() as client:
            try:
                result = await client.get_flash_app_by_name(app_name)
                return cls(app_name, id=result["id"], eager_hydrate=False)
            except Exception as exc:
                if "app not found" not in str(exc).lower():
                    raise
                result = await client.create_flash_app({"name": app_name})
                return cls(app_name, id=result["id"], eager_hydrate=False)

    @classmethod
    async def create_environment_and_app(
        cls, app_name: str, environment_name: str
    ) -> Tuple["FlashApp", Dict]:
        app = await cls.get_or_create(app_name)
        env = await app.create_environment(environment_name)
        return (app, env)

    @classmethod
    async def list(cls):
        async with RunpodGraphQLClient() as client:
            return await client.list_flash_apps()

    @classmethod
    async def delete(
        cls, app_name: Optional[str] = None, app_id: Optional[str] = None
    ) -> bool:
        _validate_exclusive_params(app_name, app_id, "app_name", "app_id")

        if not app_id:
            if app_name is None:
                raise ValueError("app_name cannot be None when app_id is not provided")
            app = await cls.from_name(app_name)
            app_id = app.id

        if app_id is None:
            raise ValueError("Failed to resolve app_id")

        async with RunpodGraphQLClient() as client:
            result = await client.delete_flash_app(app_id)
        return result.get("success", False)

    async def delete_environment(self, environment_name: str) -> bool:
        """Delete an environment from this flash app.

        Args:
            environment_name: Name of the environment to delete

        Returns:
            True if deletion was successful, False otherwise

        Raises:
            RuntimeError: If app is not hydrated (no ID available)
            ValueError: If environment is not found
        """
        await self._hydrate()
        environment = await self.get_environment_by_name(environment_name)
        environment_id = environment["id"]

        async with RunpodGraphQLClient() as client:
            result = await client.delete_flash_environment(environment_id)
        return result.get("success", False)

    async def get_build(self, build_id: str) -> Dict[str, Any]:
        """Get a build by ID.

        Args:
            build_id: ID of the build to retrieve

        Returns:
            Dictionary containing build data

        Raises:
            RuntimeError: If app is not hydrated (no ID available)
        """
        await self._hydrate()
        async with RunpodGraphQLClient() as client:
            return await client.get_flash_build(build_id)

    async def list_builds(self) -> List[Dict[str, Any]]:
        """List all builds for this app.

        Returns:
            List of dictionaries containing build data

        Raises:
            RuntimeError: If app is not hydrated (no ID available)
        """
        await self._hydrate()
        async with RunpodGraphQLClient() as client:
            return await client.list_flash_builds_by_app_id(self.id)

    async def get_environment_by_name(self, environment_name: str) -> Dict[str, Any]:
        """Get an environment by name (public wrapper for _get_environment_by_name).

        Args:
            environment_name: Name of the environment to retrieve

        Returns:
            Dictionary containing environment data

        Raises:
            RuntimeError: If app is not hydrated (no ID available)
            FlashEnvironmentNotFoundError: If environment is not found
        """
        await self._hydrate()
        async with RunpodGraphQLClient() as client:
            try:
                result = await client.get_flash_environment_by_name(
                    {"flashAppId": self.id, "name": environment_name}
                )
                if result is None:
                    raise FlashEnvironmentNotFoundError(
                        f"Environment '{environment_name}' not found in app '{self.name}'"
                    )
                return result
            except Exception as exc:
                # Convert generic exceptions that indicate "not found" to specific exception
                if "not found" in str(exc).lower():
                    raise FlashEnvironmentNotFoundError(
                        f"Environment '{environment_name}' not found in app '{self.name}'"
                    ) from exc
                raise

    async def list_environments(self) -> List[Dict[str, Any]]:
        """List all environments for this app.

        Returns:
            List of dictionaries containing environment data

        Raises:
            RuntimeError: If app is not hydrated (no ID available)
        """
        await self._hydrate()
        async with RunpodGraphQLClient() as client:
            return await client.list_flash_environments_by_app_id(self.id)

    async def get_build_manifest(self, build_id: str) -> Dict[str, Any]:
        """Retrieve manifest for a specific build.

        Args:
            build_id: ID of the build

        Returns:
            Manifest dictionary (empty dict if manifest is not present)

        Raises:
            RuntimeError: If app is not hydrated
        """
        await self._hydrate()
        async with RunpodGraphQLClient() as client:
            build = await client.get_flash_build(build_id)
            return build.get("manifest", {})

    async def update_build_manifest(
        self, build_id: str, manifest: Dict[str, Any]
    ) -> None:
        """Update manifest for a specific build.

        Args:
            build_id: ID of the build
            manifest: Complete manifest dictionary

        Raises:
            RuntimeError: If app is not hydrated
        """
        await self._hydrate()
        async with RunpodGraphQLClient() as client:
            await client.update_build_manifest(build_id, manifest)
