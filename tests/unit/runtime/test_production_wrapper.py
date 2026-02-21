"""Tests for ProductionWrapper."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runpod_flash.runtime.production_wrapper import (
    ProductionWrapper,
    create_production_wrapper,
    reset_wrapper,
)
from runpod_flash.runtime.service_registry import ServiceRegistry


class TestProductionWrapper:
    """Test ProductionWrapper routing logic."""

    @pytest.fixture
    def mock_registry(self):
        """Mock service registry."""
        registry = AsyncMock(spec=ServiceRegistry)
        registry._ensure_manifest_loaded = AsyncMock()
        return registry

    @pytest.fixture
    def wrapper(self, mock_registry):
        """Create wrapper with mocked dependencies."""
        return ProductionWrapper(mock_registry)

    @pytest.fixture
    def sample_function(self):
        """Sample function for testing."""

        async def test_func(x, y):
            return x + y

        return test_func

    @pytest.fixture
    def original_stub(self):
        """Mock original stub function."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_wrap_function_local_execution(
        self, wrapper, mock_registry, original_stub, sample_function
    ):
        """Test routing local function to original stub."""
        mock_registry.get_resource_for_function = AsyncMock(return_value=None)

        await wrapper.wrap_function_execution(
            original_stub,
            sample_function,
            None,  # dependencies
            None,  # system_dependencies
            True,  # accelerate_downloads
            1,
            2,
            key="value",
        )

        # Should call original stub
        original_stub.assert_called_once()
        call_args = original_stub.call_args
        assert call_args[0][0] == sample_function
        assert call_args[0][4] == 1  # First arg

    @pytest.mark.asyncio
    async def test_wrap_function_remote_execution(
        self, wrapper, mock_registry, original_stub, sample_function
    ):
        """Test routing remote function via ServerlessResource."""
        mock_resource = AsyncMock()
        mock_resource.run_sync = AsyncMock()
        mock_resource.run_sync.return_value = MagicMock(error="", output=42)

        mock_registry.get_resource_for_function = AsyncMock(return_value=mock_resource)

        result = await wrapper.wrap_function_execution(
            original_stub,
            sample_function,
            None,  # dependencies
            None,  # system_dependencies
            True,  # accelerate_downloads
            1,
            2,
        )

        assert result == 42
        # Should NOT call original stub
        original_stub.assert_not_called()
        # Should call ServerlessResource.run_sync()
        mock_resource.run_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_wrap_function_not_in_manifest(
        self, wrapper, mock_registry, original_stub, sample_function
    ):
        """Test function not found in manifest executes locally."""
        mock_registry.get_resource_for_function = AsyncMock(
            side_effect=ValueError("Function not found")
        )

        await wrapper.wrap_function_execution(
            original_stub,
            sample_function,
            None,  # dependencies
            None,  # system_dependencies
            True,  # accelerate_downloads
            1,
            2,
        )

        # Should call original stub
        original_stub.assert_called_once()

    @pytest.mark.asyncio
    async def test_wrap_function_remote_error(
        self, wrapper, mock_registry, original_stub, sample_function
    ):
        """Test error handling for failed remote execution."""
        mock_resource = AsyncMock()
        mock_resource.run_sync = AsyncMock()
        mock_resource.run_sync.return_value = MagicMock(error="Remote execution failed")

        mock_registry.get_resource_for_function = AsyncMock(return_value=mock_resource)

        with pytest.raises(Exception, match="Remote execution failed"):
            await wrapper.wrap_function_execution(
                original_stub,
                sample_function,
                dependencies=None,
                system_dependencies=None,
                accelerate_downloads=True,
            )

    @pytest.mark.asyncio
    async def test_wrap_function_loads_manifest(self, wrapper, mock_registry):
        """Test that manifest is loaded before routing decision."""
        mock_registry.get_resource_for_function = AsyncMock(return_value=None)

        async def sample_func():
            pass

        original_stub = AsyncMock()
        await wrapper.wrap_function_execution(
            original_stub, sample_func, None, None, True
        )

        # Should ensure manifest is loaded
        mock_registry._ensure_manifest_loaded.assert_called_once()

    @pytest.mark.asyncio
    async def test_wrap_class_method_local(self, wrapper, mock_registry, original_stub):
        """Test routing local class method."""
        request = MagicMock()
        request.class_name = "MyClass"

        mock_registry.get_resource_for_function = AsyncMock(return_value=None)

        await wrapper.wrap_class_method_execution(original_stub, request)

        # Should call original
        original_stub.assert_called_once_with(request)

    @pytest.mark.asyncio
    async def test_wrap_class_method_remote(
        self, wrapper, mock_registry, original_stub
    ):
        """Test routing remote class method."""
        request = MagicMock()
        request.class_name = "MyClass"
        request.method_name = "process"
        request.model_dump = MagicMock(
            return_value={
                "class_name": "MyClass",
                "method_name": "process",
                "args": [],
                "kwargs": {},
            }
        )

        mock_resource = AsyncMock()
        mock_resource.run_sync = AsyncMock()
        mock_resource.run_sync.return_value = MagicMock(error="", output="done")

        mock_registry.get_resource_for_function = AsyncMock(return_value=mock_resource)

        result = await wrapper.wrap_class_method_execution(original_stub, request)

        assert result == "done"
        original_stub.assert_not_called()
        mock_resource.run_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_wrap_class_method_no_class_name(self, wrapper, original_stub):
        """Test class method with no class_name executes locally."""
        request = MagicMock()
        request.class_name = None

        await wrapper.wrap_class_method_execution(original_stub, request)

        original_stub.assert_called_once_with(request)

    @pytest.mark.asyncio
    async def test_execute_remote_payload_format(self, wrapper, sample_function):
        """Test that remote payload matches RunPod format with JSON serialization."""
        mock_resource = AsyncMock()
        mock_resource.run_sync = AsyncMock()
        mock_resource.run_sync.return_value = MagicMock(error="", output=None)

        await wrapper._execute_remote(
            mock_resource,
            "gpu_task",
            (1, 2),
            {"key": "value"},
            execution_type="function",
        )

        call_args = mock_resource.run_sync.call_args
        payload = call_args[0][0]

        assert payload["input"]["function_name"] == "gpu_task"
        assert payload["input"]["execution_type"] == "function"
        assert payload["input"]["serialization_format"] == "json"
        assert payload["input"]["args"] == [1, 2]
        assert payload["input"]["kwargs"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_execute_remote_uses_json_serialization(self, wrapper):
        """Verify payload contains serialization_format: json and raw args."""
        mock_resource = AsyncMock()
        mock_resource.run_sync = AsyncMock()
        mock_resource.run_sync.return_value = MagicMock(error="", output="result")

        await wrapper._execute_remote(
            mock_resource,
            "my_func",
            ("hello", 42),
            {"flag": True},
        )

        payload = mock_resource.run_sync.call_args[0][0]

        # Must include serialization_format
        assert payload["input"]["serialization_format"] == "json"
        # Args should be a plain list, not base64-encoded cloudpickle strings
        assert payload["input"]["args"] == ["hello", 42]
        assert isinstance(payload["input"]["args"], list)
        # Kwargs should be the raw dict
        assert payload["input"]["kwargs"] == {"flag": True}
        assert isinstance(payload["input"]["kwargs"], dict)

    @pytest.mark.asyncio
    async def test_execute_remote_args_are_plain_json(self, wrapper):
        """Verify dict/int/string args pass through without cloudpickle encoding."""
        mock_resource = AsyncMock()
        mock_resource.run_sync = AsyncMock()
        mock_resource.run_sync.return_value = MagicMock(error="", output=None)

        complex_args = (
            {"nested": {"data": [1, 2, 3]}},
            42,
            "plain_string",
            [10, 20],
        )
        complex_kwargs = {
            "config": {"batch_size": 8, "model": "gpt"},
            "count": 100,
        }

        await wrapper._execute_remote(
            mock_resource,
            "process",
            complex_args,
            complex_kwargs,
        )

        payload = mock_resource.run_sync.call_args[0][0]
        args = payload["input"]["args"]
        kwargs = payload["input"]["kwargs"]

        # Each arg should be the original value, not a base64 string
        assert args[0] == {"nested": {"data": [1, 2, 3]}}
        assert args[1] == 42
        assert args[2] == "plain_string"
        assert args[3] == [10, 20]
        # Kwargs should be the raw dict
        assert kwargs == complex_kwargs

    @pytest.mark.asyncio
    async def test_build_class_payload_dict_request(self, wrapper):
        """Test building class payload from dict request."""
        request = {
            "class_name": "MyClass",
            "method_name": "process",
            "args": ["arg1"],
            "kwargs": {"key": "value"},
        }

        payload = wrapper._build_class_payload(request)

        assert payload["input"]["function_name"] == "MyClass"
        assert payload["input"]["execution_type"] == "class"
        assert payload["input"]["method_name"] == "process"

    @pytest.mark.asyncio
    async def test_build_class_payload_object_request(self, wrapper):
        """Test building class payload from object request."""
        request = MagicMock()
        request.model_dump.return_value = {
            "class_name": "MyClass",
            "method_name": "process",
            "args": ["arg1"],
            "kwargs": {"key": "value"},
        }

        payload = wrapper._build_class_payload(request)

        assert payload["input"]["function_name"] == "MyClass"
        assert payload["input"]["execution_type"] == "class"


class TestCreateProductionWrapper:
    """Test ProductionWrapper factory function."""

    def teardown_method(self):
        """Reset wrapper after each test."""
        reset_wrapper()

    def test_create_wrapper_singleton(self):
        """Test that create_production_wrapper returns singleton."""
        wrapper1 = create_production_wrapper()
        wrapper2 = create_production_wrapper()

        assert wrapper1 is wrapper2

    def test_create_wrapper_with_custom_registry(self):
        """Test creating wrapper with custom registry."""
        registry = AsyncMock(spec=ServiceRegistry)

        wrapper = create_production_wrapper(registry)

        assert wrapper.service_registry is registry

    def test_create_wrapper_creates_defaults(self):
        """Test that wrapper creates default components."""
        with patch(
            "runpod_flash.runtime.production_wrapper.ServiceRegistry"
        ) as mock_registry_class:
            create_production_wrapper()

            # Should have created ServiceRegistry instance
            assert mock_registry_class.called

    def test_reset_wrapper(self):
        """Test resetting wrapper singleton."""
        wrapper1 = create_production_wrapper()
        reset_wrapper()
        wrapper2 = create_production_wrapper()

        assert wrapper1 is not wrapper2
