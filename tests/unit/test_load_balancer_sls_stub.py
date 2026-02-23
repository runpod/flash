"""Unit tests for LoadBalancerSlsStub functionality."""

import base64
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import cloudpickle

from runpod_flash import LoadBalancerSlsResource
from runpod_flash.stubs.load_balancer_sls import LoadBalancerSlsStub


# Create test resources
test_lb_resource = LoadBalancerSlsResource(
    name="test-lb",
    imageName="test:latest",
)


class TestLoadBalancerSlsStubPrepareRequest:
    """Test suite for _prepare_request method."""

    @pytest.mark.asyncio
    async def test_prepare_request_with_no_args(self):
        """Test request preparation with no arguments."""
        stub = LoadBalancerSlsStub(test_lb_resource)

        def test_func():
            return "result"

        request = await stub._prepare_request(test_func, None, None, True)

        assert request["function_name"] == "test_func"
        assert "def test_func" in request["function_code"]
        assert request["dependencies"] == []
        assert request["system_dependencies"] == []
        assert request["accelerate_downloads"] is True
        assert "args" not in request or request["args"] == []
        assert "kwargs" not in request or request["kwargs"] == {}

    @pytest.mark.asyncio
    async def test_prepare_request_with_args(self):
        """Test request preparation with positional arguments."""
        stub = LoadBalancerSlsStub(test_lb_resource)

        def add(x, y):
            return x + y

        arg1 = 5
        arg2 = 3
        request = await stub._prepare_request(add, None, None, True, arg1, arg2)

        assert request["function_name"] == "add"
        assert len(request["args"]) == 2

        # Verify args are properly serialized
        decoded_arg1 = cloudpickle.loads(base64.b64decode(request["args"][0]))
        decoded_arg2 = cloudpickle.loads(base64.b64decode(request["args"][1]))
        assert decoded_arg1 == 5
        assert decoded_arg2 == 3

    @pytest.mark.asyncio
    async def test_prepare_request_with_kwargs(self):
        """Test request preparation with keyword arguments."""
        stub = LoadBalancerSlsStub(test_lb_resource)

        def greet(name, greeting="Hello"):
            return f"{greeting}, {name}!"

        request = await stub._prepare_request(
            greet, None, None, True, name="Alice", greeting="Hi"
        )

        assert "kwargs" in request
        assert len(request["kwargs"]) == 2

        # Verify kwargs are properly serialized
        decoded_name = cloudpickle.loads(base64.b64decode(request["kwargs"]["name"]))
        decoded_greeting = cloudpickle.loads(
            base64.b64decode(request["kwargs"]["greeting"])
        )
        assert decoded_name == "Alice"
        assert decoded_greeting == "Hi"

    @pytest.mark.asyncio
    async def test_prepare_request_with_dependencies(self):
        """Test request preparation includes dependencies."""
        stub = LoadBalancerSlsStub(test_lb_resource)

        def test_func():
            return "result"

        dependencies = ["requests", "numpy"]
        system_deps = ["git"]

        request = await stub._prepare_request(
            test_func, dependencies, system_deps, True
        )

        assert request["dependencies"] == dependencies
        assert request["system_dependencies"] == system_deps


class TestLoadBalancerSlsStubHandleResponse:
    """Test suite for _handle_response method."""

    def test_handle_response_success(self):
        """Test successful response handling."""
        stub = LoadBalancerSlsStub(test_lb_resource)

        result_value = {"status": "ok", "value": 42}
        result_b64 = base64.b64encode(cloudpickle.dumps(result_value)).decode("utf-8")

        response = {"success": True, "result": result_b64}

        result = stub._handle_response(response)

        assert result == result_value

    def test_handle_response_error(self):
        """Test error response handling."""
        stub = LoadBalancerSlsStub(test_lb_resource)

        response = {"success": False, "error": "Function execution failed"}

        with pytest.raises(Exception, match="Remote execution failed"):
            stub._handle_response(response)

    def test_handle_response_invalid_type(self):
        """Test handling of invalid response type."""
        stub = LoadBalancerSlsStub(test_lb_resource)

        with pytest.raises(ValueError, match="Invalid response type"):
            stub._handle_response("not a dict")

    def test_handle_response_missing_result(self):
        """Test handling of success response without result."""
        stub = LoadBalancerSlsStub(test_lb_resource)

        response = {"success": True, "result": None}

        with pytest.raises(
            ValueError, match="Response marked success but result is None"
        ):
            stub._handle_response(response)

    def test_handle_response_invalid_base64(self):
        """Test handling of invalid base64 in result."""
        stub = LoadBalancerSlsStub(test_lb_resource)

        response = {"success": True, "result": "not_valid_base64!!!"}

        with pytest.raises(ValueError, match="Failed to deserialize result"):
            stub._handle_response(response)


class TestLoadBalancerSlsStubExecuteFunction:
    """Test suite for _execute_function method."""

    @pytest.mark.asyncio
    async def test_execute_function_no_endpoint_url(self):
        """Test error when endpoint_url is not available."""
        mock_resource = MagicMock()
        mock_resource.endpoint_url = None
        stub = LoadBalancerSlsStub(mock_resource)

        request = {
            "function_name": "test_func",
            "function_code": "def test_func(): pass",
        }

        with pytest.raises(ValueError, match="Endpoint URL not available"):
            await stub._execute_function(request)

    @pytest.mark.asyncio
    async def test_execute_function_timeout(self):
        """Test timeout error handling."""
        mock_resource = MagicMock()
        mock_resource.endpoint_url = "http://localhost:8000"
        stub = LoadBalancerSlsStub(mock_resource)

        request = {
            "function_name": "test_func",
            "function_code": "def test_func(): pass",
        }

        import httpx

        with patch(
            "runpod_flash.stubs.load_balancer_sls.httpx.AsyncClient"
        ) as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=httpx.TimeoutException("Timeout")
            )

            with pytest.raises(TimeoutError, match="Execution timeout"):
                await stub._execute_function(request)

    @pytest.mark.asyncio
    async def test_execute_function_http_error(self):
        """Test HTTP error handling."""
        mock_resource = MagicMock()
        mock_resource.endpoint_url = "http://localhost:8000"
        mock_resource.name = "test-lb"
        stub = LoadBalancerSlsStub(mock_resource)

        request = {
            "function_name": "test_func",
            "function_code": "def test_func(): pass",
        }

        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal server error"

        with patch(
            "runpod_flash.stubs.load_balancer_sls.httpx.AsyncClient"
        ) as mock_client:
            error = httpx.HTTPStatusError(
                "Error", request=MagicMock(), response=mock_response
            )
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=error
            )

            with pytest.raises(RuntimeError, match="HTTP error from endpoint"):
                await stub._execute_function(request)


class TestLoadBalancerSlsStubCall:
    """Test suite for __call__ method."""

    @pytest.mark.asyncio
    async def test_call_success(self):
        """Test successful stub execution."""
        mock_resource = MagicMock()
        stub = LoadBalancerSlsStub(mock_resource)

        def add(x, y):
            return x + y

        with patch.object(stub, "_execute_function") as mock_execute:
            result_b64 = base64.b64encode(cloudpickle.dumps(8)).decode("utf-8")
            mock_execute.return_value = {"success": True, "result": result_b64}

            result = await stub(add, None, None, True, 5, 3)

            assert result == 8
            mock_execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_with_dependencies(self):
        """Test stub execution with dependencies."""
        mock_resource = MagicMock()
        stub = LoadBalancerSlsStub(mock_resource)

        def use_requests():
            return "success"

        deps = ["requests"]

        with patch.object(stub, "_execute_function") as mock_execute:
            result_b64 = base64.b64encode(cloudpickle.dumps("success")).decode("utf-8")
            mock_execute.return_value = {"success": True, "result": result_b64}

            result = await stub(use_requests, deps, None, True)

            assert result == "success"
            # Verify dependencies were included in request
            call_args = mock_execute.call_args
            request = call_args[0][0]
            assert request["dependencies"] == deps


@pytest.mark.serial
class TestLoadBalancerSlsStubRouting:
    """Test suite for routing detection between /execute and user routes."""

    def test_should_use_execute_for_live_load_balancer(self):
        """Test that LiveLoadBalancer always uses /execute endpoint."""
        from runpod_flash import LiveLoadBalancer
        from runpod_flash import remote

        lb = LiveLoadBalancer(name="test-live")
        stub = LoadBalancerSlsStub(lb)

        @remote(lb, method="POST", path="/api/test")
        def test_func():
            pass

        assert stub._should_use_execute_endpoint(test_func) is True

    def test_should_use_user_route_for_deployed_lb(self):
        """Test that deployed LoadBalancerSlsResource uses user-defined route."""
        from runpod_flash import remote

        lb = LoadBalancerSlsResource(name="test-deployed", imageName="test:latest")
        stub = LoadBalancerSlsStub(lb)

        @remote(lb, method="POST", path="/api/test")
        def test_func():
            pass

        assert stub._should_use_execute_endpoint(test_func) is False

    def test_should_fallback_to_execute_without_routing_metadata(self):
        """Test fallback to /execute when routing metadata is missing."""
        lb = LoadBalancerSlsResource(name="test", imageName="test:latest")
        stub = LoadBalancerSlsStub(lb)

        def func_without_metadata():
            pass

        assert stub._should_use_execute_endpoint(func_without_metadata) is True

    def test_should_fallback_to_execute_with_incomplete_metadata(self):
        """Test fallback to /execute when routing metadata is incomplete."""
        lb = LoadBalancerSlsResource(name="test", imageName="test:latest")
        stub = LoadBalancerSlsStub(lb)

        def func_with_incomplete_metadata():
            pass

        # Attach incomplete metadata
        func_with_incomplete_metadata.__remote_config__ = {"method": "POST"}

        assert stub._should_use_execute_endpoint(func_with_incomplete_metadata) is True

    @pytest.mark.asyncio
    async def test_execute_via_user_route_success(self):
        """Test successful execution via user-defined route."""
        mock_resource = MagicMock()
        mock_resource.endpoint_url = "http://localhost:8000"
        mock_resource.name = "test-lb"
        stub = LoadBalancerSlsStub(mock_resource)

        def add(x, y):
            return x + y

        mock_response = MagicMock()
        mock_response.json.return_value = {"result": 8}

        with patch(
            "runpod_flash.stubs.load_balancer_sls.httpx.AsyncClient"
        ) as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )

            result = await stub._execute_via_user_route(add, "POST", "/api/add", 5, 3)

            assert result == {"result": 8}
            # Verify correct HTTP method and URL
            mock_client.return_value.__aenter__.return_value.request.assert_called_once()
            call_args = (
                mock_client.return_value.__aenter__.return_value.request.call_args
            )
            assert call_args[0][0] == "POST"
            assert call_args[0][1] == "http://localhost:8000/api/add"
            # Verify correct JSON body with mapped parameters
            assert call_args[1]["json"] == {"x": 5, "y": 3}

    @pytest.mark.asyncio
    async def test_execute_via_user_route_with_kwargs(self):
        """Test user route execution with keyword arguments."""
        mock_resource = MagicMock()
        mock_resource.endpoint_url = "http://localhost:8000"
        mock_resource.name = "test-lb"
        stub = LoadBalancerSlsStub(mock_resource)

        def greet(name, greeting="Hello"):
            return f"{greeting}, {name}!"

        mock_response = MagicMock()
        mock_response.json.return_value = "Hi, Alice!"

        with patch(
            "runpod_flash.stubs.load_balancer_sls.httpx.AsyncClient"
        ) as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )

            result = await stub._execute_via_user_route(
                greet, "POST", "/api/greet", "Alice", greeting="Hi"
            )

            assert result == "Hi, Alice!"
            # Verify JSON body has both positional arg and kwargs
            call_args = (
                mock_client.return_value.__aenter__.return_value.request.call_args
            )
            assert call_args[1]["json"] == {"name": "Alice", "greeting": "Hi"}

    @pytest.mark.asyncio
    async def test_call_routes_to_user_path_for_deployed_endpoint(self):
        """Test that __call__ routes to user path for deployed endpoints."""
        mock_resource = MagicMock()
        mock_resource.endpoint_url = "http://localhost:8000"
        mock_resource.name = "test-lb"
        stub = LoadBalancerSlsStub(mock_resource)

        @patch.object(stub, "_should_use_execute_endpoint")
        @patch.object(stub, "_execute_via_user_route")
        async def run_test(mock_user_route, mock_detect):
            mock_detect.return_value = False
            mock_user_route.return_value = {"result": 42}

            def test_func(x):
                return x

            test_func.__remote_config__ = {
                "method": "POST",
                "path": "/api/test",
                "resource_config": mock_resource,
            }

            result = await stub(test_func, None, None, True, 42)

            # Should route to _execute_via_user_route, not _execute_function
            mock_user_route.assert_called_once()
            assert result == {"result": 42}

        await run_test()

    @pytest.mark.asyncio
    async def test_call_routes_to_execute_for_live_endpoint(self):
        """Test that __call__ routes to /execute for LiveLoadBalancer."""
        mock_resource = MagicMock()
        stub = LoadBalancerSlsStub(mock_resource)

        @patch.object(stub, "_should_use_execute_endpoint")
        @patch.object(stub, "_execute_function")
        @patch.object(stub, "_handle_response")
        async def run_test(mock_handle, mock_execute, mock_detect):
            mock_detect.return_value = True
            mock_execute.return_value = {"success": True, "result": "test"}
            mock_handle.return_value = "handled"

            def test_func():
                pass

            result = await stub(test_func, None, None, True)

            # Should route to _execute_function, not _execute_via_user_route
            mock_execute.assert_called_once()
            assert result == "handled"

        await run_test()
