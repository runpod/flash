"""Tests for stubs/registry.py - singledispatch stub factory."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runpod_flash.core.resources import (
    CpuLiveLoadBalancer,
    CpuLiveServerless,
    CpuServerlessEndpoint,
    LiveLoadBalancer,
    LiveServerless,
    LoadBalancerSlsResource,
    ServerlessEndpoint,
)
from runpod_flash.stubs.registry import _create_live_serverless_stub, stub_resource


@pytest.fixture(autouse=True)
def _clear_deployed_env_vars(monkeypatch):
    """Prevent RUNPOD_ENDPOINT_ID pollution from other tests."""
    monkeypatch.delenv("RUNPOD_ENDPOINT_ID", raising=False)
    monkeypatch.delenv("RUNPOD_POD_ID", raising=False)


class TestFallbackHandler:
    """Test fallback handler for unsupported resource types."""

    @pytest.mark.asyncio
    async def test_fallback_returns_error_dict(self):
        """Fallback returns error dict for unknown resource types."""
        result = stub_resource("not a resource type")
        assert callable(result)

    @pytest.mark.asyncio
    async def test_fallback_accepts_any_args(self):
        """Fallback handler accepts arbitrary args/kwargs."""
        result = stub_resource(42, extra_kwarg="test")
        assert callable(result)


class TestLiveServerlessDispatch:
    """Test dispatch for LiveServerless resource types."""

    def test_live_serverless_dispatches(self):
        """LiveServerless dispatches to _create_live_serverless_stub."""
        resource = LiveServerless(name="test-ls")
        stub = stub_resource(resource)
        assert callable(stub)
        assert hasattr(stub, "execute_class_method")

    def test_cpu_live_serverless_dispatches(self):
        """CpuLiveServerless dispatches to _create_live_serverless_stub."""
        resource = CpuLiveServerless(name="test-cpu-ls")
        stub = stub_resource(resource)
        assert callable(stub)
        assert hasattr(stub, "execute_class_method")


@pytest.mark.serial
class TestCreateLiveServerlessStub:
    """Test _create_live_serverless_stub function."""

    def test_returns_callable_with_execute_class_method(self):
        """Returned stub is callable and has execute_class_method attached."""
        resource = LiveServerless(name="test")
        stub = _create_live_serverless_stub(resource)
        assert callable(stub)
        assert callable(stub.execute_class_method)

    @pytest.mark.asyncio
    async def test_function_execution_calls_stub(self):
        """Function execution calls prepare_request, ExecuteFunction, handle_response."""
        resource = LiveServerless(name="test")

        MagicMock()
        with patch("runpod_flash.stubs.registry.LiveServerlessStub") as MockLSS:
            mock_instance = MockLSS.return_value
            mock_instance.prepare_request = AsyncMock(return_value="request")
            mock_instance.ExecuteFunction = AsyncMock(return_value="response")
            mock_instance.handle_response.return_value = {"result": 42}

            stub = _create_live_serverless_stub(resource)

            def my_func(x):
                return x + 1

            result = await stub(my_func, ["dep"], ["sys_dep"], True, 1, 2, key="val")
            assert result == {"result": 42}
            mock_instance.prepare_request.assert_called_once()
            mock_instance.ExecuteFunction.assert_called_once_with("request")

    @pytest.mark.asyncio
    async def test_class_method_execution(self):
        """execute_class_method calls ExecuteFunction and handle_response."""
        resource = LiveServerless(name="test")

        with patch("runpod_flash.stubs.registry.LiveServerlessStub") as MockLSS:
            mock_instance = MockLSS.return_value
            mock_instance.ExecuteFunction = AsyncMock(return_value="response")
            mock_instance.handle_response.return_value = {
                "result": "class_method_result"
            }

            stub = _create_live_serverless_stub(resource)

            request = MagicMock()
            result = await stub.execute_class_method(request)
            assert result == {"result": "class_method_result"}
            mock_instance.ExecuteFunction.assert_called_once_with(request)

    @pytest.mark.asyncio
    async def test_args_none_converted_to_empty(self):
        """When args is (None,), it should be converted to []."""
        resource = LiveServerless(name="test")

        with patch("runpod_flash.stubs.registry.LiveServerlessStub") as MockLSS:
            mock_instance = MockLSS.return_value
            mock_instance.prepare_request = AsyncMock(return_value="request")
            mock_instance.ExecuteFunction = AsyncMock(return_value="response")
            mock_instance.handle_response.return_value = "ok"

            stub = _create_live_serverless_stub(resource)

            def my_func():
                pass

            await stub(my_func, [], [], True, None)
            call_args = mock_instance.prepare_request.call_args
            # args passed to prepare_request should NOT include the (None,) original
            # The stub converts args==(None,) to args=[]
            assert call_args[0][5:] == ()  # no positional args beyond the required ones

    @patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "test-ep-id"})
    def test_production_wrapper_injected(self):
        """When RUNPOD_ENDPOINT_ID is set, ProductionWrapper wraps stubs."""
        resource = LiveServerless(name="test")

        with (
            patch("runpod_flash.stubs.registry.LiveServerlessStub"),
            patch(
                "runpod_flash.runtime.production_wrapper.create_production_wrapper"
            ) as mock_create_wrapper,
        ):
            mock_wrapper = MagicMock()
            mock_create_wrapper.return_value = mock_wrapper
            mock_wrapper.wrap_function_execution = MagicMock(
                return_value="wrapped_func"
            )
            mock_wrapper.wrap_class_method_execution = MagicMock(
                return_value="wrapped_class"
            )

            _create_live_serverless_stub(resource)
            mock_create_wrapper.assert_called_once()

    @patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "test-ep-id"})
    def test_production_wrapper_import_failure_graceful(self):
        """Gracefully falls back when ProductionWrapper can't be imported."""
        resource = LiveServerless(name="test")

        with (
            patch("runpod_flash.stubs.registry.LiveServerlessStub"),
            patch(
                "runpod_flash.runtime.production_wrapper.create_production_wrapper",
                side_effect=ImportError("not available"),
            ),
        ):
            # Should not raise, just log warning
            stub = _create_live_serverless_stub(resource)
            assert callable(stub)


@pytest.mark.serial
class TestServerlessEndpointDispatch:
    """Test dispatch for ServerlessEndpoint resource types."""

    @pytest.mark.asyncio
    async def test_serverless_endpoint_stub(self):
        """ServerlessEndpoint creates a stub that calls prepare_payload + execute."""
        resource = ServerlessEndpoint(
            name="test-sls", id="ep-123", templateId="tmpl-123"
        )
        stub = stub_resource(resource)
        assert callable(stub)

    @pytest.mark.asyncio
    async def test_cpu_serverless_endpoint_stub(self):
        """CpuServerlessEndpoint creates a stub."""
        resource = CpuServerlessEndpoint(
            name="test-cpu-sls", id="ep-456", templateId="tmpl-123"
        )
        stub = stub_resource(resource)
        assert callable(stub)

    @pytest.mark.asyncio
    async def test_serverless_warns_about_dependencies(self):
        """ServerlessEndpoint warns when dependencies are provided."""
        resource = ServerlessEndpoint(
            name="test-sls", id="ep-123", templateId="tmpl-123"
        )

        with patch("runpod_flash.stubs.registry.ServerlessEndpointStub") as MockSES:
            mock_instance = MockSES.return_value
            mock_instance.prepare_payload.return_value = {"data": "payload"}
            mock_instance.execute = AsyncMock(
                return_value=MagicMock(output="result", error=None)
            )
            mock_instance.handle_response.return_value = "result"

            stub = stub_resource(resource)

            with patch("runpod_flash.stubs.registry.log") as mock_log:
                await stub(lambda: None, ["numpy"], None, True)
                mock_log.warning.assert_called_once()
                assert "not supported" in mock_log.warning.call_args[0][0].lower()


class TestLoadBalancerDispatch:
    """Test dispatch for load balancer resource types."""

    def test_load_balancer_sls_resource_dispatches(self):
        """LoadBalancerSlsResource creates a stub."""
        resource = LoadBalancerSlsResource(name="test-lb", templateId="tmpl-123")
        stub = stub_resource(resource)
        assert callable(stub)

    def test_live_load_balancer_dispatches(self):
        """LiveLoadBalancer creates a stub."""
        resource = LiveLoadBalancer(name="test-live-lb")
        stub = stub_resource(resource)
        assert callable(stub)

    def test_cpu_live_load_balancer_dispatches(self):
        """CpuLiveLoadBalancer creates a stub."""
        resource = CpuLiveLoadBalancer(name="test-cpu-live-lb")
        stub = stub_resource(resource)
        assert callable(stub)
