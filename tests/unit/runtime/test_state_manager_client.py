"""Unit tests for StateManagerClient GraphQL-based manifest persistence."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from runpod_flash.core.api.runpod import RunpodGraphQLClient
from runpod_flash.runtime.exceptions import ManifestServiceUnavailableError
from runpod_flash.runtime.state_manager_client import StateManagerClient


class TestStateManagerClientBasicOperations:
    """Tests for basic StateManagerClient operations."""

    @pytest.mark.asyncio
    async def test_get_persisted_manifest_success(self):
        """Test successful manifest fetch via GraphQL."""
        mock_client = AsyncMock(spec=RunpodGraphQLClient)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        mock_client.get_flash_environment.return_value = {"activeBuildId": "build-123"}
        mock_client.get_flash_build.return_value = {
            "id": "build-123",
            "manifest": {
                "version": "1.0",
                "resources": {
                    "worker1": {
                        "resource_type": "ServerlessResource",
                        "config_hash": "abc123",
                    }
                },
            },
        }

        with patch(
            "runpod_flash.runtime.state_manager_client.RunpodGraphQLClient",
            return_value=mock_client,
        ):
            client = StateManagerClient()
            manifest = await client.get_persisted_manifest("env-123")

            assert manifest is not None
            assert manifest["version"] == "1.0"
            assert "worker1" in manifest["resources"]
            mock_client.get_flash_environment.assert_awaited_once_with(
                {"flashEnvironmentId": "env-123"}
            )
            mock_client.get_flash_build.assert_awaited_once_with("build-123")

    @pytest.mark.asyncio
    async def test_update_resource_state_merges_existing_data(self):
        """Verify update_resource_state merges with existing resource data."""
        mock_client = AsyncMock(spec=RunpodGraphQLClient)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        mock_client.get_flash_environment.return_value = {"activeBuildId": "build-123"}
        mock_client.get_flash_build.return_value = {
            "id": "build-123",
            "manifest": {
                "resources": {
                    "worker1": {
                        "resource_type": "ServerlessResource",
                        "endpoint_url": "https://old.url",
                    }
                }
            },
        }
        mock_client.update_build_manifest = AsyncMock()

        with patch(
            "runpod_flash.runtime.state_manager_client.RunpodGraphQLClient",
            return_value=mock_client,
        ):
            client = StateManagerClient()
            await client.update_resource_state(
                "env-123", "worker1", {"config_hash": "abc123"}
            )

            call_args = mock_client.update_build_manifest.call_args
            updated_manifest = call_args[0][1]
            assert (
                updated_manifest["resources"]["worker1"]["endpoint_url"]
                == "https://old.url"
            )
            assert updated_manifest["resources"]["worker1"]["config_hash"] == "abc123"

    @pytest.mark.asyncio
    async def test_remove_resource_state_deletes_resource(self):
        """Verify remove_resource_state deletes the specified resource."""
        mock_client = AsyncMock(spec=RunpodGraphQLClient)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        mock_client.get_flash_environment.return_value = {"activeBuildId": "build-123"}
        mock_client.get_flash_build.return_value = {
            "id": "build-123",
            "manifest": {
                "resources": {
                    "worker1": {"resource_type": "ServerlessResource"},
                    "worker2": {"resource_type": "ServerlessResource"},
                }
            },
        }
        mock_client.update_build_manifest = AsyncMock()

        with patch(
            "runpod_flash.runtime.state_manager_client.RunpodGraphQLClient",
            return_value=mock_client,
        ):
            client = StateManagerClient()
            await client.remove_resource_state("env-123", "worker1")

            call_args = mock_client.update_build_manifest.call_args
            updated_manifest = call_args[0][1]
            assert "worker1" not in updated_manifest["resources"]
            assert "worker2" in updated_manifest["resources"]


class TestStateManagerClientErrorHandling:
    """Tests for StateManagerClient error handling."""

    @pytest.mark.asyncio
    async def test_fetch_build_and_manifest_raises_when_no_active_build(self):
        """Verify error when environment has no activeBuildId."""
        mock_client = AsyncMock(spec=RunpodGraphQLClient)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        mock_client.get_flash_environment.return_value = {"activeBuildId": None}

        with patch(
            "runpod_flash.runtime.state_manager_client.RunpodGraphQLClient",
            return_value=mock_client,
        ):
            client = StateManagerClient()

            with pytest.raises(
                ManifestServiceUnavailableError, match="Active build not found"
            ):
                await client.get_persisted_manifest("env-123")

    @pytest.mark.asyncio
    async def test_fetch_build_and_manifest_raises_when_no_manifest(self):
        """Verify error when build has no manifest."""
        mock_client = AsyncMock(spec=RunpodGraphQLClient)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        mock_client.get_flash_environment.return_value = {"activeBuildId": "build-123"}
        mock_client.get_flash_build.return_value = {"id": "build-123", "manifest": None}

        with patch(
            "runpod_flash.runtime.state_manager_client.RunpodGraphQLClient",
            return_value=mock_client,
        ):
            client = StateManagerClient()

            with pytest.raises(
                ManifestServiceUnavailableError, match="Manifest not found"
            ):
                await client.get_persisted_manifest("env-123")

    @pytest.mark.asyncio
    async def test_get_persisted_manifest_timeout(self):
        """Test handling of request timeout."""
        mock_client = AsyncMock(spec=RunpodGraphQLClient)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        mock_client.get_flash_environment.side_effect = asyncio.TimeoutError(
            "Timed out"
        )

        with patch(
            "runpod_flash.runtime.state_manager_client.RunpodGraphQLClient",
            return_value=mock_client,
        ):
            client = StateManagerClient(max_retries=2)

            with patch(
                "runpod_flash.runtime.state_manager_client.asyncio.sleep",
                new_callable=AsyncMock,
            ):
                with pytest.raises(
                    ManifestServiceUnavailableError, match="after 2 attempts"
                ):
                    await client.get_persisted_manifest("env-123")

    @pytest.mark.asyncio
    async def test_update_resource_state_graphql_error(self):
        """Test handling of GraphQL mutation failure."""
        mock_client = AsyncMock(spec=RunpodGraphQLClient)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        mock_client.get_flash_environment.return_value = {"activeBuildId": "build-123"}
        mock_client.get_flash_build.return_value = {
            "id": "build-123",
            "manifest": {"resources": {}},
        }
        mock_client.update_build_manifest.side_effect = ManifestServiceUnavailableError(
            "GraphQL mutation failed"
        )

        with patch(
            "runpod_flash.runtime.state_manager_client.RunpodGraphQLClient",
            return_value=mock_client,
        ):
            client = StateManagerClient(max_retries=2)

            with patch(
                "runpod_flash.runtime.state_manager_client.asyncio.sleep",
                new_callable=AsyncMock,
            ):
                with pytest.raises(
                    ManifestServiceUnavailableError, match="after 2 attempts"
                ):
                    await client.update_resource_state(
                        "env-123", "worker1", {"config_hash": "abc123"}
                    )


class TestStateManagerClientRetryLogic:
    """Tests for StateManagerClient retry logic and exponential backoff."""

    @pytest.mark.asyncio
    async def test_get_persisted_manifest_retry_on_transient_failure(self):
        """Test retry logic with exponential backoff on transient failures."""
        mock_client = AsyncMock(spec=RunpodGraphQLClient)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        success_response = {
            "id": "build-123",
            "manifest": {"version": "1.0", "resources": {}},
        }

        mock_client.get_flash_environment.return_value = {"activeBuildId": "build-123"}
        mock_client.get_flash_build.side_effect = [
            ConnectionError("Network error"),
            ConnectionError("Network error"),
            success_response,
        ]

        with patch(
            "runpod_flash.runtime.state_manager_client.RunpodGraphQLClient",
            return_value=mock_client,
        ):
            client = StateManagerClient(max_retries=3)

            with patch(
                "runpod_flash.runtime.state_manager_client.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep:
                manifest = await client.get_persisted_manifest("env-123")

                assert manifest is not None
                assert mock_client.get_flash_build.call_count == 3
                assert mock_sleep.call_count == 2

                sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
                expected_backoffs = [2**i for i in range(len(sleep_calls))]
                assert sleep_calls == expected_backoffs

    @pytest.mark.asyncio
    async def test_update_resource_state_exhaust_retries(self):
        """Test failure after exhausting all retries."""
        mock_client = AsyncMock(spec=RunpodGraphQLClient)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        mock_client.get_flash_environment.side_effect = ConnectionError("Always fails")

        with patch(
            "runpod_flash.runtime.state_manager_client.RunpodGraphQLClient",
            return_value=mock_client,
        ):
            client = StateManagerClient(max_retries=2)

            with patch(
                "runpod_flash.runtime.state_manager_client.asyncio.sleep",
                new_callable=AsyncMock,
            ):
                with pytest.raises(
                    ManifestServiceUnavailableError, match="after 2 attempts"
                ):
                    await client.update_resource_state(
                        "env-123", "worker1", {"config_hash": "abc123"}
                    )

    @pytest.mark.asyncio
    async def test_remove_resource_state_retry_with_backoff(self):
        """Verify remove_resource_state retries with exponential backoff."""
        mock_client = AsyncMock(spec=RunpodGraphQLClient)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        mock_client.get_flash_environment.return_value = {"activeBuildId": "build-123"}
        mock_client.get_flash_build.side_effect = [
            asyncio.TimeoutError("Timeout"),
            {
                "id": "build-123",
                "manifest": {"resources": {"worker1": {}}},
            },
        ]
        mock_client.update_build_manifest = AsyncMock()

        with patch(
            "runpod_flash.runtime.state_manager_client.RunpodGraphQLClient",
            return_value=mock_client,
        ):
            client = StateManagerClient(max_retries=3)

            with patch(
                "runpod_flash.runtime.state_manager_client.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep:
                await client.remove_resource_state("env-123", "worker1")

                assert mock_sleep.call_count == 1
                sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
                expected_backoffs = [2**i for i in range(len(sleep_calls))]
                assert sleep_calls == expected_backoffs


class TestStateManagerClientConcurrency:
    """Tests for StateManagerClient concurrency and thread safety."""

    @pytest.mark.asyncio
    async def test_concurrent_update_resource_state_with_lock(self):
        """Verify concurrent updates are serialized by the lock."""
        mock_client = AsyncMock(spec=RunpodGraphQLClient)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        mock_client.get_flash_environment.return_value = {"activeBuildId": "build-123"}
        mock_client.get_flash_build.return_value = {
            "id": "build-123",
            "manifest": {"resources": {}},
        }
        mock_client.update_build_manifest = AsyncMock()

        with patch(
            "runpod_flash.runtime.state_manager_client.RunpodGraphQLClient",
            return_value=mock_client,
        ):
            client = StateManagerClient()

            tasks = [
                client.update_resource_state(
                    "env-123", f"worker{i}", {"config_hash": f"hash{i}"}
                )
                for i in range(3)
            ]

            await asyncio.gather(*tasks)

            assert mock_client.update_build_manifest.call_count == 3

            manifests = [
                call[0][1] for call in mock_client.update_build_manifest.call_args_list
            ]

            for i, manifest in enumerate(manifests):
                worker_key = f"worker{i}"
                assert worker_key in manifest["resources"]
                assert manifest["resources"][worker_key]["config_hash"] == f"hash{i}"

    @pytest.mark.asyncio
    async def test_concurrent_remove_and_update_serialized(self):
        """Verify remove and update operations don't conflict."""
        mock_client = AsyncMock(spec=RunpodGraphQLClient)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False

        mock_client.get_flash_environment.return_value = {"activeBuildId": "build-123"}
        mock_client.get_flash_build.return_value = {
            "id": "build-123",
            "manifest": {"resources": {"worker1": {"config_hash": "old"}}},
        }
        mock_client.update_build_manifest = AsyncMock()

        with patch(
            "runpod_flash.runtime.state_manager_client.RunpodGraphQLClient",
            return_value=mock_client,
        ):
            client = StateManagerClient()

            await asyncio.gather(
                client.update_resource_state(
                    "env-123", "worker2", {"config_hash": "new"}
                ),
                client.remove_resource_state("env-123", "worker1"),
            )

            assert mock_client.update_build_manifest.call_count == 2


class TestStateManagerClientAPIKeyThreading:
    """Tests for API key threading through StateManagerClient."""

    @pytest.mark.asyncio
    async def test_api_key_in_init_is_stored(self):
        """Verify API key passed to __init__ is stored."""
        client = StateManagerClient(api_key="test-key-123")
        assert client.api_key == "test-key-123"

    @pytest.mark.asyncio
    async def test_api_key_passed_to_runpod_graphql_client(self):
        """Verify API key is passed to RunpodGraphQLClient."""
        mock_client = AsyncMock(spec=RunpodGraphQLClient)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.get_flash_environment.return_value = {"activeBuildId": "build-123"}
        mock_client.get_flash_build.return_value = {
            "id": "build-123",
            "manifest": {"version": "1.0", "resources": {}},
        }

        with patch(
            "runpod_flash.runtime.state_manager_client.RunpodGraphQLClient",
            return_value=mock_client,
        ) as mock_graphql_class:
            client = StateManagerClient(api_key="stored-key")
            await client.get_persisted_manifest("env-123")

            # Verify RunpodGraphQLClient was called with the stored API key
            mock_graphql_class.assert_called_with(api_key="stored-key")

    @pytest.mark.asyncio
    async def test_api_key_method_parameter_overrides_instance(self):
        """Verify API key passed to method overrides instance api_key."""
        mock_client = AsyncMock(spec=RunpodGraphQLClient)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.get_flash_environment.return_value = {"activeBuildId": "build-123"}
        mock_client.get_flash_build.return_value = {
            "id": "build-123",
            "manifest": {"version": "1.0", "resources": {}},
        }

        with patch(
            "runpod_flash.runtime.state_manager_client.RunpodGraphQLClient",
            return_value=mock_client,
        ) as mock_graphql_class:
            client = StateManagerClient(api_key="stored-key")
            await client.get_persisted_manifest("env-123", api_key="override-key")

            # Verify method parameter overrides instance api_key
            mock_graphql_class.assert_called_with(api_key="override-key")

    @pytest.mark.asyncio
    async def test_api_key_used_in_update_resource_state(self):
        """Verify API key is passed to RunpodGraphQLClient in update_resource_state."""
        mock_client = AsyncMock(spec=RunpodGraphQLClient)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.get_flash_environment.return_value = {"activeBuildId": "build-123"}
        mock_client.get_flash_build.return_value = {
            "id": "build-123",
            "manifest": {"resources": {}},
        }
        mock_client.update_build_manifest = AsyncMock()

        with patch(
            "runpod_flash.runtime.state_manager_client.RunpodGraphQLClient",
            return_value=mock_client,
        ) as mock_graphql_class:
            client = StateManagerClient(api_key="update-key")
            await client.update_resource_state("env-123", "worker1", {"status": "ok"})

            # Verify RunpodGraphQLClient was called with the API key
            mock_graphql_class.assert_called_with(api_key="update-key")

    @pytest.mark.asyncio
    async def test_api_key_used_in_remove_resource_state(self):
        """Verify API key is passed to RunpodGraphQLClient in remove_resource_state."""
        mock_client = AsyncMock(spec=RunpodGraphQLClient)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.get_flash_environment.return_value = {"activeBuildId": "build-123"}
        mock_client.get_flash_build.return_value = {
            "id": "build-123",
            "manifest": {"resources": {"worker1": {}}},
        }
        mock_client.update_build_manifest = AsyncMock()

        with patch(
            "runpod_flash.runtime.state_manager_client.RunpodGraphQLClient",
            return_value=mock_client,
        ) as mock_graphql_class:
            client = StateManagerClient(api_key="remove-key")
            await client.remove_resource_state("env-123", "worker1")

            # Verify RunpodGraphQLClient was called with the API key
            mock_graphql_class.assert_called_with(api_key="remove-key")

    @pytest.mark.asyncio
    async def test_none_api_key_passed_when_not_available(self):
        """Verify None is passed to RunpodGraphQLClient when no API key available."""
        mock_client = AsyncMock(spec=RunpodGraphQLClient)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.get_flash_environment.return_value = {"activeBuildId": "build-123"}
        mock_client.get_flash_build.return_value = {
            "id": "build-123",
            "manifest": {"version": "1.0", "resources": {}},
        }

        with patch(
            "runpod_flash.runtime.state_manager_client.RunpodGraphQLClient",
            return_value=mock_client,
        ) as mock_graphql_class:
            client = StateManagerClient()  # No API key
            await client.get_persisted_manifest("env-123")  # No API key parameter

            # Verify RunpodGraphQLClient was called with None
            # It will fall back to context or env var
            mock_graphql_class.assert_called_with(api_key=None)
