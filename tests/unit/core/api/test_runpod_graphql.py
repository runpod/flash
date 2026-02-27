"""Tests for RunpodGraphQLClient."""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from runpod_flash.core.api.runpod import (
    RunpodGraphQLClient,
    _sanitize_for_logging,
)
from runpod_flash.core.exceptions import RunpodAPIKeyError


class TestSanitizeForLogging:
    """Test sanitization helper function."""

    def test_sanitize_dict_with_sensitive_fields(self):
        """Test sanitizing dictionary with sensitive fields."""
        data = {
            "uploadUrl": "https://s3.amazonaws.com/secret-url",
            "safe_field": "visible_data",
            "downloadUrl": "https://download.url/secret",
        }

        sanitized = _sanitize_for_logging(data)

        assert sanitized["uploadUrl"] == "<REDACTED>"
        assert sanitized["downloadUrl"] == "<REDACTED>"
        assert sanitized["safe_field"] == "visible_data"

    def test_sanitize_nested_dict(self):
        """Test sanitizing nested dictionaries."""
        data = {
            "outer": {
                "uploadUrl": "secret",
                "inner": {
                    "presignedUrl": "also-secret",
                    "normal": "visible",
                },
            },
        }

        sanitized = _sanitize_for_logging(data)

        assert sanitized["outer"]["uploadUrl"] == "<REDACTED>"
        assert sanitized["outer"]["inner"]["presignedUrl"] == "<REDACTED>"
        assert sanitized["outer"]["inner"]["normal"] == "visible"

    def test_sanitize_list(self):
        """Test sanitizing lists."""
        data = [
            {"uploadUrl": "secret1"},
            {"uploadUrl": "secret2", "safe": "visible"},
            "plain_string",
        ]

        sanitized = _sanitize_for_logging(data)

        assert sanitized[0]["uploadUrl"] == "<REDACTED>"
        assert sanitized[1]["uploadUrl"] == "<REDACTED>"
        assert sanitized[1]["safe"] == "visible"
        assert sanitized[2] == "plain_string"

    def test_sanitize_custom_redaction_text(self):
        """Test using custom redaction text."""
        data = {"uploadUrl": "secret"}

        sanitized = _sanitize_for_logging(data, redaction_text="***HIDDEN***")

        assert sanitized["uploadUrl"] == "***HIDDEN***"

    def test_sanitize_primitives(self):
        """Test sanitizing primitive types."""
        assert _sanitize_for_logging("string") == "string"
        assert _sanitize_for_logging(123) == 123
        assert _sanitize_for_logging(True) is True
        assert _sanitize_for_logging(None) is None


class TestRunpodGraphQLClientInitialization:
    """Test RunpodGraphQLClient initialization."""

    def test_initialization_with_api_key(self):
        """Test initializing client with explicit API key."""
        client = RunpodGraphQLClient(api_key="test_api_key")

        assert client.api_key == "test_api_key"
        assert client.session is None

    def test_initialization_with_env_var(self, monkeypatch):
        """Test initializing client with API key from environment."""
        monkeypatch.setenv("RUNPOD_API_KEY", "env_api_key")

        client = RunpodGraphQLClient()

        assert client.api_key == "env_api_key"

    def test_initialization_without_api_key(self, monkeypatch):
        """Test that missing API key raises error."""
        monkeypatch.delenv("RUNPOD_API_KEY", raising=False)

        with pytest.raises(RunpodAPIKeyError):
            RunpodGraphQLClient()

    def test_graphql_url_configuration(self):
        """Test GraphQL URL is properly configured."""
        client = RunpodGraphQLClient(api_key="test_key")

        assert "graphql" in client.GRAPHQL_URL
        assert client.GRAPHQL_URL.startswith("https://")


class TestRunpodGraphQLClientSession:
    """Test session management."""

    @pytest.mark.asyncio
    async def test_get_session_creates_new_session(self):
        """Test that _get_session creates a new session."""
        client = RunpodGraphQLClient(api_key="test_key")

        session = await client._get_session()

        assert session is not None
        assert isinstance(session, aiohttp.ClientSession)
        assert not session.closed

        await session.close()

    @pytest.mark.asyncio
    async def test_get_session_reuses_existing_session(self):
        """Test that _get_session reuses existing session."""
        client = RunpodGraphQLClient(api_key="test_key")

        session1 = await client._get_session()
        session2 = await client._get_session()

        assert session1 is session2

        await session1.close()

    @pytest.mark.asyncio
    async def test_get_session_recreates_closed_session(self):
        """Test that _get_session recreates closed session."""
        client = RunpodGraphQLClient(api_key="test_key")

        session1 = await client._get_session()
        await session1.close()

        session2 = await client._get_session()

        assert session2 is not session1
        assert not session2.closed

        await session2.close()

    @pytest.mark.asyncio
    async def test_session_has_auth_header(self):
        """Test that session includes authorization header."""
        client = RunpodGraphQLClient(api_key="test_api_key")

        session = await client._get_session()

        assert "Authorization" in session.headers
        assert session.headers["Authorization"] == "Bearer test_api_key"

        await session.close()

    @pytest.mark.asyncio
    async def test_close_session(self):
        """Test closing the session."""
        client = RunpodGraphQLClient(api_key="test_key")

        session = await client._get_session()
        assert not session.closed

        await client.close()
        assert session.closed


class TestRunpodGraphQLClientExecution:
    """Test GraphQL execution."""

    @pytest.mark.asyncio
    async def test_execute_graphql_success(self):
        """Test successful GraphQL query execution."""
        client = RunpodGraphQLClient(api_key="test_key")

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={"data": {"endpoint": {"id": "123"}}}
        )

        with patch.object(client, "_get_session") as mock_session:
            mock_session_instance = MagicMock()
            mock_session_instance.post.return_value.__aenter__ = AsyncMock(
                return_value=mock_response
            )
            mock_session_instance.post.return_value.__aexit__ = AsyncMock()
            mock_session.return_value = mock_session_instance

            result = await client._execute_graphql("query { test }")

            assert result == {"endpoint": {"id": "123"}}

    @pytest.mark.asyncio
    async def test_execute_graphql_with_variables(self):
        """Test GraphQL execution with variables."""
        client = RunpodGraphQLClient(api_key="test_key")

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"data": {"result": "success"}})

        variables = {"id": "endpoint_123"}

        with patch.object(client, "_get_session") as mock_session:
            mock_session_instance = MagicMock()
            mock_session_instance.post.return_value.__aenter__ = AsyncMock(
                return_value=mock_response
            )
            mock_session_instance.post.return_value.__aexit__ = AsyncMock()
            mock_session.return_value = mock_session_instance

            result = await client._execute_graphql(
                "query($id: ID!) { test(id: $id) }", variables
            )

            assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_execute_graphql_handles_graphql_errors(self):
        """Test handling GraphQL errors in response."""
        client = RunpodGraphQLClient(api_key="test_key")

        # Create proper mock response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "errors": [
                    {"message": "Field not found"},
                    {"message": "Invalid query"},
                ]
            }
        )

        # Create proper async context manager
        mock_ctx_mgr = MagicMock()
        mock_ctx_mgr.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx_mgr.__aexit__ = AsyncMock(return_value=False)

        with patch.object(client, "_get_session") as mock_session:
            mock_session_instance = MagicMock()
            mock_session_instance.post = MagicMock(return_value=mock_ctx_mgr)
            mock_session.return_value = mock_session_instance

            with pytest.raises(Exception, match="GraphQL errors"):
                await client._execute_graphql("query { test }")

    @pytest.mark.asyncio
    async def test_execute_graphql_handles_http_errors(self):
        """Test handling HTTP error status codes."""
        client = RunpodGraphQLClient(api_key="test_key")

        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.json = AsyncMock(return_value={"error": "Internal server error"})

        # Create proper async context manager
        mock_ctx_mgr = MagicMock()
        mock_ctx_mgr.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx_mgr.__aexit__ = AsyncMock(return_value=False)

        with patch.object(client, "_get_session") as mock_session:
            mock_session_instance = MagicMock()
            mock_session_instance.post = MagicMock(return_value=mock_ctx_mgr)
            mock_session.return_value = mock_session_instance

            with pytest.raises(Exception, match="GraphQL request failed: 500"):
                await client._execute_graphql("query { test }")

    @pytest.mark.asyncio
    async def test_execute_graphql_handles_network_errors(self):
        """Test handling network/client errors."""
        client = RunpodGraphQLClient(api_key="test_key")

        with patch.object(client, "_get_session") as mock_session:
            mock_session_instance = MagicMock()
            mock_session_instance.post.side_effect = aiohttp.ClientError(
                "Connection failed"
            )
            mock_session.return_value = mock_session_instance

            with pytest.raises(Exception, match="HTTP request failed"):
                await client._execute_graphql("query { test }")


class TestRunpodGraphQLClientEndpoints:
    """Test endpoint-related methods."""

    @pytest.mark.asyncio
    async def test_save_endpoint(self):
        """Test saving an endpoint."""
        client = RunpodGraphQLClient(api_key="test_key")

        input_data = {
            "name": "test_endpoint",
            "workersMin": 0,
            "workersMax": 3,
        }

        expected_response = {
            "id": "endpoint_123",
            "name": "test_endpoint",
            "workersMin": 0,
            "workersMax": 3,
        }

        with patch.object(client, "_execute_graphql") as mock_execute:
            mock_execute.return_value = {"saveEndpoint": expected_response}

            result = await client.save_endpoint(input_data)

            assert result == expected_response
            mock_execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_endpoint_update_existing(self):
        """Test updating an existing endpoint."""
        client = RunpodGraphQLClient(api_key="test_key")

        input_data = {
            "id": "endpoint_123",
            "name": "updated_endpoint",
            "workersMax": 5,
        }

        with patch.object(client, "_execute_graphql") as mock_execute:
            mock_execute.return_value = {
                "saveEndpoint": {"id": "endpoint_123", "name": "updated_endpoint"}
            }

            result = await client.save_endpoint(input_data)

            assert result["id"] == "endpoint_123"
            assert result["name"] == "updated_endpoint"

    @pytest.mark.asyncio
    async def test_get_endpoint_not_implemented(self):
        """Test that get_endpoint is not currently implemented."""
        client = RunpodGraphQLClient(api_key="test_key")

        # get_endpoint is not implemented in current schema
        with pytest.raises(
            NotImplementedError, match="not available in current schema"
        ):
            await client.get_endpoint("endpoint_123")

    @pytest.mark.asyncio
    async def test_delete_endpoint(self):
        """Test deleting an endpoint."""
        client = RunpodGraphQLClient(api_key="test_key")

        with patch.object(client, "_execute_graphql") as mock_execute:
            mock_execute.return_value = {"deleteEndpoint": None}

            result = await client.delete_endpoint("endpoint_123")

            assert result == {"success": True}
            mock_execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_endpoint_exists_true(self):
        """Test checking if endpoint exists (returns True)."""
        client = RunpodGraphQLClient(api_key="test_key")

        # Mock the actual GraphQL query that endpoint_exists uses (queries myself.endpoints)
        with patch.object(client, "_execute_graphql") as mock_execute:
            mock_execute.return_value = {
                "myself": {
                    "endpoints": [
                        {"id": "endpoint_123"},
                        {"id": "endpoint_456"},
                    ]
                }
            }

            exists = await client.endpoint_exists("endpoint_123")

            assert exists is True

    @pytest.mark.asyncio
    async def test_endpoint_exists_false(self):
        """Test checking if endpoint exists (returns False)."""
        client = RunpodGraphQLClient(api_key="test_key")

        with patch.object(client, "get_endpoint") as mock_get:
            mock_get.side_effect = Exception("Endpoint not found")

            exists = await client.endpoint_exists("endpoint_123")

            assert exists is False


class TestRunpodGraphQLClientGPUCPU:
    """Test GPU and CPU type methods."""

    @pytest.mark.asyncio
    async def test_get_cpu_types(self):
        """Test getting available CPU types."""
        client = RunpodGraphQLClient(api_key="test_key")

        expected_cpu_types = [
            {"id": "cpu1", "displayName": "CPU Type 1"},
            {"id": "cpu2", "displayName": "CPU Type 2"},
        ]

        with patch.object(client, "_execute_graphql") as mock_execute:
            mock_execute.return_value = {"cpuTypes": expected_cpu_types}

            result = await client.get_cpu_types()

            assert result == expected_cpu_types

    @pytest.mark.asyncio
    async def test_get_gpu_types(self):
        """Test getting available GPU types."""
        client = RunpodGraphQLClient(api_key="test_key")

        gpu_filter = {"available": True}
        expected_gpu_types = [
            {"id": "gpu1", "displayName": "NVIDIA RTX 4090"},
            {"id": "gpu2", "displayName": "NVIDIA A100"},
        ]

        with patch.object(client, "_execute_graphql") as mock_execute:
            mock_execute.return_value = {"gpuTypes": expected_gpu_types}

            result = await client.get_gpu_types(gpu_filter)

            assert result == expected_gpu_types


class TestRunpodGraphQLClientContextManager:
    """Test async context manager support."""

    @pytest.mark.asyncio
    async def test_context_manager_usage(self):
        """Test using client as async context manager."""
        async with RunpodGraphQLClient(api_key="test_key") as client:
            assert client.api_key == "test_key"
            session = await client._get_session()
            assert not session.closed

        # Session should be closed after exit
        assert session.closed

    @pytest.mark.asyncio
    async def test_context_manager_with_exception(self):
        """Test context manager closes session even with exception."""
        try:
            async with RunpodGraphQLClient(api_key="test_key") as client:
                session = await client._get_session()
                raise ValueError("Test error")
        except ValueError:
            pass

        # Session should still be closed
        assert session.closed
