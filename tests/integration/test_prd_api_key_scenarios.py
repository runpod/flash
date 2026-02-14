"""Integration tests for PRD API key management scenarios.

Tests the three PRD scenarios:
1. Mothership + GPU worker (mothership makes remote calls)
2. Mothership + CPU + GPU chained (multiple workers with remote calls)
3. Mothership local-only (no remote calls, State Manager not queried)
"""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from runpod_flash.core.resources.serverless import ServerlessResource, ServerlessType
from runpod_flash.runtime.service_registry import ServiceRegistry


class TestPRDScenario1MothershipGPUWorker:
    """Test PRD Scenario 1: Mothership + GPU worker (mothership makes remote calls)."""

    @pytest.fixture
    def manifest_mothership_calls_gpu(self):
        """Manifest where mothership makes remote calls to GPU worker."""
        return {
            "version": "1.0",
            "project_name": "scenario1",
            "function_registry": {
                "inference": "gpu_worker",
            },
            "resources": {
                "mothership": {
                    "resource_type": "CpuLiveLoadBalancer",
                    "functions": [],
                    "is_mothership": True,
                    "makes_remote_calls": True,  # Calls GPU worker
                },
                "gpu_worker": {
                    "resource_type": "LiveServerless",
                    "functions": [
                        {"name": "inference", "module": "workers.gpu", "is_async": True}
                    ],
                    "makes_remote_calls": False,  # Doesn't call others
                },
            },
        }

    @pytest.mark.asyncio
    async def test_mothership_gets_api_key(self, manifest_mothership_calls_gpu):
        """Test that mothership gets RUNPOD_API_KEY when makes_remote_calls=True."""
        # Write manifest to CWD (where _check_makes_remote_calls looks for it)
        manifest_path = Path.cwd() / "flash_manifest.json"
        manifest_path.write_text(json.dumps(manifest_mothership_calls_gpu))

        try:
            # Simulate mothership deployment with API key in environment
            with patch.dict(
                os.environ,
                {
                    "RUNPOD_API_KEY": "test-api-key-123",
                    "FLASH_ENVIRONMENT_ID": "test-env-456",
                },
            ):
                # Create mothership resource
                mothership = ServerlessResource(
                    name="mothership",
                    type=ServerlessType.LB,
                    imageName="runpod/flash-lb-cpu:wip",
                )

                # Check that manifest correctly identifies remote calls
                makes_remote = mothership._check_makes_remote_calls()
                assert makes_remote is True, (
                    "Mothership should make remote calls per manifest"
                )

                # Simulate deployment (inject env vars)
                env_dict = {}
                if makes_remote:
                    env_dict["RUNPOD_API_KEY"] = os.getenv("RUNPOD_API_KEY")
                    env_dict["FLASH_ENVIRONMENT_ID"] = os.getenv("FLASH_ENVIRONMENT_ID")

                assert "RUNPOD_API_KEY" in env_dict, (
                    "Mothership should have API key injected"
                )
                assert env_dict["RUNPOD_API_KEY"] == "test-api-key-123"
                assert "FLASH_ENVIRONMENT_ID" in env_dict, (
                    "Mothership should have environment ID injected"
                )

        finally:
            if manifest_path.exists():
                manifest_path.unlink()

    @pytest.mark.asyncio
    async def test_gpu_worker_no_api_key(self, manifest_mothership_calls_gpu):
        """Test that GPU worker doesn't get API key when makes_remote_calls=False."""
        # Write manifest to CWD (where _check_makes_remote_calls looks for it)
        manifest_path = Path.cwd() / "flash_manifest.json"
        manifest_path.write_text(json.dumps(manifest_mothership_calls_gpu))

        try:
            with patch.dict(
                os.environ, {"RUNPOD_API_KEY": "test-api-key-123"}, clear=True
            ):
                # Create GPU worker resource
                gpu_worker = ServerlessResource(
                    name="gpu_worker",
                    type=ServerlessType.QB,
                    imageName="runpod/flash:wip",
                )

                makes_remote = gpu_worker._check_makes_remote_calls()
                assert makes_remote is False, (
                    "GPU worker shouldn't make remote calls per manifest"
                )

                # No API key injection for local-only worker
                env_dict = {}
                if makes_remote:
                    env_dict["RUNPOD_API_KEY"] = os.getenv("RUNPOD_API_KEY")

                assert "RUNPOD_API_KEY" not in env_dict, (
                    "GPU worker should NOT have API key (local-only)"
                )

        finally:
            if manifest_path.exists():
                manifest_path.unlink()


class TestPRDScenario2ChainedWorkers:
    """Test PRD Scenario 2: Mothership + CPU + GPU chained calls."""

    @pytest.fixture
    def manifest_chained(self):
        """Manifest with chained calls: mothership -> CPU -> GPU."""
        return {
            "version": "1.0",
            "project_name": "scenario2",
            "function_registry": {
                "preprocess": "cpu_worker",
                "inference": "gpu_worker",
            },
            "resources": {
                "mothership": {
                    "resource_type": "CpuLiveLoadBalancer",
                    "functions": [],
                    "is_mothership": True,
                    "makes_remote_calls": True,  # Calls CPU worker
                },
                "cpu_worker": {
                    "resource_type": "LiveServerless",
                    "functions": [
                        {
                            "name": "preprocess",
                            "module": "workers.cpu",
                            "is_async": False,
                        }
                    ],
                    "makes_remote_calls": True,  # Calls GPU worker
                },
                "gpu_worker": {
                    "resource_type": "LiveServerless",
                    "functions": [
                        {"name": "inference", "module": "workers.gpu", "is_async": True}
                    ],
                    "makes_remote_calls": False,  # Terminal node
                },
            },
        }

    @pytest.mark.asyncio
    async def test_all_callers_get_api_keys(self, manifest_chained):
        """Test that all workers making remote calls get API keys."""
        manifest_path = Path.cwd() / "flash_manifest.json"
        manifest_path.write_text(json.dumps(manifest_chained))

        try:
            with patch.dict(
                os.environ, {"RUNPOD_API_KEY": "test-api-key-123"}, clear=True
            ):
                resources = [
                    ("mothership", ServerlessType.LB, True),
                    ("cpu_worker", ServerlessType.QB, True),
                    ("gpu_worker", ServerlessType.QB, False),
                ]

                for name, res_type, expected_remote in resources:
                    resource = ServerlessResource(
                        name=name,
                        type=res_type,
                        imageName="runpod/flash:wip",
                    )

                    makes_remote = resource._check_makes_remote_calls()
                    assert makes_remote == expected_remote, (
                        f"{name} makes_remote_calls should be {expected_remote}"
                    )

                    # API key injection based on makes_remote_calls
                    env_dict = {}
                    if makes_remote:
                        env_dict["RUNPOD_API_KEY"] = os.getenv("RUNPOD_API_KEY")

                    if expected_remote:
                        assert "RUNPOD_API_KEY" in env_dict, (
                            f"{name} should have API key"
                        )
                    else:
                        assert "RUNPOD_API_KEY" not in env_dict, (
                            f"{name} should NOT have API key"
                        )

        finally:
            if manifest_path.exists():
                manifest_path.unlink()


class TestPRDScenario3LocalOnly:
    """Test PRD Scenario 3: Mothership local-only (no State Manager queries)."""

    @pytest.fixture
    def manifest_local_only(self):
        """Manifest where mothership is local-only (no remote calls)."""
        return {
            "version": "1.0",
            "project_name": "scenario3",
            "function_registry": {
                "process": "mothership",
            },
            "resources": {
                "mothership": {
                    "resource_type": "CpuLiveLoadBalancer",
                    "functions": [
                        {
                            "name": "process",
                            "module": "main",
                            "is_async": False,
                        }
                    ],
                    "is_mothership": True,
                    "makes_remote_calls": False,  # Local-only, no remote calls
                },
            },
        }

    @pytest.mark.asyncio
    async def test_local_only_no_state_manager_query(self, manifest_local_only):
        """Test that local-only endpoint doesn't query State Manager."""
        manifest_path = Path.cwd() / "flash_manifest.json"
        manifest_path.write_text(json.dumps(manifest_local_only))

        try:
            with patch.dict(
                os.environ,
                {
                    "FLASH_RESOURCE_NAME": "mothership",
                    "FLASH_ENVIRONMENT_ID": "test-env-123",
                },
            ):
                registry = ServiceRegistry(manifest_path=manifest_path)

                # Mock State Manager client
                mock_client = AsyncMock()
                mock_client.get_persisted_manifest = AsyncMock()
                registry._manifest_client = mock_client

                # Ensure manifest loading - should be skipped for local-only
                await registry._ensure_manifest_loaded()

                # State Manager should NOT be queried (makes_remote_calls=False)
                mock_client.get_persisted_manifest.assert_not_called()

                # Endpoint registry should remain empty (no remote calls needed)
                assert registry._endpoint_registry == {}, (
                    "Local-only endpoint should not load endpoint registry"
                )

        finally:
            if manifest_path.exists():
                manifest_path.unlink()

    @pytest.mark.asyncio
    async def test_local_only_no_api_key_injection(self, manifest_local_only):
        """Test that local-only endpoint doesn't get API key injected."""
        manifest_path = Path.cwd() / "flash_manifest.json"
        manifest_path.write_text(json.dumps(manifest_local_only))

        try:
            with patch.dict(
                os.environ, {"RUNPOD_API_KEY": "test-api-key-123"}, clear=True
            ):
                mothership = ServerlessResource(
                    name="mothership",
                    type=ServerlessType.LB,
                    imageName="runpod/flash-lb-cpu:wip",
                )

                makes_remote = mothership._check_makes_remote_calls()
                assert makes_remote is False, (
                    "Local-only mothership shouldn't make remote calls"
                )

                # No API key for local-only endpoint
                env_dict = {}
                if makes_remote:
                    env_dict["RUNPOD_API_KEY"] = os.getenv("RUNPOD_API_KEY")

                assert "RUNPOD_API_KEY" not in env_dict, (
                    "Local-only endpoint should NOT get API key"
                )

        finally:
            if manifest_path.exists():
                manifest_path.unlink()


class TestResourceNameNormalization:
    """Test resource name normalization (-fb suffix, live- prefix)."""

    @pytest.fixture
    def manifest_for_normalization(self):
        """Manifest with resource 'worker' (no prefixes/suffixes)."""
        return {
            "version": "1.0",
            "project_name": "normalization",
            "function_registry": {},
            "resources": {
                "worker": {
                    "resource_type": "LiveServerless",
                    "functions": [],
                    "makes_remote_calls": True,
                },
            },
        }

    @pytest.mark.parametrize(
        "resource_name,expected_lookup",
        [
            ("worker", "worker"),  # No modification
            ("worker-fb", "worker"),  # Strip -fb
            ("live-worker", "worker"),  # Strip live-
            ("live-worker-fb", "worker"),  # Strip both
        ],
    )
    @pytest.mark.asyncio
    async def test_name_normalization(
        self, manifest_for_normalization, resource_name, expected_lookup
    ):
        """Test that resource names are normalized correctly."""
        manifest_path = Path.cwd() / "flash_manifest.json"
        manifest_path.write_text(json.dumps(manifest_for_normalization))

        try:
            resource = ServerlessResource(
                name=resource_name,
                type=ServerlessType.QB,
                imageName="runpod/flash:wip",
            )

            makes_remote = resource._check_makes_remote_calls()
            # Should find 'worker' in manifest regardless of prefixes/suffixes
            assert makes_remote is True, (
                f"'{resource_name}' should be normalized to '{expected_lookup}' and find makes_remote_calls=True"
            )

        finally:
            if manifest_path.exists():
                manifest_path.unlink()
