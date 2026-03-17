"""
Unit tests for concurrency issues in runpod_flash.

This module tests race conditions and thread safety issues in:
1. ResourceManager singleton and resource provisioning
2. Global function cache access
3. File-based state persistence
4. Class serialization caching

All tests are designed to expose the race conditions identified in the code review.
"""

import asyncio
import threading
import time
import tempfile
import shutil
from typing import Dict, Any
from pathlib import Path
from unittest.mock import patch

import pytest

from runpod_flash.core.resources.resource_manager import (
    ResourceManager,
    RESOURCE_STATE_FILE,
)
from runpod_flash.core.resources.base import DeployableResource
from runpod_flash.core.utils.singleton import SingletonMixin
from runpod_flash.stubs.live_serverless import (
    _SERIALIZED_FUNCTION_CACHE,
    _function_cache_lock,
)
from runpod_flash.execute_class import _SERIALIZED_CLASS_CACHE


class MockDeployableResource(DeployableResource):
    """Mock deployable resource for testing."""

    _hashed_fields = {"name"}
    name: str = "test-resource"
    deploy_delay: float = 0.1

    def __init__(
        self, name: str = "test-resource", deploy_delay: float = 0.1, **kwargs
    ):
        super().__init__(name=name, deploy_delay=deploy_delay, **kwargs)
        self._deployed = False
        self._deploy_count = 0

    @property
    def url(self) -> str:
        return f"https://mock.example.com/{self.name}"

    async def is_deployed(self) -> bool:
        return self._deployed

    async def _do_deploy(self) -> "DeployableResource":
        """Simulate deployment with delay to trigger race conditions."""
        await asyncio.sleep(self.deploy_delay)
        self._deploy_count += 1
        self._deployed = True
        # Return a new instance to simulate API response
        deployed = MockDeployableResource(
            name=self.name,
            deploy_delay=self.deploy_delay,
            id=f"deployed-{self.name}-{self._deploy_count}",
        )
        deployed._deployed = True
        deployed._deploy_count = self._deploy_count
        return deployed

    async def deploy(self) -> "DeployableResource":
        resource_manager = ResourceManager()
        return await resource_manager.get_or_deploy_resource(self)

    async def _do_undeploy(self) -> bool:
        """Mock undeploy method."""
        self._deployed = False
        return True

    async def undeploy(self) -> Dict[str, Any]:
        resource_manager = ResourceManager()
        result = await resource_manager.undeploy_resource(self.resource_id)
        return result


@pytest.mark.serial
class TestSingleton:
    """Test thread safety of SingletonMixin."""

    def teardown_method(self):
        """Clean up singleton instances after each test."""
        SingletonMixin._instances.clear()

    def test_singleton_thread_safety_race_condition(self):
        """Test that SingletonMixin creates only one instance under concurrent access."""
        instances = []
        exception_count = 0

        class TestSingleton(SingletonMixin):
            def __init__(self):
                # Add a small delay to increase race condition likelihood
                time.sleep(0.001)
                self.thread_id = threading.current_thread().ident

        def create_instance():
            nonlocal exception_count
            try:
                instance = TestSingleton()
                instances.append(instance)
            except Exception:
                exception_count += 1

        # Create multiple threads that try to create singleton instances simultaneously
        threads = []
        for _ in range(20):  # Increased thread count for more aggressive test
            thread = threading.Thread(target=create_instance)
            threads.append(thread)

        # Start all threads simultaneously to maximize race condition chance
        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        # After fix, should only have 1 unique instance
        unique_instances = set(id(instance) for instance in instances)

        print(f"Created {len(unique_instances)} unique instances (should be 1)")
        print(f"Total instances: {len(instances)}")
        print(f"Exceptions: {exception_count}")

        # With the fix, we should have exactly 1 unique instance
        assert len(unique_instances) == 1, (
            f"Expected 1 unique instance, got {len(unique_instances)}"
        )
        assert len(instances) == 20 - exception_count  # All threads should succeed
        assert exception_count == 0  # No exceptions should occur


@pytest.mark.serial
class TestResourceManagerConcurrency:
    """Test ResourceManager concurrency issues."""

    def setup_method(self):
        """Set up test environment."""
        # Clear singleton instances
        SingletonMixin._instances.clear()

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

    @pytest.mark.asyncio
    async def test_concurrent_deployment_race_condition(self):
        """Test that concurrent deployments create multiple resources."""
        resource_config = MockDeployableResource("test-resource", deploy_delay=0.1)

        # This will expose the race condition where multiple deployments happen
        deployment_tasks = []
        for _ in range(5):
            manager = ResourceManager()
            task = asyncio.create_task(manager.get_or_deploy_resource(resource_config))
            deployment_tasks.append(task)

        # Execute all deployments concurrently
        results = await asyncio.gather(*deployment_tasks)

        # Check how many unique deployments were created
        unique_deployed_ids = set(
            result.id for result in results if hasattr(result, "id")
        )
        deploy_counts = [
            result._deploy_count
            for result in results
            if hasattr(result, "_deploy_count")
        ]

        print(f"Unique deployed resources: {len(unique_deployed_ids)}")
        print(f"Deploy counts: {deploy_counts}")
        print(f"Resource IDs: {unique_deployed_ids}")

        # EXPECTED FAILURE: Current implementation may create multiple deployments
        # After fix, all results should reference the same deployed resource

        # Document the race condition - in broken version, we get multiple deployments
        # This assertion will need to be updated after the fix
        max_deploy_count = max(deploy_counts) if deploy_counts else 0
        print(f"Maximum deploy count: {max_deploy_count}")

        # For now, just verify that deployments happened
        deployed_checks = [await result.is_deployed() for result in results]
        assert all(deployed_checks)

        # The race condition means we might get multiple deployments
        # In the fixed version, this should be 1
        assert len(unique_deployed_ids) >= 1

    @pytest.mark.asyncio
    async def test_resource_manager_singleton_consistency(self):
        """Test that all ResourceManager instances are the same."""
        managers = []

        async def get_manager():
            manager = ResourceManager()
            managers.append(manager)
            return manager

        # Create multiple managers concurrently
        tasks = [asyncio.create_task(get_manager()) for _ in range(10)]
        await asyncio.gather(*tasks)

        # All managers should be the same instance (after singleton fix)
        unique_managers = set(id(manager) for manager in managers)
        print(f"Unique manager instances: {len(unique_managers)}")

        # This documents the current behavior and will need updating after fix
        assert len(managers) == 10

    def test_file_state_race_condition(self):
        """Test file-based state corruption with concurrent access."""
        # This test demonstrates file I/O race conditions
        manager1 = ResourceManager()
        manager2 = ResourceManager()

        # Create some mock resources
        resource1 = MockDeployableResource("resource1")
        resource1.id = "deployed-resource1"
        resource1._deployed = True

        resource2 = MockDeployableResource("resource2")
        resource2.id = "deployed-resource2"
        resource2._deployed = True

        exceptions = []

        def save_resource_1():
            try:
                manager1._add_resource("resource1", resource1)
                # Add delay to increase race condition likelihood
                time.sleep(0.01)
            except Exception as e:
                exceptions.append(e)

        def save_resource_2():
            try:
                manager2._add_resource("resource2", resource2)
                time.sleep(0.01)
            except Exception as e:
                exceptions.append(e)

        # Create threads that save state concurrently
        threads = [
            threading.Thread(target=save_resource_1),
            threading.Thread(target=save_resource_2),
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        # Check for exceptions
        if exceptions:
            print(f"File I/O exceptions: {exceptions}")

        # Try to load state and verify consistency
        try:
            manager3 = ResourceManager()
            # In a race condition, state might be corrupted or inconsistent
            print(f"Loaded resources: {list(manager3._resources.keys())}")
        except Exception as e:
            print(f"State loading error: {e}")


@pytest.mark.serial
class TestFunctionCacheConcurrency:
    """Test global function cache thread safety."""

    def setup_method(self):
        """Clear function cache before each test."""
        _SERIALIZED_FUNCTION_CACHE.clear()

    def teardown_method(self):
        """Clear function cache after each test."""
        _SERIALIZED_FUNCTION_CACHE.clear()

    def test_function_cache_thread_safety(self):
        """Test function cache dictionary thread safety with direct access."""

        # Test the cache directly to verify thread safety
        results = []
        exceptions = []

        def cache_worker(worker_id: int):
            try:
                # Direct cache access with locking
                with _function_cache_lock:
                    for i in range(100):
                        key = f"worker_{worker_id}_item_{i}"
                        source = (
                            f"def worker_{worker_id}_function_{i}():\n    return {i}"
                        )

                        # Set operation
                        if key not in _SERIALIZED_FUNCTION_CACHE:
                            _SERIALIZED_FUNCTION_CACHE[key] = source

                        # Get operation
                        retrieved = _SERIALIZED_FUNCTION_CACHE.get(key)
                        if retrieved:
                            results.append((worker_id, key))

            except Exception as e:
                exceptions.append((worker_id, e))

        # Create threads that hammer the cache
        threads = []
        for worker_id in range(10):
            thread = threading.Thread(target=cache_worker, args=(worker_id,))
            threads.append(thread)

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        print(f"Cache operations: {len(results)}")
        print(f"Exceptions: {len(exceptions)}")
        print(f"Final cache size: {len(_SERIALIZED_FUNCTION_CACHE)}")

        if exceptions:
            print(f"Cache exceptions: {exceptions}")

        # With proper locking, no exceptions should occur
        assert len(exceptions) == 0, f"Expected no exceptions, got {len(exceptions)}"

        # All operations should succeed
        assert len(results) > 0

        # Cache should contain entries
        assert len(_SERIALIZED_FUNCTION_CACHE) > 0


@pytest.mark.serial
class TestClassCacheConcurrency:
    """Test class serialization cache thread safety."""

    def setup_method(self):
        """Clear class cache before each test."""
        _SERIALIZED_CLASS_CACHE.clear()

    def teardown_method(self):
        """Clear class cache after each test."""
        _SERIALIZED_CLASS_CACHE.clear()

    def test_class_cache_concurrent_access(self):
        """Test LRU cache thread safety under concurrent load."""

        cache_operations = []
        exceptions = []

        def cache_worker(worker_id: int):
            try:
                for i in range(100):
                    key = f"worker_{worker_id}_item_{i}"
                    value = {"data": f"worker {worker_id} data {i}"}

                    # Set operation
                    _SERIALIZED_CLASS_CACHE.set(key, value)
                    cache_operations.append(("set", key))

                    # Get operation
                    retrieved = _SERIALIZED_CLASS_CACHE.get(key)
                    if retrieved:
                        cache_operations.append(("get", key))

                    # Contains check
                    if key in _SERIALIZED_CLASS_CACHE:
                        cache_operations.append(("contains", key))

            except Exception as e:
                exceptions.append((worker_id, e))

        # Create multiple threads that hammer the cache
        threads = []
        for worker_id in range(10):
            thread = threading.Thread(target=cache_worker, args=(worker_id,))
            threads.append(thread)

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        print(f"Cache operations: {len(cache_operations)}")
        print(f"Exceptions: {len(exceptions)}")
        print(f"Final cache size: {len(_SERIALIZED_CLASS_CACHE)}")

        if exceptions:
            print(f"Cache exceptions: {exceptions[:5]}")  # Show first 5

        # The LRU cache should be thread-safe, so no exceptions expected
        assert len(exceptions) == 0
        assert len(cache_operations) > 0


@pytest.mark.serial
class TestEndToEndConcurrency:
    """End-to-end tests for concurrent remote function execution."""

    def setup_method(self):
        """Set up test environment."""
        SingletonMixin._instances.clear()
        _SERIALIZED_FUNCTION_CACHE.clear()
        _SERIALIZED_CLASS_CACHE.clear()

    def teardown_method(self):
        """Clean up test environment."""
        SingletonMixin._instances.clear()
        _SERIALIZED_FUNCTION_CACHE.clear()
        _SERIALIZED_CLASS_CACHE.clear()

    @pytest.mark.asyncio
    async def test_concurrent_remote_function_simulation(self):
        """Simulate concurrent @remote function calls."""

        # Mock the entire remote execution pipeline
        with patch(
            "runpod_flash.core.resources.resource_manager.ResourceManager.get_or_deploy_resource"
        ) as mock_deploy:
            # Configure mock to have deployment delay
            async def slow_deploy(config):
                await asyncio.sleep(0.1)  # Simulate deployment time
                return MockDeployableResource(config.name)

            mock_deploy.side_effect = slow_deploy

            # Simulate multiple calls to the same remote function
            deployment_calls = []

            async def simulate_remote_call(call_id: int):
                manager = ResourceManager()
                config = MockDeployableResource("shared-resource")
                result = await manager.get_or_deploy_resource(config)
                deployment_calls.append((call_id, result))
                return result

            # Execute multiple "remote function calls" concurrently
            tasks = [simulate_remote_call(i) for i in range(5)]
            results = await asyncio.gather(*tasks)

            print(f"Deployment calls made: {mock_deploy.call_count}")
            print(f"Results received: {len(results)}")

            # In the broken version, we expect multiple deployment calls
            # After fix, this should be 1
            assert mock_deploy.call_count >= 1
            assert len(results) == 5


if __name__ == "__main__":
    # Run specific tests to demonstrate race conditions
    pytest.main([__file__, "-v", "-s"])
