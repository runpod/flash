"""
Test configuration and fixtures for flash tests.

Provides shared fixtures for:
- Resource configurations (GPU, CPU)
- Mock API clients
- Test project structures
- Environment variable management
- Logger suppression
"""

import gc
import threading
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, Mock

import pytest

from runpod_flash.core.resources.resource_manager import ResourceManager
from runpod_flash.core.utils.singleton import SingletonMixin


def pytest_configure(config):
    """Configure pytest-xdist to respect the serial marker.

    Tests marked with @pytest.mark.serial will always run on the main worker,
    while unmarked tests can be distributed to other workers.
    """
    # This hook is called early in pytest initialization
    # xdist will check for this during test distribution


def pytest_collection_modifyitems(config, items):
    """Mark serial tests so they don't get distributed by xdist.

    This ensures that tests marked with @pytest.mark.serial run on the main
    worker (worker -1 or 0) and are never distributed to other workers.
    """
    for item in items:
        # Check if item has the serial marker
        if item.get_closest_marker("serial"):
            # Add xdist marker to prevent distribution
            item.add_marker(pytest.mark.xdist_group(name="serial"))


@pytest.fixture
def mock_asyncio_run_coro():
    """Create a mock asyncio.run that executes coroutines."""

    def run_coro(coro):
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    return run_coro


@pytest.fixture
def sample_gpu_config() -> Dict[str, Any]:
    """Provide standard GPU configuration for tests.

    Returns:
        Dictionary with LiveServerless GPU configuration.
    """
    return {
        "name": "test_gpu_worker",
        "workersMin": 0,
        "workersMax": 3,
        "idleTimeout": 5,
    }


@pytest.fixture
def sample_cpu_config() -> Dict[str, Any]:
    """Provide standard CPU configuration for tests.

    Returns:
        Dictionary with CpuLiveServerless configuration.
    """
    return {
        "name": "test_cpu_worker",
        "workersMin": 0,
        "workersMax": 5,
        "idleTimeout": 5,
    }


@pytest.fixture
def mock_runpod_client():
    """Provide mock Runpod API client.

    Returns:
        Mock object with common Runpod API methods.
    """
    client = Mock()

    # Mock common API responses
    client.save_endpoint = AsyncMock(
        return_value={"id": "test-endpoint-id", "status": "active"}
    )
    client.update_template = AsyncMock(
        return_value={"id": "test-template-id", "name": "template"}
    )
    client.get_endpoint = AsyncMock(
        return_value={"id": "test-endpoint-id", "status": "running"}
    )
    client.delete_endpoint = AsyncMock(return_value={"success": True})
    client.run_sync = AsyncMock(
        return_value={"status": "COMPLETED", "output": {"result": "success"}}
    )

    return client


@pytest.fixture
def temp_project_dir(tmp_path: Path) -> Path:
    """Provide temporary directory with common project structure.

    Creates a temporary directory with typical project layout:
    - main.py
    - workers/ directory
    - .env file

    Args:
        tmp_path: Pytest's built-in temporary directory fixture.

    Returns:
        Path to temporary project directory.
    """
    # Create standard project structure
    (tmp_path / "workers").mkdir()
    (tmp_path / "workers" / "__init__.py").touch()
    (tmp_path / "main.py").write_text("# Main application")
    (tmp_path / ".env").write_text("RUNPOD_API_KEY=test_key")

    return tmp_path


@pytest.fixture
def mock_env_vars(monkeypatch: pytest.MonkeyPatch) -> Dict[str, str]:
    """Provide patched environment variables for tests.

    Sets common environment variables needed for tests and
    returns the configuration for reference.

    Args:
        monkeypatch: Pytest's monkeypatch fixture.

    Returns:
        Dictionary of environment variables set.
    """
    env_vars = {
        "RUNPOD_API_KEY": "test_api_key_123",
        "RUNPOD_API_BASE_URL": "https://api.runpod.ai/v2",
        "LOG_LEVEL": "ERROR",  # Suppress logs during tests
    }

    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)

    return env_vars


@pytest.fixture
def mock_logger():
    """Provide mock logger to suppress log output in tests.

    Returns:
        Mock logger object.
    """
    logger = Mock()
    logger.debug = Mock()
    logger.info = Mock()
    logger.warning = Mock()
    logger.error = Mock()
    logger.critical = Mock()

    return logger


@pytest.fixture(autouse=True)
def isolate_credentials_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """force tests to use a temp credentials file."""
    credentials_path = tmp_path / "credentials.toml"
    monkeypatch.setenv("RUNPOD_CREDENTIALS_FILE", str(credentials_path))
    return credentials_path


@pytest.fixture
def sample_function_request() -> Dict[str, Any]:
    """Provide sample function request data for remote execution tests.

    Returns:
        Dictionary with typical function request structure.
    """
    return {
        "input": {"data": [1, 2, 3, 4, 5], "operation": "sum"},
        "timeout": 300,
        "idempotencyId": "test-request-123",
    }


@pytest.fixture
def sample_pod_template() -> Dict[str, Any]:
    """Provide sample PodTemplate configuration.

    Returns:
        Dictionary with PodTemplate configuration.
    """
    return {
        "name": "test_template",
        "imageName": "test/image:latest",
        "containerDiskInGb": 64,
        "env": {"PYTHONUNBUFFERED": "1"},
    }


@pytest.fixture(scope="session")
def worker_temp_dir(
    tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest
) -> Path:
    """Provide worker-specific temporary directory for file system isolation.

    Each xdist worker gets its own isolated temp directory to prevent
    file system conflicts when tests write to shared paths. The worker ID
    is extracted from the pytest-xdist request object.

    Args:
        tmp_path_factory: Pytest's temporary path factory.
        request: Pytest request object used to extract worker ID.

    Returns:
        Path to worker-specific temporary directory.
    """
    worker_id = getattr(request.config, "workerinput", {}).get("workerid", "master")

    if worker_id == "master":
        # Single worker (non-parallel)
        return tmp_path_factory.mktemp("test_data")
    else:
        # Parallel execution - worker-specific directory
        return tmp_path_factory.mktemp(f"test_data_{worker_id}")


@pytest.fixture(scope="session")
def worker_runpod_dir(worker_temp_dir: Path) -> Path:
    """Provide worker-specific .runpod directory for state file isolation.

    Args:
        worker_temp_dir: Worker-specific temporary directory.

    Returns:
        Path to worker-specific .runpod directory.
    """
    runpod_dir = worker_temp_dir / ".runpod"
    runpod_dir.mkdir(parents=True, exist_ok=True)
    return runpod_dir


@pytest.fixture(autouse=True)
def isolate_resource_state_file(
    monkeypatch: pytest.MonkeyPatch, worker_runpod_dir: Path
) -> Path:
    """Automatically isolate RESOURCE_STATE_FILE per worker.

    Patches RESOURCE_STATE_FILE and RUNPOD_FLASH_DIR to point to
    worker-specific temp directory, preventing file system conflicts.

    Args:
        monkeypatch: Pytest's monkeypatch fixture.
        worker_runpod_dir: Worker-specific .runpod directory.

    Returns:
        Path to worker-specific state file.
    """
    from runpod_flash.core.resources import resource_manager

    worker_state_file = worker_runpod_dir / "resources.pkl"
    monkeypatch.setattr(resource_manager, "RESOURCE_STATE_FILE", worker_state_file)
    monkeypatch.setattr(resource_manager, "RUNPOD_FLASH_DIR", worker_runpod_dir)

    return worker_state_file


@pytest.fixture(autouse=True)
def clear_live_provisioning_env(monkeypatch: pytest.MonkeyPatch):
    """Clear FLASH_IS_LIVE_PROVISIONING env var between tests.

    This fixture ensures that the flag set by `flash run` command
    doesn't leak into unit tests. It's autouse so it runs for all tests.

    Args:
        monkeypatch: Pytest's monkeypatch fixture.
    """
    # Explicitly unset the variable before each test
    monkeypatch.delenv("FLASH_IS_LIVE_PROVISIONING", raising=False)
    # Cleanup is automatic: monkeypatch restores the environment after each test
    yield


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset singleton instances between tests.

    This fixture runs automatically for all tests to ensure
    clean state between test executions.
    """
    # Patch cloudpickle to handle threading.Lock objects that may be left over
    # from previous tests. This prevents "cannot pickle '_thread.lock'" errors
    # when test pollution causes old lock instances to be in the object graph.
    try:
        import cloudpickle
        import copyreg

        def _lock_reducer(lock):
            """Reducer for threading.Lock that creates a new lock on unpickle."""
            return (threading.Lock, ())

        # Register the reducer for threading.Lock in copyreg so cloudpickle uses it
        copyreg.pickle(threading.Lock, _lock_reducer)

        # Also patch cloudpickle.CloudPickler to use the reducer
        original_reducer_override = cloudpickle.CloudPickler.reducer_override

        def patched_reducer_override(self, obj):
            if isinstance(obj, type(threading.Lock())):
                return _lock_reducer(obj)
            return original_reducer_override(self, obj)

        cloudpickle.CloudPickler.reducer_override = patched_reducer_override
    except Exception:
        # If patching fails, continue anyway - the test might still pass
        pass

    # Clear module-level caches (worker-isolated due to process boundaries)
    try:
        from runpod_flash.stubs.live_serverless import _SERIALIZED_FUNCTION_CACHE
        from runpod_flash.execute_class import _SERIALIZED_CLASS_CACHE

        _SERIALIZED_FUNCTION_CACHE.clear()
        _SERIALIZED_CLASS_CACHE.clear()
    except (ImportError, AttributeError):
        # Caches may not exist in all configurations
        pass

    # Reset SingletonMixin instances to clear any accumulated state
    # This prevents old singleton instances from leaking into object graphs during pickling
    SingletonMixin._instances = {}

    # Also reset ResourceManager class variables to ensure clean state
    ResourceManager._resources = {}
    ResourceManager._resource_configs = {}
    ResourceManager._deployment_locks = {}
    ResourceManager._global_lock = None
    ResourceManager._lock_initialized = False
    ResourceManager._resources_initialized = False

    # Reset ResourceManager singleton if it exists
    if hasattr(ResourceManager, "_instance"):
        ResourceManager._instance = None

    # Force garbage collection to ensure old instances are truly freed
    gc.collect()

    yield

    # Cleanup after test
    try:
        from runpod_flash.stubs.live_serverless import _SERIALIZED_FUNCTION_CACHE
        from runpod_flash.execute_class import _SERIALIZED_CLASS_CACHE

        _SERIALIZED_FUNCTION_CACHE.clear()
        _SERIALIZED_CLASS_CACHE.clear()
    except (ImportError, AttributeError):
        pass

    SingletonMixin._instances = {}

    ResourceManager._resources = {}
    ResourceManager._resource_configs = {}
    ResourceManager._deployment_locks = {}
    ResourceManager._global_lock = None
    ResourceManager._lock_initialized = False
    ResourceManager._resources_initialized = False

    if hasattr(ResourceManager, "_instance"):
        ResourceManager._instance = None

    gc.collect()
