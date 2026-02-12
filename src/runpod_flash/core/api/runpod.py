"""
Direct GraphQL communication with Runpod API.
Bypasses the outdated runpod-python SDK limitations.
"""

import json
import logging
import os
from typing import Any, Dict, Optional, List

import aiohttp
from aiohttp.resolver import ThreadedResolver

from runpod_flash.core.exceptions import RunpodAPIKeyError
from runpod_flash.runtime.exceptions import GraphQLMutationError, GraphQLQueryError

log = logging.getLogger(__name__)

RUNPOD_API_BASE_URL = os.environ.get("RUNPOD_API_BASE_URL", "https://api.runpod.io")
RUNPOD_REST_API_URL = os.environ.get("RUNPOD_REST_API_URL", "https://rest.runpod.io/v1")

# Sensitive fields that should be redacted from logs (pre-signed URLs, tokens, etc.)
SENSITIVE_FIELDS = {"uploadUrl", "downloadUrl", "presignedUrl"}


def _sanitize_for_logging(data: Any, redaction_text: str = "<REDACTED>") -> Any:
    """Recursively sanitize sensitive fields from data structures before logging.

    Pre-signed URLs and other sensitive fields should not be logged as they
    are temporary credentials that could be misused if exposed.

    Args:
        data: Data structure to sanitize (dict, list, or primitive)
        redaction_text: Text to replace sensitive values with

    Returns:
        Sanitized copy of the data structure
    """
    if isinstance(data, dict):
        return {
            key: (
                redaction_text
                if key in SENSITIVE_FIELDS
                else _sanitize_for_logging(value, redaction_text)
            )
            for key, value in data.items()
        }
    elif isinstance(data, list):
        return [_sanitize_for_logging(item, redaction_text) for item in data]
    else:
        return data


class RunpodGraphQLClient:
    """
    Runpod GraphQL client for Runpod API.
    Communicates directly with Runpod's GraphQL endpoint without SDK limitations.
    """

    GRAPHQL_URL = f"{RUNPOD_API_BASE_URL}/graphql"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("RUNPOD_API_KEY")
        if not self.api_key:
            raise RunpodAPIKeyError()

        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=300)  # 5 minute timeout
            connector = aiohttp.TCPConnector(resolver=ThreadedResolver())
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                connector=connector,
            )
        return self.session

    async def _execute_graphql(
        self, query: str, variables: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute a GraphQL query/mutation."""
        session = await self._get_session()

        payload = {"query": query, "variables": variables or {}}

        log.debug(f"GraphQL Query: {query}")
        sanitized_vars = _sanitize_for_logging(variables)
        log.debug(f"GraphQL Variables: {json.dumps(sanitized_vars, indent=2)}")

        try:
            async with session.post(self.GRAPHQL_URL, json=payload) as response:
                response_data = await response.json()

                log.debug(f"GraphQL Response Status: {response.status}")
                sanitized_response = _sanitize_for_logging(response_data)
                log.debug(
                    f"GraphQL Response: {json.dumps(sanitized_response, indent=2)}"
                )

                if response.status >= 400:
                    sanitized_err = _sanitize_for_logging(response_data)
                    raise Exception(
                        f"GraphQL request failed: {response.status} - {sanitized_err}"
                    )

                if "errors" in response_data:
                    errors = response_data["errors"]
                    sanitized_errors = _sanitize_for_logging(errors)
                    error_msg = "; ".join(
                        [e.get("message", str(e)) for e in sanitized_errors]
                    )
                    raise Exception(f"GraphQL errors: {error_msg}")

                return response_data.get("data", {})

        except aiohttp.ClientError as e:
            log.error(f"HTTP client error: {e}")
            raise Exception(f"HTTP request failed: {e}")


    async def update_template(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        mutation = """
        mutation saveTemplate($input: SaveTemplateInput) {
            saveTemplate(input: $input) {
                id
                containerDiskInGb
                dockerArgs
                env {
                    key
                    value
                }
                imageName
                name
                readme
            }
        }
        """
        
        variables = {"input": input_data}

        log.debug(
            f"Updating template with GraphQL: {input_data.get('name', 'unnamed')}"
        )

        result = await self._execute_graphql(mutation, variables)

        if "saveTemplate" not in result:
            raise Exception("Unexpected GraphQL response structure")

        template_data = result["saveTemplate"]
        log.info(
            f"Updated template: {template_data.get('id', 'unknown')} - {template_data.get('name', 'unnamed')}"
        )

        return template_data

    async def save_endpoint(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create or update a serverless endpoint using direct GraphQL mutation.
        When 'id' is included in the input, updates the existing endpoint.
        Supports both GPU and CPU endpoints with full field support.
        """
        # GraphQL mutation for saveEndpoint (based on actual schema)
        mutation = """
        mutation saveEndpoint($input: EndpointInput!) {
            saveEndpoint(input: $input) {
                aiKey
                gpuIds
                id
                idleTimeout
                locations
                name
                networkVolumeId
                flashEnvironmentId
                scalerType
                scalerValue
                templateId
                type
                userId
                version
                workersMax
                workersMin
                workersStandby
                workersPFBTarget
                gpuCount
                allowedCudaVersions
                executionTimeoutMs
                instanceIds
                activeBuildid
                idePodId
            }
        }
        """

        variables = {"input": input_data}

        log.debug(f"Saving endpoint with GraphQL: {input_data.get('name', 'unnamed')}")

        result = await self._execute_graphql(mutation, variables)

        if "saveEndpoint" not in result:
            raise Exception("Unexpected GraphQL response structure")

        endpoint_data = result["saveEndpoint"]
        log.info(
            f"Saved endpoint: {endpoint_data.get('id', 'unknown')} - {endpoint_data.get('name', 'unnamed')}"
        )

        return endpoint_data

    async def get_cpu_types(self) -> Dict[str, Any]:
        """Get available CPU types."""
        query = """
        query getCpuTypes {
            cpuTypes {
                id
                displayName
                manufacturer
                cores
                threadsPerCore
                groupId
            }
        }
        """

        result = await self._execute_graphql(query)
        return result.get("cpuTypes", [])

    async def get_gpu_types(
        self, gpu_filter: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Get available GPU types."""
        query = """
        query getGpuTypes($input: GpuTypeFilter) {
            gpuTypes(input: $input) {
                id
                displayName
                manufacturer
                memoryInGb
                cudaCores
                secureCloud
                communityCloud
                securePrice
                communityPrice
                communitySpotPrice
                secureSpotPrice
                maxGpuCount
                maxGpuCountCommunityCloud
                maxGpuCountSecureCloud
                minPodGpuCount
                nodeGroupGpuSizes
                throughput
            }
        }
        """

        variables = {"input": gpu_filter} if gpu_filter else {}
        result = await self._execute_graphql(query, variables)
        return result.get("gpuTypes", [])

    async def get_endpoint(self, endpoint_id: str) -> Dict[str, Any]:
        """Get endpoint details."""
        # Note: The schema doesn't show a specific endpoint query
        # This would need to be implemented if such query exists
        raise NotImplementedError("Get endpoint query not available in current schema")

    async def delete_endpoint(self, endpoint_id: str) -> Dict[str, Any]:
        """Delete a serverless endpoint."""
        mutation = """
        mutation deleteEndpoint($id: String!) {
            deleteEndpoint(id: $id)
        }
        """

        variables = {"id": endpoint_id}
        log.info(f"Deleting endpoint: {endpoint_id}")

        result = await self._execute_graphql(mutation, variables)

        # If _execute_graphql didn't raise an exception, the deletion succeeded.
        # The GraphQL mutation returns null on success, but presence of the key
        # (even with null value) indicates the mutation executed.
        # If the mutation failed, _execute_graphql would have raised an exception.

        return {"success": "deleteEndpoint" in result}

    async def list_flash_apps(self) -> List[Dict]:
        """
        List all flash apps in Runpod.
        """
        log.debug("Listing Flash apps")
        query = """
        query getFlashApps {
                myself {
                    flashApps {
                        id
                        name
                        flashEnvironments {
                            id
                            name
                            state
                            createdAt
                            activeBuildId
                        }
                        flashBuilds {
                            id
                            createdAt
                        }
                    }
                }
                }
        """

        result = await self._execute_graphql(query)
        return result["myself"].get("flashApps", [])

    async def prepare_artifact_upload(
        self, input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        mutation = """
        mutation PrepareArtifactUpload($input: PrepareFlashArtifactUploadInput!) {
                prepareFlashArtifactUpload(input: $input) {
                    uploadUrl
                    objectKey
                    expiresAt
                    }
                }
        """
        variables = {"input": input_data}

        log.debug(f"Preparing upload url for flash environment: {input_data}")

        result = await self._execute_graphql(mutation, variables)
        return result["prepareFlashArtifactUpload"]

    async def finalize_artifact_upload(
        self, input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        mutation = """
        mutation FinalizeArtifactUpload($input: FinalizeFlashArtifactUploadInput!) {
                finalizeFlashArtifactUpload(input: $input) {
                    id
                    manifest
                    }
                }
        """
        variables = {"input": input_data}

        log.debug(f"finalizing upload for flash app: {input_data}")

        result = await self._execute_graphql(mutation, variables)
        return result["finalizeFlashArtifactUpload"]

    async def get_flash_app(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        query = """
        query getFlashApp($input: String!) {
                flashApp(flashAppId: $input) {
                    id
                    name
                    flashEnvironments {
                        id
                        name
                        state
                    }
                flashBuilds {
                    id
                    objectKey
                    createdAt
                }
            }
        }
        """
        variables = {"input": input_data}

        log.debug(f"Fetching flash app for input: {input_data}")
        result = await self._execute_graphql(query, variables)
        return result["flashApp"]

    async def get_flash_app_by_name(self, app_name: str) -> Dict[str, Any]:
        query = """
        query getFlashAppByName($flashAppName: String!) {
                flashAppByName(flashAppName: $flashAppName) {
                    id
                    name
                    flashEnvironments {
                        id
                        name
                        state
                        activeBuildId
                        createdAt
                    }
                flashBuilds {
                    id
                    objectKey
                    createdAt
                }
            }
        }
        """
        variables = {"flashAppName": app_name}

        log.debug(f"Fetching flash app by name for input: {app_name}")
        result = await self._execute_graphql(query, variables)
        return result["flashAppByName"]

    async def get_flash_environment(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        query = """
        query getFlashEnvironment($flashEnvironmentId: String!) {
                flashEnvironment(flashEnvironmentId: $flashEnvironmentId) {
                    id
                    name
                    state
                    activeBuildId
                    createdAt
                    endpoints {
                        id
                        name
                    }
                    networkVolumes {
                        id
                        name
                    }
                }
            }
        """
        variables = {**input_data}

        log.debug(f"Fetching flash environment for input: {variables}")
        result = await self._execute_graphql(query, variables)
        return result["flashEnvironment"]

    async def get_flash_environment_by_name(
        self, input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        query = """
        query getFlashEnvironmentByName($input: FlashEnvironmentByNameInput!) {
                flashEnvironmentByName(input: $input) {
                    id
                    name
                    state
                    activeBuildId
                    endpoints {
                        id
                        name
                    }
                    networkVolumes {
                        id
                        name
                    }
                }
            }
        """
        variables = {"input": input_data}

        log.debug(f"Fetching flash environment by name for input: {variables}")
        result = await self._execute_graphql(query, variables)

        return result["flashEnvironmentByName"]

    async def update_build_manifest(
        self,
        build_id: str,
        manifest: Dict[str, Any],
    ) -> None:
        mutation = """
        mutation updateFlashBuildManifest($input: UpdateFlashBuildManifestInput!) {
            updateFlashBuildManifest(input: $input) {
                id
                manifest
            }
        }
        """
        variables = {"input": {"flashBuildId": build_id, "manifest": manifest}}
        result = await self._execute_graphql(mutation, variables)

        if "updateFlashBuildManifest" not in result:
            raise GraphQLMutationError(
                f"updateFlashBuildManifest mutation failed for build {build_id}. "
                f"Expected 'updateFlashBuildManifest' in response, got: {list(result.keys())}"
            )

    async def get_flash_artifact_url(self, environment_id: str) -> Dict[str, Any]:
        result = await self.get_flash_environment(
            {"flashEnvironmentId": environment_id}
        )
        return result

    async def deploy_build_to_environment(
        self, input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        # TODO(jhcipar) should we not generate a presigned url when promoting a build here?
        mutation = """
        mutation deployBuildToEnvironment($input: DeployBuildToEnvironmentInput!) {
                deployBuildToEnvironment(input: $input) {
                    id
                    name
                    activeArtifact {
                        objectKey
                        downloadUrl
                        expiresAt
                        }
                    }
                }
        """

        variables = {"input": input_data}

        log.debug(f"Deploying flash environment with vars: {input_data}")

        result = await self._execute_graphql(mutation, variables)
        return result["deployBuildToEnvironment"]

    async def create_flash_app(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new flash app in Runpod."""
        log.debug(f"creating flash app with name {input_data.get('name')}")

        mutation = """
        mutation createFlashApp($input: CreateFlashAppInput!) {
                createFlashApp(input: $input) {
                    id
                    name
                    }
                }
        """

        variables = {"input": input_data}

        log.debug(
            f"Creating flash app with GraphQL: {input_data.get('name', 'unnamed')}"
        )

        result = await self._execute_graphql(mutation, variables)

        return result["createFlashApp"]

    async def create_flash_environment(
        self, input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create an environment within a flash app."""
        log.debug(f"creating flash environment with name {input_data.get('name')}")

        mutation = """
        mutation createFlashEnvironment($input: CreateFlashEnvironmentInput!) {
                createFlashEnvironment(input: $input) {
                    id
                    name
                    }
                }
        """

        variables = {"input": input_data}

        log.debug(
            f"Creating flash environment with GraphQL: {input_data.get('name', 'unnamed')}"
        )

        result = await self._execute_graphql(mutation, variables)

        return result["createFlashEnvironment"]

    async def register_endpoint_to_environment(
        self, input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Register an endpoint to a Flash environment"""

        log.debug(
            f"Registering endpoint to flash environment with input data: {input_data}"
        )

        mutation = """
        mutation addEndpointToFlashEnvironment($input: AddEndpointToEnvironmentInput!) {
                addEndpointToFlashEnvironment(input: $input) {
                    id
                    name
                    flashEnvironmentId
                    }
                }
        """

        variables = {"input": input_data}

        result = await self._execute_graphql(mutation, variables)

        return result["addEndpointToFlashEnvironment"]

    async def register_network_volume_to_environment(
        self, input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Register an endpoint to a Flash environment"""

        log.debug(
            f"Registering endpoint to flash environment with input data: {input_data}"
        )

        mutation = """
        mutation addNetworkVolumeToFlashEnvironment($input: AddNetworkVolumeToEnvironmentInput!) {
                addNetworkVolumeToFlashEnvironment(input: $input) {
                    id
                    name
                    flashEnvironmentId
                    }
                }
        """

        variables = {"input": input_data}

        result = await self._execute_graphql(mutation, variables)

        return result["addNetworkVolumeToFlashEnvironment"]

    async def set_environment_state(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        log.debug(f"Setting Flash environment status with input data: {input_data}")

        mutation = """
        mutation updateFlashEnvironment($input: UpdateFlashEnvironmentInput!) {
                updateFlashEnvironment(input: $input) {
                    id
                    name
                    state
                    }
                }
        """

        variables = {"input": input_data}

        result = await self._execute_graphql(mutation, variables)

        return result["updateFlashEnvironment"]

    async def get_flash_build(self, build_id: str) -> Dict[str, Any]:
        """Fetch flash build by ID.

        Args:
            build_id: Build ID string (UUID format).

        Returns:
            Build data including id and manifest.

        Raises:
            TypeError: If build_id is not a string.
            GraphQLQueryError: If build not found or query fails.

        Note:
            API changed in PR #144:
            - Previously accepted Dict[str, Any], now requires string build_id directly
            - Query now requests 'manifest' field instead of 'name' field
        """
        if not isinstance(build_id, str):
            raise TypeError(
                f"get_flash_build() expects build_id as str, got {type(build_id).__name__}. "
                f"API changed in PR #144 - update caller to pass build_id string directly."
            )

        query = """
        query getFlashBuild($input: String!) {
                flashBuild(flashBuildId: $input) {
                    id
                    manifest
            }
        }
        """
        variables = {"input": build_id}

        log.debug(f"Fetching flash build for input: {build_id}")
        result = await self._execute_graphql(query, variables)

        if "flashBuild" not in result:
            raise GraphQLQueryError(
                f"get_flash_build query failed for build {build_id}. "
                f"Expected 'flashBuild' in response, got: {list(result.keys())}"
            )

        return result["flashBuild"]

    async def list_flash_builds_by_app_id(self, app_id: str) -> List[Dict[str, Any]]:
        """List all builds for a flash app by app ID (optimized query).

        Args:
            app_id: The flash app ID

        Returns:
            List of build dictionaries with id, objectKey, createdAt fields
        """
        query = """
        query listFlashBuilds($flashAppId: String!) {
            flashApp(flashAppId: $flashAppId) {
                flashBuilds {
                    id
                    objectKey
                    createdAt
                }
            }
        }
        """
        variables = {"flashAppId": app_id}

        log.debug(f"Listing flash builds for app: {app_id}")
        result = await self._execute_graphql(query, variables)
        return result["flashApp"]["flashBuilds"]

    async def list_flash_environments_by_app_id(
        self, app_id: str
    ) -> List[Dict[str, Any]]:
        """List all environments for a flash app by app ID (optimized query).

        Args:
            app_id: The flash app ID

        Returns:
            List of environment dictionaries with id, name, state, activeBuildId, createdAt fields
        """
        query = """
        query listFlashEnvironments($flashAppId: String!) {
            flashApp(flashAppId: $flashAppId) {
                flashEnvironments {
                    id
                    name
                    state
                    activeBuildId
                    createdAt
                }
            }
        }
        """
        variables = {"flashAppId": app_id}

        log.debug(f"Listing flash environments for app: {app_id}")
        result = await self._execute_graphql(query, variables)
        return result["flashApp"]["flashEnvironments"]

    async def delete_flash_app(self, app_id: str) -> Dict[str, Any]:
        mutation = """
        mutation deleteFlashApp($flashAppId: String!) {
            deleteFlashApp(flashAppId: $flashAppId)
        }
        """

        variables = {"flashAppId": app_id}
        log.info(f"Deleting flash app: {app_id}")

        result = await self._execute_graphql(mutation, variables)
        return {"success": "deleteFlashApp" in result}

    async def delete_flash_environment(self, environment_id: str) -> Dict[str, Any]:
        """Delete a flash environment."""
        mutation = """
        mutation deleteFlashEnvironment($flashEnvironmentId: String!) {
            deleteFlashEnvironment(flashEnvironmentId: $flashEnvironmentId)
        }
        """

        variables = {"flashEnvironmentId": environment_id}
        log.info(f"Deleting flash environment: {environment_id}")

        result = await self._execute_graphql(mutation, variables)
        return {"success": "deleteFlashEnvironment" in result}

    async def endpoint_exists(self, endpoint_id: str) -> bool:
        """Check if an endpoint exists by querying the user's endpoint list."""
        query = """
        query {
            myself {
                endpoints {
                    id
                }
            }
        }
        """

        try:
            result = await self._execute_graphql(query)
            endpoints = result.get("myself", {}).get("endpoints", [])
            endpoint_ids = [ep.get("id") for ep in endpoints]
            exists = endpoint_id in endpoint_ids

            log.debug(f"Endpoint {endpoint_id} exists: {exists}")
            return exists
        except Exception as e:
            log.error(f"Error checking endpoint existence: {e}")
            return False

    async def close(self):
        """Close the HTTP session."""
        if self.session and not self.session.closed:
            await self.session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


class RunpodRestClient:
    """
    Runpod REST client for Runpod API.
    Provides methods to interact with Runpod's REST endpoints.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("RUNPOD_API_KEY")
        if not self.api_key:
            raise RunpodAPIKeyError()

        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=300)  # 5 minute timeout
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self.session

    async def _execute_rest(
        self, method: str, url: str, data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute a REST API request."""
        session = await self._get_session()

        log.debug(f"REST Request: {method} {url}")
        log.debug(f"REST Data: {json.dumps(data, indent=2) if data else 'None'}")

        try:
            async with session.request(method, url, json=data) as response:
                response_data = await response.json()

                log.debug(f"REST Response Status: {response.status}")
                log.debug(f"REST Response: {json.dumps(response_data, indent=2)}")

                if response.status >= 400:
                    raise Exception(
                        f"REST request failed: {response.status} - {response_data}"
                    )

                return response_data

        except aiohttp.ClientError as e:
            log.error(f"HTTP client error: {e}")
            raise Exception(f"HTTP request failed: {e}")

    async def create_network_volume(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a network volume in Runpod."""
        log.debug(f"Creating network volume: {payload.get('name', 'unnamed')}")

        result = await self._execute_rest(
            "POST", f"{RUNPOD_REST_API_URL}/networkvolumes", payload
        )

        log.info(
            f"Created network volume: {result.get('id', 'unknown')} - {result.get('name', 'unnamed')}"
        )

        return result

    async def list_network_volumes(self) -> Dict[str, Any]:
        """
        List all network volumes in Runpod.

        Returns:
            List of network volume objects or dict containing networkVolumes key.
            The API may return either format depending on version.
        """
        log.debug("Listing network volumes")

        result = await self._execute_rest(
            "GET", f"{RUNPOD_REST_API_URL}/networkvolumes"
        )

        # Handle both list and dict responses
        if isinstance(result, list):
            volume_count = len(result)
        else:
            volume_count = len(result.get("networkVolumes", []))

        log.debug(f"Listed {volume_count} network volumes")

        return result

    async def close(self):
        """Close the HTTP session."""
        if self.session and not self.session.closed:
            await self.session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
