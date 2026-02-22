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
        mock_registry.get_routing_info = AsyncMock(return_value=None)

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
    async def test_wrap_function_remote_qb_execution(
        self, wrapper, mock_registry, original_stub, sample_function
    ):
        """Test routing remote QB function sends plain JSON kwargs via runsync."""
        mock_registry.get_routing_info = AsyncMock(
            return_value={
                "resource_name": "gpu_config",
                "endpoint_url": "https://api.runpod.ai/v2/abc123",
                "is_load_balanced": False,
                "http_method": None,
                "http_path": None,
            }
        )

        mock_resource = AsyncMock()
        mock_resource.runsync = AsyncMock()
        mock_resource.runsync.return_value = MagicMock(error="", output=42)

        with patch(
            "runpod_flash.runtime.production_wrapper.ServerlessResource",
            return_value=mock_resource,
        ):
            result = await wrapper.wrap_function_execution(
                original_stub,
                sample_function,
                None,
                None,
                True,
                1,
                2,
            )

        assert result == 42
        original_stub.assert_not_called()
        mock_resource.runsync.assert_called_once()

        # Verify payload is plain JSON kwargs mapped from positional args
        payload = mock_resource.runsync.call_args[0][0]
        assert payload == {"input": {"x": 1, "y": 2}}

    @pytest.mark.asyncio
    async def test_wrap_function_remote_lb_execution(
        self, wrapper, mock_registry, original_stub, sample_function
    ):
        """Test routing remote LB function sends HTTP request to endpoint URL."""
        mock_registry.get_routing_info = AsyncMock(
            return_value={
                "resource_name": "lb_config",
                "endpoint_url": "https://lb.example.com",
                "is_load_balanced": True,
                "http_method": "POST",
                "http_path": "/api/process",
            }
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "processed"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "runpod_flash.runtime.production_wrapper.get_authenticated_httpx_client",
            return_value=mock_client,
        ):
            result = await wrapper.wrap_function_execution(
                original_stub,
                sample_function,
                None,
                None,
                True,
                1,
                2,
            )

        assert result == {"result": "processed"}
        original_stub.assert_not_called()

        # Verify HTTP call to correct method/path/URL
        mock_client.request.assert_called_once()
        call_args = mock_client.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "https://lb.example.com/api/process"

    @pytest.mark.asyncio
    async def test_wrap_function_not_in_manifest(
        self, wrapper, mock_registry, original_stub, sample_function
    ):
        """Test function not found in manifest executes locally."""
        mock_registry.get_routing_info = AsyncMock(
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
    async def test_wrap_function_remote_qb_error(
        self, wrapper, mock_registry, original_stub, sample_function
    ):
        """Test error handling for failed remote QB execution."""
        mock_registry.get_routing_info = AsyncMock(
            return_value={
                "resource_name": "gpu_config",
                "endpoint_url": "https://api.runpod.ai/v2/abc123",
                "is_load_balanced": False,
                "http_method": None,
                "http_path": None,
            }
        )

        mock_resource = AsyncMock()
        mock_resource.runsync = AsyncMock()
        mock_resource.runsync.return_value = MagicMock(error="Remote execution failed")

        with patch(
            "runpod_flash.runtime.production_wrapper.ServerlessResource",
            return_value=mock_resource,
        ):
            with pytest.raises(Exception, match="Remote execution failed"):
                await wrapper.wrap_function_execution(
                    original_stub,
                    sample_function,
                    dependencies=None,
                    system_dependencies=None,
                    accelerate_downloads=True,
                )

    @pytest.mark.asyncio
    async def test_wrap_function_calls_get_routing_info(self, wrapper, mock_registry):
        """Test that get_routing_info is called for routing decision."""
        mock_registry.get_routing_info = AsyncMock(return_value=None)

        async def sample_func():
            pass

        original_stub = AsyncMock()
        await wrapper.wrap_function_execution(
            original_stub, sample_func, None, None, True
        )

        mock_registry.get_routing_info.assert_called_once_with("sample_func")

    @pytest.mark.asyncio
    async def test_wrap_class_method_local(self, wrapper, mock_registry, original_stub):
        """Test routing local class method."""
        request = MagicMock()
        request.class_name = "MyClass"

        mock_registry.get_routing_info = AsyncMock(return_value=None)

        await wrapper.wrap_class_method_execution(original_stub, request)

        # Should call original
        original_stub.assert_called_once_with(request)

    @pytest.mark.asyncio
    async def test_wrap_class_method_remote(
        self, wrapper, mock_registry, original_stub
    ):
        """Test routing remote class method via QB dispatch."""
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

        mock_registry.get_routing_info = AsyncMock(
            return_value={
                "resource_name": "gpu_config",
                "endpoint_url": "https://api.runpod.ai/v2/abc123",
                "is_load_balanced": False,
                "http_method": None,
                "http_path": None,
            }
        )

        mock_resource = AsyncMock()
        mock_resource.runsync = AsyncMock()
        mock_resource.runsync.return_value = MagicMock(error="", output="done")

        with patch(
            "runpod_flash.runtime.production_wrapper.ServerlessResource",
            return_value=mock_resource,
        ):
            result = await wrapper.wrap_class_method_execution(original_stub, request)

        assert result == "done"
        original_stub.assert_not_called()
        mock_resource.runsync.assert_called_once()

    @pytest.mark.asyncio
    async def test_wrap_class_method_no_class_name(self, wrapper, original_stub):
        """Test class method with no class_name executes locally."""
        request = MagicMock()
        request.class_name = None

        await wrapper.wrap_class_method_execution(original_stub, request)

        original_stub.assert_called_once_with(request)

    @pytest.mark.asyncio
    async def test_execute_remote_qb_maps_args_to_kwargs(
        self, wrapper, sample_function
    ):
        """Test that QB dispatch maps positional args to named kwargs."""
        routing_info = {
            "resource_name": "gpu_config",
            "endpoint_url": "https://api.runpod.ai/v2/abc123",
            "is_load_balanced": False,
        }

        mock_resource = AsyncMock()
        mock_resource.runsync = AsyncMock()
        mock_resource.runsync.return_value = MagicMock(error="", output=None)

        with patch(
            "runpod_flash.runtime.production_wrapper.ServerlessResource",
            return_value=mock_resource,
        ):
            await wrapper._execute_remote_qb(
                routing_info=routing_info,
                func=sample_function,
                args=(1, 2),
                kwargs={"extra": "val"},
            )

        payload = mock_resource.runsync.call_args[0][0]
        # Positional args mapped to parameter names (x, y) via inspect.signature
        assert payload["input"]["x"] == 1
        assert payload["input"]["y"] == 2
        assert payload["input"]["extra"] == "val"

    @pytest.mark.asyncio
    async def test_execute_remote_qb_no_endpoint_url(self, wrapper, sample_function):
        """Test QB dispatch raises when no endpoint URL."""
        routing_info = {
            "resource_name": "gpu_config",
            "endpoint_url": None,
            "is_load_balanced": False,
        }

        with pytest.raises(Exception, match="No endpoint URL"):
            await wrapper._execute_remote_qb(
                routing_info=routing_info,
                func=sample_function,
                args=(),
                kwargs={},
            )

    @pytest.mark.asyncio
    async def test_execute_remote_lb_no_endpoint_url(self, wrapper):
        """Test LB dispatch raises when no endpoint URL."""
        with pytest.raises(Exception, match="No endpoint URL"):
            await wrapper._execute_remote_lb(
                endpoint_url="",
                http_method="POST",
                http_path="/api/test",
                args=(),
                kwargs={},
                function_name="test_func",
            )

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
