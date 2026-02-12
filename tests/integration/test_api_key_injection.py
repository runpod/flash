"""Integration tests for API key injection during ServerlessResource deployment."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from runpod_flash.core.resources.serverless import (
    ServerlessResource,
    ServerlessType,
)
from runpod_flash.core.api.runpod import RunpodGraphQLClient


class TestAPIKeyInjection:
    """Integration tests for API key injection in queue-based endpoints."""

    @pytest.mark.asyncio
    async def test_qb_endpoint_with_remote_calls_injects_api_key(self):
        """QB endpoint with makes_remote_calls=True injects API key from environment."""
        manifest = {
            "version": "1.0",
            "project_name": "test",
            "resources": {
                "worker1": {
                    "resource_type": "LiveServerless",
                    "makes_remote_calls": True,
                    "functions": [
                        {"name": "task1", "module": "workers.task1", "is_async": True}
                    ],
                }
            },
        }

        # Create temp directory and manifest file
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "flash_manifest.json"
            with open(manifest_path, "w") as f:
                json.dump(manifest, f)

            original_cwd = Path.cwd()
            try:
                # Change to manifest directory for _check_makes_remote_calls()
                os.chdir(tmpdir)

                with patch.dict("os.environ", {"RUNPOD_API_KEY": "test-api-key-123"}):
                    # Create endpoint with QB type
                    endpoint = ServerlessResource(
                        name="worker1",
                        type=ServerlessType.QB,
                        env={},
                    )

                    # Mock RunpodGraphQLClient
                    mock_client = AsyncMock(spec=RunpodGraphQLClient)
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock(return_value=None)
                    mock_client.save_endpoint = AsyncMock(
                        return_value={"id": "endpoint-123", "name": "worker1"}
                    )

                    with patch(
                        "runpod_flash.core.resources.serverless.RunpodGraphQLClient",
                        return_value=mock_client,
                    ):
                        await endpoint._do_deploy()

                    # Assert API key was injected
                    assert "RUNPOD_API_KEY" in endpoint.env
                    assert endpoint.env["RUNPOD_API_KEY"] == "test-api-key-123"

            finally:
                os.chdir(original_cwd)

    @pytest.mark.asyncio
    async def test_qb_endpoint_without_remote_calls_skips_api_key(self):
        """QB endpoint with makes_remote_calls=False does not inject API key."""
        manifest = {
            "version": "1.0",
            "project_name": "test",
            "resources": {
                "local_worker": {
                    "resource_type": "LiveServerless",
                    "makes_remote_calls": False,
                    "functions": [
                        {
                            "name": "local_task",
                            "module": "workers.local",
                            "is_async": True,
                        }
                    ],
                }
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "flash_manifest.json"
            with open(manifest_path, "w") as f:
                json.dump(manifest, f)

            original_cwd = Path.cwd()
            try:
                os.chdir(tmpdir)

                with patch.dict(
                    "os.environ",
                    {"RUNPOD_API_KEY": "test-api-key-123"},
                ):
                    endpoint = ServerlessResource(
                        name="local_worker",
                        type=ServerlessType.QB,
                        env={},
                    )

                    mock_client = AsyncMock(spec=RunpodGraphQLClient)
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock(return_value=None)
                    mock_client.save_endpoint = AsyncMock(
                        return_value={"id": "endpoint-456", "name": "local_worker"}
                    )

                    with patch(
                        "runpod_flash.core.resources.serverless.RunpodGraphQLClient",
                        return_value=mock_client,
                    ):
                        await endpoint._do_deploy()

                    # Assert API key was NOT injected
                    assert "RUNPOD_API_KEY" not in endpoint.env

            finally:
                os.chdir(original_cwd)

    @pytest.mark.asyncio
    async def test_lb_endpoint_never_injects_api_key(self):
        """Load-balancer endpoints never inject API keys (use Authorization headers)."""
        manifest = {
            "version": "1.0",
            "project_name": "test",
            "resources": {
                "lb_worker": {
                    "resource_type": "LoadBalancerServerless",
                    "makes_remote_calls": True,
                    "functions": [
                        {"name": "api_task", "module": "workers.api", "is_async": True}
                    ],
                }
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "flash_manifest.json"
            with open(manifest_path, "w") as f:
                json.dump(manifest, f)

            original_cwd = Path.cwd()
            try:
                os.chdir(tmpdir)

                with patch.dict("os.environ", {"RUNPOD_API_KEY": "test-api-key-123"}):
                    # LB endpoint type
                    endpoint = ServerlessResource(
                        name="lb_worker",
                        type=ServerlessType.LB,
                        env={},
                    )

                    mock_client = AsyncMock(spec=RunpodGraphQLClient)
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock(return_value=None)
                    mock_client.save_endpoint = AsyncMock(
                        return_value={"id": "endpoint-789", "name": "lb_worker"}
                    )

                    with patch(
                        "runpod_flash.core.resources.serverless.RunpodGraphQLClient",
                        return_value=mock_client,
                    ):
                        await endpoint._do_deploy()

                    # Assert API key was NOT injected (LB uses Authorization headers)
                    assert "RUNPOD_API_KEY" not in endpoint.env

            finally:
                os.chdir(original_cwd)

    @pytest.mark.asyncio
    async def test_missing_runpod_api_key_logs_warning(self, caplog):
        """Missing RUNPOD_API_KEY logs warning but deployment proceeds."""
        manifest = {
            "version": "1.0",
            "project_name": "test",
            "resources": {
                "remote_worker": {
                    "resource_type": "LiveServerless",
                    "makes_remote_calls": True,
                    "functions": [
                        {
                            "name": "remote_task",
                            "module": "workers.remote",
                            "is_async": True,
                        }
                    ],
                }
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "flash_manifest.json"
            with open(manifest_path, "w") as f:
                json.dump(manifest, f)

            original_cwd = Path.cwd()
            try:
                os.chdir(tmpdir)

                # No RUNPOD_API_KEY in environment
                with patch.dict("os.environ", {}, clear=True):
                    endpoint = ServerlessResource(
                        name="remote_worker",
                        type=ServerlessType.QB,
                        env={},
                    )

                    mock_client = AsyncMock(spec=RunpodGraphQLClient)
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock(return_value=None)
                    mock_client.save_endpoint = AsyncMock(
                        return_value={"id": "endpoint-999", "name": "remote_worker"}
                    )

                    with patch(
                        "runpod_flash.core.resources.serverless.RunpodGraphQLClient",
                        return_value=mock_client,
                    ):
                        with caplog.at_level("WARNING"):
                            await endpoint._do_deploy()

                    # Assert warning was logged
                    assert any(
                        "makes_remote_calls=True but RUNPOD_API_KEY not set"
                        in record.message
                        for record in caplog.records
                    )

                    # Assert deployment still proceeded
                    assert endpoint.id == "endpoint-999"
                    assert "RUNPOD_API_KEY" not in endpoint.env

            finally:
                os.chdir(original_cwd)

    @pytest.mark.asyncio
    async def test_existing_api_key_not_overwritten(self):
        """Existing API key in env dict is not overwritten."""
        manifest = {
            "version": "1.0",
            "project_name": "test",
            "resources": {
                "configured_worker": {
                    "resource_type": "LiveServerless",
                    "makes_remote_calls": True,
                    "functions": [
                        {
                            "name": "configured_task",
                            "module": "workers.configured",
                            "is_async": True,
                        }
                    ],
                }
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "flash_manifest.json"
            with open(manifest_path, "w") as f:
                json.dump(manifest, f)

            original_cwd = Path.cwd()
            try:
                os.chdir(tmpdir)

                with patch.dict("os.environ", {"RUNPOD_API_KEY": "env-api-key"}):
                    # Endpoint already has API key configured
                    endpoint = ServerlessResource(
                        name="configured_worker",
                        type=ServerlessType.QB,
                        env={"RUNPOD_API_KEY": "pre-configured-key"},
                    )

                    mock_client = AsyncMock(spec=RunpodGraphQLClient)
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock(return_value=None)
                    mock_client.save_endpoint = AsyncMock(
                        return_value={"id": "endpoint-111", "name": "configured_worker"}
                    )

                    with patch(
                        "runpod_flash.core.resources.serverless.RunpodGraphQLClient",
                        return_value=mock_client,
                    ):
                        await endpoint._do_deploy()

                    # Assert pre-configured key was NOT overwritten
                    assert endpoint.env["RUNPOD_API_KEY"] == "pre-configured-key"

            finally:
                os.chdir(original_cwd)

    @pytest.mark.asyncio
    async def test_manifest_not_found_uses_safe_default(self):
        """When manifest not found, assumes makes_remote_calls=True and injects key."""
        original_cwd = Path.cwd()
        # Use temp directory where no manifest exists
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                os.chdir(tmpdir)

                with patch.dict("os.environ", {"RUNPOD_API_KEY": "fallback-key"}):
                    endpoint = ServerlessResource(
                        name="unknown_worker",
                        type=ServerlessType.QB,
                        env={},
                    )

                    mock_client = AsyncMock(spec=RunpodGraphQLClient)
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock(return_value=None)
                    mock_client.save_endpoint = AsyncMock(
                        return_value={"id": "endpoint-222", "name": "unknown_worker"}
                    )

                    with patch(
                        "runpod_flash.core.resources.serverless.RunpodGraphQLClient",
                        return_value=mock_client,
                    ):
                        await endpoint._do_deploy()

                    # Assert safe default: API key was injected
                    assert "RUNPOD_API_KEY" in endpoint.env
                    assert endpoint.env["RUNPOD_API_KEY"] == "fallback-key"

            finally:
                os.chdir(original_cwd)
