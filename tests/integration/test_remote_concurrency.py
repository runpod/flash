"""
Integration tests for @remote decorator concurrency.

These tests verify that concurrent calls to @remote decorated functions
properly use async locking to prevent race conditions and duplicate deployments.
"""

import asyncio
import os
import tempfile
import shutil
import base64
import cloudpickle
from pathlib import Path
from unittest.mock import patch
from typing import Dict, Any

import pytest

from runpod_flash import remote
from runpod_flash.core.resources.resource_manager import (
    ResourceManager,
    RESOURCE_STATE_FILE,
)
from runpod_flash.core.resources.serverless_cpu import CpuServerlessEndpoint
from runpod_flash.core.resources.serverless import JobOutput, ServerlessEndpoint
from runpod_flash.core.resources.live_serverless import (
    LiveServerless,
    CpuLiveServerless,
)
from runpod_flash.core.utils.singleton import SingletonMixin
from runpod_flash.protos.remote_execution import FunctionResponse


@pytest.mark.serial
@pytest.mark.asyncio
@patch.dict(
    os.environ,
    {
        "RUNPOD_ENDPOINT_ID": "",
        "RUNPOD_POD_ID": "",
        "FLASH_IS_LIVE_PROVISIONING": "true",
    },
)
class TestRemoteConcurrency:
    """Test concurrency behavior of @remote decorated functions."""

    def setup_method(self):
        """Set up test environment with clean state."""
        # Clear singleton instances
        SingletonMixin._instances.clear()
        ResourceManager._resources.clear()
        ResourceManager._deployment_locks.clear()
        ResourceManager._lock_initialized = False
        ResourceManager._resources_initialized = False

        # Use temporary state file
        self.temp_dir = tempfile.mkdtemp()
        self.original_state_file = RESOURCE_STATE_FILE

        # Patch the state file location
        import runpod_flash.core.resources.resource_manager as rm_module

        rm_module.RESOURCE_STATE_FILE = Path(self.temp_dir) / "test_resources.pkl"

    def teardown_method(self):
        """Clean up test environment."""
        # Restore original state file
        import runpod_flash.core.resources.resource_manager as rm_module

        rm_module.RESOURCE_STATE_FILE = self.original_state_file

        # Clean up temp directory
        shutil.rmtree(self.temp_dir, ignore_errors=True)

        # Clear singleton instances
        SingletonMixin._instances.clear()
        ResourceManager._resources.clear()
        ResourceManager._deployment_locks.clear()
        ResourceManager._lock_initialized = False
        ResourceManager._resources_initialized = False

    async def test_concurrent_remote_function_calls_single_deployment(self):
        """Test that concurrent calls to same @remote function create only one deployment."""

        # Create CPU endpoint for testing
        cpu_endpoint = CpuServerlessEndpoint(
            name="test_concurrent",
            imageName="runpod/mock-worker:dev",
        )

        # Track deployment calls at the actual deploy level
        deployment_count = 0

        async def mock_deploy(self):
            nonlocal deployment_count
            deployment_count += 1

            # Simulate deployment delay to increase race condition likelihood
            await asyncio.sleep(0.1)

            # Create mock deployed resource
            deployed = CpuServerlessEndpoint(
                name=self.name,
                imageName=self.imageName,
                id=f"mock-endpoint-{deployment_count}",
            )
            deployed._deployed = True
            return deployed

        async def mock_is_deployed(self):
            return hasattr(self, "id") and self.id is not None

        # Mock at the deployment level to let ResourceManager handle concurrency
        with (
            patch.object(CpuServerlessEndpoint, "_do_deploy", mock_deploy),
            patch.object(CpuServerlessEndpoint, "is_deployed", mock_is_deployed),
        ):

            @remote(cpu_endpoint)
            def test_function(value: str) -> Dict[str, Any]:
                return {"result": f"processed_{value}"}

            # Mock the actual function execution to avoid network calls
            with patch(
                "runpod_flash.stubs.serverless.ServerlessEndpointStub.execute",
                return_value=JobOutput(
                    id="mock-job-1",
                    workerId="mock-worker-1",
                    status="COMPLETED",
                    delayTime=10,
                    executionTime=100,
                    output={"result": "mocked_response"},
                    error=None,
                ),
            ):
                # Execute 5 concurrent calls to the same function
                tasks = []
                for i in range(5):
                    task = test_function(f"value_{i}")
                    tasks.append(task)

                # Wait for all calls to complete
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Verify results
                assert len(results) == 5

                # Check that all calls succeeded
                successful_calls = sum(
                    1 for result in results if not isinstance(result, Exception)
                )

                # Print exceptions for debugging
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        print(
                            f"Call {i} failed with: {type(result).__name__}: {result}"
                        )

                assert successful_calls == 5, (
                    f"Expected 5 successful calls, got {successful_calls}"
                )

                # CRITICAL: Verify only one deployment occurred
                assert deployment_count == 1, (
                    f"Expected 1 deployment, got {deployment_count}"
                )

    async def test_concurrent_different_endpoints_multiple_deployments(self):
        """Test that concurrent calls to different @remote endpoints create separate deployments."""

        deployment_count = 0
        deployed_resources = {}

        async def mock_get_or_deploy_resource(config):
            nonlocal deployment_count, deployed_resources

            # Use config name as key to track different endpoints
            if config.name not in deployed_resources:
                deployment_count += 1
                deployed_resources[config.name] = CpuServerlessEndpoint(
                    name=config.name,
                    imageName=config.imageName,
                    id=f"mock-endpoint-{config.name}-{deployment_count}",
                )
                deployed_resources[config.name]._deployed = True

            # Simulate deployment delay
            await asyncio.sleep(0.05)
            return deployed_resources[config.name]

        # Mock the ResourceManager method that handles deployment
        with patch.object(
            ResourceManager,
            "get_or_deploy_resource",
            side_effect=mock_get_or_deploy_resource,
        ):
            # Create two different endpoints
            cpu_endpoint_1 = CpuServerlessEndpoint(
                name="test_endpoint_1",
                imageName="runpod/mock-worker:dev",
            )

            cpu_endpoint_2 = CpuServerlessEndpoint(
                name="test_endpoint_2",
                imageName="runpod/mock-worker:dev",
            )

            @remote(cpu_endpoint_1)
            def function_1(value: str) -> str:
                return f"function1_{value}"

            @remote(cpu_endpoint_2)
            def function_2(value: str) -> str:
                return f"function2_{value}"

            # Mock the actual function execution to avoid network calls
            with patch(
                "runpod_flash.stubs.serverless.ServerlessEndpointStub.execute",
                return_value=JobOutput(
                    id="mock-job-2",
                    workerId="mock-worker-2",
                    status="COMPLETED",
                    delayTime=10,
                    executionTime=100,
                    output="mocked_response",
                    error=None,
                ),
            ):
                # Execute concurrent calls to different functions
                tasks = [
                    function_1("test"),
                    function_2("test"),
                    function_1("test2"),  # Should reuse endpoint 1
                    function_2("test2"),  # Should reuse endpoint 2
                ]

                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Verify results
                assert len(results) == 4
                successful_calls = sum(
                    1 for result in results if not isinstance(result, Exception)
                )
                assert successful_calls == 4

                # Should have exactly 2 deployments (one per unique endpoint)
                assert deployment_count == 2, (
                    f"Expected 2 deployments for different endpoints, got {deployment_count}"
                )

    async def test_resource_manager_singleton_across_remote_calls(self):
        """Test that ResourceManager singleton works correctly across @remote calls."""

        cpu_endpoint = CpuServerlessEndpoint(
            name="test_singleton",
            imageName="runpod/mock-worker:dev",
        )

        resource_manager_ids = []

        async def mock_get_or_deploy_resource(config):
            # Capture ResourceManager instance ID during deployment
            rm = ResourceManager()
            resource_manager_ids.append(id(rm))

            deployed = CpuServerlessEndpoint(
                name=config.name, imageName=config.imageName, id="mock-singleton-test"
            )
            deployed._deployed = True
            return deployed

        # Mock the ResourceManager method that handles deployment
        with patch.object(
            ResourceManager,
            "get_or_deploy_resource",
            side_effect=mock_get_or_deploy_resource,
        ):

            @remote(cpu_endpoint)
            def test_function(value: int) -> int:
                return value * 2

            # Mock the actual function execution to avoid network calls
            with patch(
                "runpod_flash.stubs.serverless.ServerlessEndpointStub.execute",
                return_value=JobOutput(
                    id="mock-job-3",
                    workerId="mock-worker-3",
                    status="COMPLETED",
                    delayTime=10,
                    executionTime=100,
                    output=4,
                    error=None,
                ),
            ):
                # Make multiple concurrent calls
                tasks = [test_function(i) for i in range(3)]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Verify all calls succeeded
                assert len(results) == 3
                assert all(not isinstance(result, Exception) for result in results)

                # Verify ResourceManager singleton - should only have 1 unique instance ID
                unique_rm_ids = set(resource_manager_ids)
                assert len(unique_rm_ids) <= 1, (
                    f"Expected 1 ResourceManager instance, got {len(unique_rm_ids)}: {unique_rm_ids}"
                )

    async def test_async_lock_prevents_race_conditions(self):
        """Test that async locks prevent race conditions during deployment."""

        cpu_endpoint = CpuServerlessEndpoint(
            name="test_race_conditions",
            imageName="runpod/mock-worker:dev",
        )

        # Track the order of deployment attempts
        deployment_order = []
        deployment_in_progress = False
        deployment_count = 0

        async def mock_deploy(self):
            nonlocal deployment_in_progress, deployment_count

            # Verify that no other deployment is in progress (mutual exclusion)
            assert not deployment_in_progress, (
                "Race condition detected: multiple deployments in progress"
            )

            deployment_in_progress = True
            deployment_order.append(f"start-{len(deployment_order)}")
            deployment_count += 1

            # Simulate deployment time
            await asyncio.sleep(0.05)

            deployment_order.append(f"end-{len(deployment_order)}")
            deployment_in_progress = False

            # Create deployed resource
            deployed = CpuServerlessEndpoint(
                name=self.name, imageName=self.imageName, id="mock-race-test"
            )
            deployed._deployed = True
            return deployed

        async def mock_is_deployed(self):
            return hasattr(self, "id") and self.id is not None

        # Mock at the deployment level to let ResourceManager handle concurrency
        with (
            patch.object(CpuServerlessEndpoint, "_do_deploy", mock_deploy),
            patch.object(CpuServerlessEndpoint, "is_deployed", mock_is_deployed),
        ):

            @remote(cpu_endpoint)
            def test_function(value: str) -> str:
                return f"result_{value}"

            # Mock the actual function execution to avoid network calls
            with patch(
                "runpod_flash.stubs.serverless.ServerlessEndpointStub.execute",
                return_value=JobOutput(
                    id="mock-job-4",
                    workerId="mock-worker-4",
                    status="COMPLETED",
                    delayTime=10,
                    executionTime=100,
                    output="mocked_result",
                    error=None,
                ),
            ):
                # Execute multiple concurrent calls
                tasks = [test_function(f"val_{i}") for i in range(4)]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Verify no race conditions occurred
                assert len(results) == 4

                # Print exceptions for debugging
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        print(
                            f"Call {i} failed with: {type(result).__name__}: {result}"
                        )

                assert all(not isinstance(result, Exception) for result in results)

                # Verify deployment order shows proper mutual exclusion
                # Should see only one start-end pair
                start_count = sum(
                    1 for item in deployment_order if item.startswith("start")
                )
                end_count = sum(
                    1 for item in deployment_order if item.startswith("end")
                )

                assert start_count == 1, (
                    f"Expected 1 deployment start, got {start_count}: {deployment_order}"
                )
                assert end_count == 1, (
                    f"Expected 1 deployment end, got {end_count}: {deployment_order}"
                )

    # ===== ServerlessEndpoint Tests =====

    async def test_serverless_endpoint_concurrent_calls_single_deployment(self):
        """Test that concurrent calls to same @remote function with ServerlessEndpoint create only one deployment."""

        # Create ServerlessEndpoint for testing
        serverless_endpoint = ServerlessEndpoint(
            name="test_serverless_concurrent",
            imageName="runpod/mock-worker:dev",
        )

        # Track deployment calls at the actual deploy level
        deployment_count = 0

        async def mock_deploy(self):
            nonlocal deployment_count
            deployment_count += 1

            # Simulate deployment delay to increase race condition likelihood
            await asyncio.sleep(0.1)

            # Create mock deployed resource
            deployed = ServerlessEndpoint(
                name=self.name,
                imageName=self.imageName,
                id=f"mock-serverless-{deployment_count}",
            )
            deployed._deployed = True
            return deployed

        async def mock_is_deployed(self):
            return hasattr(self, "id") and self.id is not None

        # Mock at the deployment level to let ResourceManager handle concurrency
        with (
            patch.object(ServerlessEndpoint, "_do_deploy", mock_deploy),
            patch.object(ServerlessEndpoint, "is_deployed", mock_is_deployed),
        ):

            @remote(serverless_endpoint)
            def test_function(value: str) -> Dict[str, Any]:
                return {"result": f"processed_{value}"}

            # Mock the actual function execution to avoid network calls
            with patch(
                "runpod_flash.stubs.serverless.ServerlessEndpointStub.execute",
                return_value=JobOutput(
                    id="mock-job-serverless",
                    workerId="mock-worker-serverless",
                    status="COMPLETED",
                    delayTime=10,
                    executionTime=100,
                    output={"result": "mocked_response"},
                    error=None,
                ),
            ):
                # Execute 5 concurrent calls to the same function
                tasks = []
                for i in range(5):
                    task = test_function(f"value_{i}")
                    tasks.append(task)

                # Wait for all calls to complete
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Verify results
                assert len(results) == 5

                # Check that all calls succeeded
                successful_calls = sum(
                    1 for result in results if not isinstance(result, Exception)
                )

                # Print exceptions for debugging
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        print(
                            f"ServerlessEndpoint Call {i} failed with: {type(result).__name__}: {result}"
                        )

                assert successful_calls == 5, (
                    f"Expected 5 successful calls, got {successful_calls}"
                )

                # CRITICAL: Verify only one deployment occurred
                assert deployment_count == 1, (
                    f"Expected 1 deployment, got {deployment_count}"
                )

    async def test_serverless_endpoint_async_lock_prevents_race_conditions(self):
        """Test that async locks prevent race conditions during ServerlessEndpoint deployment."""

        serverless_endpoint = ServerlessEndpoint(
            name="test_serverless_race_conditions",
            imageName="runpod/mock-worker:dev",
        )

        # Track the order of deployment attempts
        deployment_order = []
        deployment_in_progress = False
        deployment_count = 0

        async def mock_deploy(self):
            nonlocal deployment_in_progress, deployment_count

            # Verify that no other deployment is in progress (mutual exclusion)
            assert not deployment_in_progress, (
                "Race condition detected: multiple deployments in progress"
            )

            deployment_in_progress = True
            deployment_order.append(f"start-{len(deployment_order)}")
            deployment_count += 1

            # Simulate deployment time
            await asyncio.sleep(0.05)

            deployment_order.append(f"end-{len(deployment_order)}")
            deployment_in_progress = False

            # Create deployed resource
            deployed = ServerlessEndpoint(
                name=self.name, imageName=self.imageName, id="mock-serverless-race-test"
            )
            deployed._deployed = True
            return deployed

        async def mock_is_deployed(self):
            return hasattr(self, "id") and self.id is not None

        # Mock at the deployment level to let ResourceManager handle concurrency
        with (
            patch.object(ServerlessEndpoint, "_do_deploy", mock_deploy),
            patch.object(ServerlessEndpoint, "is_deployed", mock_is_deployed),
        ):

            @remote(serverless_endpoint)
            def test_function(value: str) -> str:
                return f"result_{value}"

            # Mock the actual function execution to avoid network calls
            with patch(
                "runpod_flash.stubs.serverless.ServerlessEndpointStub.execute",
                return_value=JobOutput(
                    id="mock-job-serverless-race",
                    workerId="mock-worker-serverless-race",
                    status="COMPLETED",
                    delayTime=10,
                    executionTime=100,
                    output="mocked_result",
                    error=None,
                ),
            ):
                # Execute multiple concurrent calls
                tasks = [test_function(f"val_{i}") for i in range(4)]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Verify no race conditions occurred
                assert len(results) == 4

                # Print exceptions for debugging
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        print(
                            f"ServerlessEndpoint Race Call {i} failed with: {type(result).__name__}: {result}"
                        )

                assert all(not isinstance(result, Exception) for result in results)

                # Verify deployment order shows proper mutual exclusion
                # Should see only one start-end pair
                start_count = sum(
                    1 for item in deployment_order if item.startswith("start")
                )
                end_count = sum(
                    1 for item in deployment_order if item.startswith("end")
                )

                assert start_count == 1, (
                    f"Expected 1 deployment start, got {start_count}: {deployment_order}"
                )
                assert end_count == 1, (
                    f"Expected 1 deployment end, got {end_count}: {deployment_order}"
                )

    # ===== LiveServerless Tests =====

    async def test_live_serverless_concurrent_calls_single_deployment(self):
        """Test that concurrent calls to same @remote function with LiveServerless create only one deployment."""

        # Create LiveServerless for testing
        live_serverless = LiveServerless(
            name="test_live_concurrent",
            imageName="runpod/mock-worker:dev",
        )

        # Track deployment calls at the actual deploy level
        deployment_count = 0

        async def mock_deploy(self):
            nonlocal deployment_count
            deployment_count += 1

            # Simulate deployment delay to increase race condition likelihood
            await asyncio.sleep(0.1)

            # Create mock deployed resource
            deployed = LiveServerless(
                name=self.name,
                imageName=self.imageName,
                id=f"mock-live-{deployment_count}",
            )
            deployed._deployed = True
            return deployed

        async def mock_is_deployed(self):
            return hasattr(self, "id") and self.id is not None

        # Mock at the deployment level to let ResourceManager handle concurrency
        with (
            patch.object(LiveServerless, "_do_deploy", mock_deploy),
            patch.object(LiveServerless, "is_deployed", mock_is_deployed),
        ):

            @remote(live_serverless)
            def test_function(value: str) -> Dict[str, Any]:
                return {"result": f"processed_{value}"}

            # Mock the actual function execution to avoid network calls
            # LiveServerless uses LiveServerlessStub.ExecuteFunction which returns FunctionResponse
            mock_result = {"result": "mocked_response"}
            with (
                patch(
                    "runpod_flash.stubs.live_serverless.LiveServerlessStub.ExecuteFunction",
                    return_value=FunctionResponse(
                        success=True,
                        result=base64.b64encode(cloudpickle.dumps(mock_result)).decode(
                            "utf-8"
                        ),
                        error=None,
                        stdout="Mock execution output",
                    ),
                ),
                patch(
                    "runpod_flash.stubs.live_serverless.get_function_source",
                    return_value=(
                        "def test_function(value):\n    return {'result': f'processed_{value}'}",
                        "mock_hash",
                    ),
                ),
            ):
                # Execute 5 concurrent calls to the same function
                tasks = []
                for i in range(5):
                    task = test_function(f"value_{i}")
                    tasks.append(task)

                # Wait for all calls to complete
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Verify results
                assert len(results) == 5

                # Check that all calls succeeded
                successful_calls = sum(
                    1 for result in results if not isinstance(result, Exception)
                )

                # Print exceptions for debugging
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        print(
                            f"LiveServerless Call {i} failed with: {type(result).__name__}: {result}"
                        )

                assert successful_calls == 5, (
                    f"Expected 5 successful calls, got {successful_calls}"
                )

                # CRITICAL: Verify only one deployment occurred
                assert deployment_count == 1, (
                    f"Expected 1 deployment, got {deployment_count}"
                )

    async def test_live_serverless_async_lock_prevents_race_conditions(self):
        """Test that async locks prevent race conditions during LiveServerless deployment."""

        live_serverless = LiveServerless(
            name="test_live_race_conditions",
            imageName="runpod/mock-worker:dev",
        )

        # Track the order of deployment attempts
        deployment_order = []
        deployment_in_progress = False
        deployment_count = 0

        async def mock_deploy(self):
            nonlocal deployment_in_progress, deployment_count

            # Verify that no other deployment is in progress (mutual exclusion)
            assert not deployment_in_progress, (
                "Race condition detected: multiple deployments in progress"
            )

            deployment_in_progress = True
            deployment_order.append(f"start-{len(deployment_order)}")
            deployment_count += 1

            # Simulate deployment time
            await asyncio.sleep(0.05)

            deployment_order.append(f"end-{len(deployment_order)}")
            deployment_in_progress = False

            # Create deployed resource
            deployed = LiveServerless(
                name=self.name, imageName=self.imageName, id="mock-live-race-test"
            )
            deployed._deployed = True
            return deployed

        async def mock_is_deployed(self):
            return hasattr(self, "id") and self.id is not None

        # Mock at the deployment level to let ResourceManager handle concurrency
        with (
            patch.object(LiveServerless, "_do_deploy", mock_deploy),
            patch.object(LiveServerless, "is_deployed", mock_is_deployed),
        ):

            @remote(live_serverless)
            def test_function(value: str) -> str:
                return f"result_{value}"

            # Mock the actual function execution to avoid network calls
            mock_result = "mocked_result"
            with (
                patch(
                    "runpod_flash.stubs.live_serverless.LiveServerlessStub.ExecuteFunction",
                    return_value=FunctionResponse(
                        success=True,
                        result=base64.b64encode(cloudpickle.dumps(mock_result)).decode(
                            "utf-8"
                        ),
                        error=None,
                        stdout="Mock execution output",
                    ),
                ),
                patch(
                    "runpod_flash.stubs.live_serverless.get_function_source",
                    return_value=(
                        "def test_function(value):\n    return f'result_{value}'",
                        "mock_hash",
                    ),
                ),
            ):
                # Execute multiple concurrent calls
                tasks = [test_function(f"val_{i}") for i in range(4)]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Verify no race conditions occurred
                assert len(results) == 4

                # Print exceptions for debugging
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        print(
                            f"LiveServerless Race Call {i} failed with: {type(result).__name__}: {result}"
                        )

                assert all(not isinstance(result, Exception) for result in results)

                # Verify deployment order shows proper mutual exclusion
                # Should see only one start-end pair
                start_count = sum(
                    1 for item in deployment_order if item.startswith("start")
                )
                end_count = sum(
                    1 for item in deployment_order if item.startswith("end")
                )

                assert start_count == 1, (
                    f"Expected 1 deployment start, got {start_count}: {deployment_order}"
                )
                assert end_count == 1, (
                    f"Expected 1 deployment end, got {end_count}: {deployment_order}"
                )

    # ===== CpuLiveServerless Tests =====

    async def test_cpu_live_serverless_concurrent_calls_single_deployment(self):
        """Test that concurrent calls to same @remote function with CpuLiveServerless create only one deployment."""

        # Create CpuLiveServerless for testing
        cpu_live_serverless = CpuLiveServerless(
            name="test_cpu_live_concurrent",
            imageName="runpod/mock-worker:dev",
        )

        # Track deployment calls at the actual deploy level
        deployment_count = 0

        async def mock_deploy(self):
            nonlocal deployment_count
            deployment_count += 1

            # Simulate deployment delay to increase race condition likelihood
            await asyncio.sleep(0.1)

            # Create mock deployed resource
            deployed = CpuLiveServerless(
                name=self.name,
                imageName=self.imageName,
                id=f"mock-cpu-live-{deployment_count}",
            )
            deployed._deployed = True
            return deployed

        async def mock_is_deployed(self):
            return hasattr(self, "id") and self.id is not None

        # Mock at the deployment level to let ResourceManager handle concurrency
        with (
            patch.object(CpuLiveServerless, "_do_deploy", mock_deploy),
            patch.object(CpuLiveServerless, "is_deployed", mock_is_deployed),
        ):

            @remote(cpu_live_serverless)
            def test_function(value: str) -> Dict[str, Any]:
                return {"result": f"processed_{value}"}

            # Mock the actual function execution to avoid network calls
            # CpuLiveServerless uses LiveServerlessStub.ExecuteFunction which returns FunctionResponse
            mock_result = {"result": "mocked_response"}
            with (
                patch(
                    "runpod_flash.stubs.live_serverless.LiveServerlessStub.ExecuteFunction",
                    return_value=FunctionResponse(
                        success=True,
                        result=base64.b64encode(cloudpickle.dumps(mock_result)).decode(
                            "utf-8"
                        ),
                        error=None,
                        stdout="Mock execution output",
                    ),
                ),
                patch(
                    "runpod_flash.stubs.live_serverless.get_function_source",
                    return_value=(
                        "def test_function(value):\n    return {'result': f'processed_{value}'}",
                        "mock_hash",
                    ),
                ),
            ):
                # Execute 5 concurrent calls to the same function
                tasks = []
                for i in range(5):
                    task = test_function(f"value_{i}")
                    tasks.append(task)

                # Wait for all calls to complete
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Verify results
                assert len(results) == 5

                # Check that all calls succeeded
                successful_calls = sum(
                    1 for result in results if not isinstance(result, Exception)
                )

                # Print exceptions for debugging
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        print(
                            f"CpuLiveServerless Call {i} failed with: {type(result).__name__}: {result}"
                        )

                assert successful_calls == 5, (
                    f"Expected 5 successful calls, got {successful_calls}"
                )

                # CRITICAL: Verify only one deployment occurred
                assert deployment_count == 1, (
                    f"Expected 1 deployment, got {deployment_count}"
                )

    async def test_cpu_live_serverless_async_lock_prevents_race_conditions(self):
        """Test that async locks prevent race conditions during CpuLiveServerless deployment."""

        cpu_live_serverless = CpuLiveServerless(
            name="test_cpu_live_race_conditions",
            imageName="runpod/mock-worker:dev",
        )

        # Track the order of deployment attempts
        deployment_order = []
        deployment_in_progress = False
        deployment_count = 0

        async def mock_deploy(self):
            nonlocal deployment_in_progress, deployment_count

            # Verify that no other deployment is in progress (mutual exclusion)
            assert not deployment_in_progress, (
                "Race condition detected: multiple deployments in progress"
            )

            deployment_in_progress = True
            deployment_order.append(f"start-{len(deployment_order)}")
            deployment_count += 1

            # Simulate deployment time
            await asyncio.sleep(0.05)

            deployment_order.append(f"end-{len(deployment_order)}")
            deployment_in_progress = False

            # Create deployed resource
            deployed = CpuLiveServerless(
                name=self.name, imageName=self.imageName, id="mock-cpu-live-race-test"
            )
            deployed._deployed = True
            return deployed

        async def mock_is_deployed(self):
            return hasattr(self, "id") and self.id is not None

        # Mock at the deployment level to let ResourceManager handle concurrency
        with (
            patch.object(CpuLiveServerless, "_do_deploy", mock_deploy),
            patch.object(CpuLiveServerless, "is_deployed", mock_is_deployed),
        ):

            @remote(cpu_live_serverless)
            def test_function(value: str) -> str:
                return f"result_{value}"

            # Mock the actual function execution to avoid network calls
            mock_result = "mocked_result"
            with (
                patch(
                    "runpod_flash.stubs.live_serverless.LiveServerlessStub.ExecuteFunction",
                    return_value=FunctionResponse(
                        success=True,
                        result=base64.b64encode(cloudpickle.dumps(mock_result)).decode(
                            "utf-8"
                        ),
                        error=None,
                        stdout="Mock execution output",
                    ),
                ),
                patch(
                    "runpod_flash.stubs.live_serverless.get_function_source",
                    return_value=(
                        "def test_function(value):\n    return f'result_{value}'",
                        "mock_hash",
                    ),
                ),
            ):
                # Execute multiple concurrent calls
                tasks = [test_function(f"val_{i}") for i in range(4)]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Verify no race conditions occurred
                assert len(results) == 4

                # Print exceptions for debugging
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        print(
                            f"CpuLiveServerless Race Call {i} failed with: {type(result).__name__}: {result}"
                        )

                assert all(not isinstance(result, Exception) for result in results)

                # Verify deployment order shows proper mutual exclusion
                # Should see only one start-end pair
                start_count = sum(
                    1 for item in deployment_order if item.startswith("start")
                )
                end_count = sum(
                    1 for item in deployment_order if item.startswith("end")
                )

                assert start_count == 1, (
                    f"Expected 1 deployment start, got {start_count}: {deployment_order}"
                )
                assert end_count == 1, (
                    f"Expected 1 deployment end, got {end_count}: {deployment_order}"
                )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
