"""Extended tests for core/api/runpod.py - GraphQL and REST client coverage."""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from runpod_flash.core.api.runpod import (
    RUNPOD_REST_API_URL,
    RunpodGraphQLClient,
    RunpodRestClient,
)
from runpod_flash.core.exceptions import RunpodAPIKeyError
from runpod_flash.runtime.exceptions import GraphQLMutationError, GraphQLQueryError


# ──── GraphQL mutation/query methods ────


class TestGraphQLMutations:
    """Test GraphQL mutation methods via parametrized tests."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name,call_args,mock_response,assert_key,assert_value",
        [
            (
                "update_template",
                ({"name": "my-template"},),
                {"saveTemplate": {"id": "tpl-1", "name": "my-template"}},
                "id",
                "tpl-1",
            ),
            (
                "create_flash_app",
                ({"name": "my-app"},),
                {"createFlashApp": {"id": "app-1", "name": "my-app"}},
                "id",
                "app-1",
            ),
            (
                "create_flash_environment",
                ({"flashAppId": "app-1", "name": "staging"},),
                {"createFlashEnvironment": {"id": "env-1", "name": "staging"}},
                "id",
                "env-1",
            ),
            (
                "register_endpoint_to_environment",
                ({"flashEnvironmentId": "env-1", "endpointId": "ep-1"},),
                {"addEndpointToFlashEnvironment": {"id": "ep-1", "name": "gpu"}},
                "id",
                "ep-1",
            ),
            (
                "register_network_volume_to_environment",
                ({"flashEnvironmentId": "env-1", "networkVolumeId": "nv-1"},),
                {"addNetworkVolumeToFlashEnvironment": {"id": "nv-1", "name": "vol"}},
                "id",
                "nv-1",
            ),
            (
                "set_environment_state",
                ({"flashEnvironmentId": "env-1", "status": "HEALTHY"},),
                {"updateFlashEnvironment": {"id": "env-1", "state": "HEALTHY"}},
                "state",
                "HEALTHY",
            ),
            (
                "prepare_artifact_upload",
                ({"flashAppId": "app-1", "tarballSize": 1024},),
                {
                    "prepareFlashArtifactUpload": {
                        "uploadUrl": "https://s3.example.com/upload",
                        "objectKey": "key-123",
                    }
                },
                "objectKey",
                "key-123",
            ),
            (
                "finalize_artifact_upload",
                ({"flashAppId": "app-1", "objectKey": "key-123", "manifest": {}},),
                {"finalizeFlashArtifactUpload": {"id": "build-1", "manifest": {}}},
                "id",
                "build-1",
            ),
            (
                "deploy_build_to_environment",
                ({"flashEnvironmentId": "env-1", "flashBuildId": "build-1"},),
                {"deployBuildToEnvironment": {"id": "env-1", "name": "staging"}},
                "id",
                "env-1",
            ),
        ],
        ids=lambda x: x if isinstance(x, str) and not x.startswith("{") else "",
    )
    async def test_mutation_success(
        self, method_name, call_args, mock_response, assert_key, assert_value
    ):
        """Mutation methods return expected result from GraphQL response."""
        client = RunpodGraphQLClient(api_key="test")
        with patch.object(client, "_execute_graphql", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            method = getattr(client, method_name)
            result = await method(*call_args)
            assert result[assert_key] == assert_value

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name,call_args",
        [
            ("update_template", ({"name": "bad"},)),
            ("save_endpoint", ({"name": "bad"},)),
        ],
    )
    async def test_mutation_missing_key_raises(self, method_name, call_args):
        """Mutations raise when expected key is missing from response."""
        client = RunpodGraphQLClient(api_key="test")
        with patch.object(client, "_execute_graphql", new_callable=AsyncMock) as mock:
            mock.return_value = {}
            with pytest.raises(Exception, match="Unexpected GraphQL response"):
                await getattr(client, method_name)(*call_args)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name,call_args,mock_response",
        [
            ("delete_flash_app", ("app-1",), {"deleteFlashApp": None}),
            ("delete_flash_environment", ("env-1",), {"deleteFlashEnvironment": None}),
        ],
    )
    async def test_delete_mutations_return_success(
        self, method_name, call_args, mock_response
    ):
        """Delete mutations return success dict."""
        client = RunpodGraphQLClient(api_key="test")
        with patch.object(client, "_execute_graphql", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            result = await getattr(client, method_name)(*call_args)
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_update_build_manifest_success(self):
        client = RunpodGraphQLClient(api_key="test")
        with patch.object(client, "_execute_graphql", new_callable=AsyncMock) as mock:
            mock.return_value = {
                "updateFlashBuildManifest": {"id": "build-1", "manifest": {"v": 1}}
            }
            await client.update_build_manifest("build-1", {"v": 1})

    @pytest.mark.asyncio
    async def test_update_build_manifest_missing_key_raises(self):
        client = RunpodGraphQLClient(api_key="test")
        with patch.object(client, "_execute_graphql", new_callable=AsyncMock) as mock:
            mock.return_value = {}
            with pytest.raises(GraphQLMutationError):
                await client.update_build_manifest("build-1", {"v": 1})


class TestGraphQLQueries:
    """Test GraphQL query methods via parametrized tests."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name,call_args,mock_response,assert_fn",
        [
            (
                "list_flash_apps",
                (),
                {"myself": {"flashApps": [{"id": "app-1", "name": "my-app"}]}},
                lambda r: len(r) == 1,
            ),
            (
                "get_flash_app",
                ({"input": "app-1"},),
                {"flashApp": {"id": "app-1", "name": "my-app"}},
                lambda r: r["id"] == "app-1",
            ),
            (
                "get_flash_app_by_name",
                ("my-app",),
                {"flashAppByName": {"id": "app-1", "name": "my-app"}},
                lambda r: r["name"] == "my-app",
            ),
            (
                "get_flash_environment",
                ({"flashEnvironmentId": "env-1"},),
                {
                    "flashEnvironment": {
                        "id": "env-1",
                        "name": "prod",
                        "state": "HEALTHY",
                    }
                },
                lambda r: r["state"] == "HEALTHY",
            ),
            (
                "get_flash_environment_by_name",
                ({"flashAppId": "app-1", "name": "staging"},),
                {"flashEnvironmentByName": {"id": "env-1", "name": "staging"}},
                lambda r: r["name"] == "staging",
            ),
            (
                "get_flash_build",
                ("build-1",),
                {"flashBuild": {"id": "build-1", "manifest": {}}},
                lambda r: r["id"] == "build-1",
            ),
            (
                "list_flash_builds_by_app_id",
                ("app-1",),
                {"flashApp": {"flashBuilds": [{"id": "b1"}, {"id": "b2"}]}},
                lambda r: len(r) == 2,
            ),
            (
                "list_flash_environments_by_app_id",
                ("app-1",),
                {"flashApp": {"flashEnvironments": [{"id": "e1"}, {"id": "e2"}]}},
                lambda r: len(r) == 2,
            ),
            (
                "get_gpu_types",
                (),
                {"gpuTypes": [{"id": "gpu-1"}]},
                lambda r: len(r) == 1,
            ),
        ],
        ids=lambda x: (
            x
            if isinstance(x, str) and not x.startswith("{") and not x.startswith("(")
            else ""
        ),
    )
    async def test_query_success(
        self, method_name, call_args, mock_response, assert_fn
    ):
        """Query methods return expected result from GraphQL response."""
        client = RunpodGraphQLClient(api_key="test")
        with patch.object(client, "_execute_graphql", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            result = await getattr(client, method_name)(*call_args)
            assert assert_fn(result), f"{method_name} assertion failed on {result}"

    @pytest.mark.asyncio
    async def test_get_flash_build_type_error(self):
        client = RunpodGraphQLClient(api_key="test")
        with pytest.raises(TypeError, match="expects build_id as str"):
            await client.get_flash_build({"id": "build-1"})

    @pytest.mark.asyncio
    async def test_get_flash_build_not_found_raises(self):
        client = RunpodGraphQLClient(api_key="test")
        with patch.object(client, "_execute_graphql", new_callable=AsyncMock) as mock:
            mock.return_value = {}
            with pytest.raises(GraphQLQueryError):
                await client.get_flash_build("build-nonexistent")

    @pytest.mark.asyncio
    async def test_endpoint_exists_handles_api_failure(self):
        """endpoint_exists returns False when API call fails."""
        client = RunpodGraphQLClient(api_key="test")
        with patch.object(client, "_execute_graphql", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("API error")
            result = await client.endpoint_exists("ep-123")
            assert result is False

    @pytest.mark.asyncio
    async def test_get_flash_artifact_url(self):
        client = RunpodGraphQLClient(api_key="test")
        with patch.object(
            client, "get_flash_environment", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {
                "activeArtifact": {"downloadUrl": "https://example.com/dl"}
            }
            result = await client.get_flash_artifact_url("env-1")
            assert "activeArtifact" in result


# ──── REST client ────


class TestRestClientInit:
    """Test RunpodRestClient initialization."""

    def test_init_with_api_key(self):
        client = RunpodRestClient(api_key="test-key")
        assert client.api_key == "test-key"
        assert client.session is None

    def test_init_from_env(self, monkeypatch):
        monkeypatch.setenv("RUNPOD_API_KEY", "env-key")
        client = RunpodRestClient()
        assert client.api_key == "env-key"

    def test_init_no_key_raises(self, monkeypatch):
        monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
        with pytest.raises(RunpodAPIKeyError):
            RunpodRestClient()


class TestRestClientCreateNetworkVolume:
    """Test RunpodRestClient.create_network_volume."""

    @pytest.mark.asyncio
    async def test_create_network_volume(self):
        client = RunpodRestClient(api_key="test")
        with patch.object(client, "_execute_rest", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {"id": "nv-1", "name": "vol"}
            result = await client.create_network_volume({"name": "vol", "size": 10})
            assert result["id"] == "nv-1"
            mock_exec.assert_awaited_once_with(
                "POST",
                f"{RUNPOD_REST_API_URL}/networkvolumes",
                {"name": "vol", "size": 10},
            )


class TestRestClientListNetworkVolumes:
    """Test RunpodRestClient.list_network_volumes."""

    @pytest.mark.asyncio
    async def test_list_network_volumes_list_format(self):
        client = RunpodRestClient(api_key="test")
        with patch.object(client, "_execute_rest", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = [{"id": "nv-1"}, {"id": "nv-2"}]
            result = await client.list_network_volumes()
            assert len(result) == 2
            mock_exec.assert_awaited_once_with(
                "GET", f"{RUNPOD_REST_API_URL}/networkvolumes"
            )

    @pytest.mark.asyncio
    async def test_list_network_volumes_dict_format(self):
        client = RunpodRestClient(api_key="test")
        with patch.object(client, "_execute_rest", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {"networkVolumes": [{"id": "nv-1"}]}
            result = await client.list_network_volumes()
            assert result["networkVolumes"][0]["id"] == "nv-1"


class TestRestClientContextManager:
    """Test RunpodRestClient context manager and close."""

    @pytest.mark.asyncio
    async def test_rest_context_manager(self):
        """Context manager creates and closes session."""
        async with RunpodRestClient(api_key="test") as client:
            assert client.api_key == "test"

    @pytest.mark.asyncio
    async def test_close_with_no_session(self):
        """close() when no session exists doesn't raise."""
        client = RunpodRestClient(api_key="test")
        await client.close()  # Should not raise


class TestRestClientExecuteRest:
    """Test RunpodRestClient._execute_rest error handling."""

    @pytest.mark.asyncio
    async def test_execute_rest_http_error(self):
        """HTTP 4xx/5xx raises exception."""
        client = RunpodRestClient(api_key="test")
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.json = AsyncMock(return_value={"error": "server error"})

        mock_ctx_mgr = MagicMock()
        mock_ctx_mgr.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx_mgr.__aexit__ = AsyncMock(return_value=False)

        with patch.object(
            client, "_get_session", new_callable=AsyncMock
        ) as mock_session:
            mock_session_instance = MagicMock()
            mock_session_instance.request = MagicMock(return_value=mock_ctx_mgr)
            mock_session.return_value = mock_session_instance

            with pytest.raises(Exception, match="REST request failed: 500"):
                await client._execute_rest("GET", "https://example.com/api")

    @pytest.mark.asyncio
    async def test_execute_rest_network_error(self):
        """Network errors raise exception."""
        client = RunpodRestClient(api_key="test")
        with patch.object(
            client, "_get_session", new_callable=AsyncMock
        ) as mock_session:
            mock_session_instance = MagicMock()
            mock_session_instance.request.side_effect = aiohttp.ClientError("timeout")
            mock_session.return_value = mock_session_instance

            with pytest.raises(Exception, match="HTTP request failed"):
                await client._execute_rest("GET", "https://example.com/api")
