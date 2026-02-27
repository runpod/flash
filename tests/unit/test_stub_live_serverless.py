"""Tests for stubs/live_serverless.py - LiveServerlessStub."""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import cloudpickle
import pytest

from runpod_flash.protos.remote_execution import FunctionResponse
from runpod_flash.stubs.live_serverless import (
    LiveServerlessStub,
    _SERIALIZED_FUNCTION_CACHE,
    get_function_source,
)


@pytest.fixture(autouse=True)
def clear_function_cache():
    """Clear the function cache between tests."""
    _SERIALIZED_FUNCTION_CACHE.clear()
    yield
    _SERIALIZED_FUNCTION_CACHE.clear()


class TestGetFunctionSource:
    """Test get_function_source extraction."""

    def test_extracts_simple_function(self):
        def simple_func(x, y):
            return x + y

        source, src_hash = get_function_source(simple_func)
        assert "def simple_func(x, y):" in source
        assert "return x + y" in source
        assert isinstance(src_hash, str)
        assert len(src_hash) == 64  # SHA256 hex digest

    def test_extracts_async_function(self):
        async def async_func(data):
            return data

        source, src_hash = get_function_source(async_func)
        assert "async def async_func(data):" in source

    def test_deterministic_hash(self):
        def stable_func():
            return 42

        _, hash1 = get_function_source(stable_func)
        _, hash2 = get_function_source(stable_func)
        assert hash1 == hash2

    def test_different_functions_different_hashes(self):
        def func_a():
            return 1

        def func_b():
            return 2

        _, hash_a = get_function_source(func_a)
        _, hash_b = get_function_source(func_b)
        assert hash_a != hash_b

    def test_unwraps_decorated_functions(self):
        """Should unwrap decorators to get the original function."""
        import functools

        def my_decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            return wrapper

        @my_decorator
        def decorated_func(x):
            return x * 2

        source, _ = get_function_source(decorated_func)
        assert "def decorated_func(x):" in source


class TestLiveServerlessStub:
    """Test LiveServerlessStub methods."""

    @pytest.fixture
    def mock_server(self):
        server = MagicMock()
        server.run = AsyncMock()
        server.runsync = AsyncMock()
        return server

    @pytest.fixture
    def stub(self, mock_server):
        return LiveServerlessStub(mock_server)

    @pytest.mark.asyncio
    async def test_prepare_request_basic(self, stub):
        """prepare_request creates a FunctionRequest with serialized args."""

        def sample_func(x):
            return x + 1

        with patch(
            "runpod_flash.stubs.dependency_resolver.resolve_dependencies",
            new_callable=AsyncMock,
            return_value=[],
        ):
            request = await stub.prepare_request(
                sample_func, ["numpy"], ["git"], True, 42
            )

        assert request.function_name == "sample_func"
        assert request.dependencies == ["numpy"]
        assert request.system_dependencies == ["git"]
        assert request.accelerate_downloads is True
        assert request.function_code is not None
        assert len(request.args) == 1

    @pytest.mark.asyncio
    async def test_prepare_request_caches_function(self, stub):
        """Second call with same function uses cache."""

        def cached_func(x):
            return x

        with patch(
            "runpod_flash.stubs.dependency_resolver.resolve_dependencies",
            new_callable=AsyncMock,
            return_value=[],
        ):
            req1 = await stub.prepare_request(cached_func, [], [], True, 1)
            req2 = await stub.prepare_request(cached_func, [], [], True, 2)

        assert req1.function_code == req2.function_code
        # Only one entry in cache
        assert len(_SERIALIZED_FUNCTION_CACHE) == 1

    @pytest.mark.asyncio
    async def test_prepare_request_with_kwargs(self, stub):
        """prepare_request handles kwargs."""

        def func_with_kwargs(x, y=10):
            return x + y

        with patch(
            "runpod_flash.stubs.dependency_resolver.resolve_dependencies",
            new_callable=AsyncMock,
            return_value=[],
        ):
            request = await stub.prepare_request(
                func_with_kwargs, [], [], True, 5, y=20
            )

        assert len(request.args) == 1
        assert "y" in request.kwargs

    def test_handle_response_success(self, stub):
        """handle_response returns deserialized result on success."""
        result_data = {"key": "value"}
        encoded = base64.b64encode(cloudpickle.dumps(result_data)).decode()
        response = FunctionResponse(success=True, result=encoded)

        result = stub.handle_response(response)
        assert result == {"key": "value"}

    def test_handle_response_error(self, stub):
        """handle_response raises on error."""
        response = FunctionResponse(success=False, error="Something failed")

        with pytest.raises(Exception, match="Remote execution failed"):
            stub.handle_response(response)

    def test_handle_response_invalid(self, stub):
        """handle_response raises ValueError for invalid response."""
        response = FunctionResponse(success=False, error=None)

        with pytest.raises(ValueError, match="Invalid response"):
            stub.handle_response(response)

    def test_handle_response_none_result(self, stub):
        """handle_response raises ValueError when success but result is None."""
        response = FunctionResponse(success=True, result=None)

        with pytest.raises(ValueError, match="result is None"):
            stub.handle_response(response)

    def test_handle_response_prints_stdout(self, stub, capsys):
        """handle_response prints stdout lines."""
        encoded = base64.b64encode(cloudpickle.dumps(42)).decode()
        response = FunctionResponse(
            success=True, result=encoded, stdout="Line 1\nLine 2"
        )

        stub.handle_response(response)
        captured = capsys.readouterr()
        assert "Line 1" in captured.out
        assert "Line 2" in captured.out

    @pytest.mark.asyncio
    async def test_execute_function_success(self, stub, mock_server):
        """ExecuteFunction sends payload and returns FunctionResponse."""
        mock_output = {"success": True, "result": "encoded_result"}
        job_output = MagicMock(error=None, output=mock_output)
        mock_server.run.return_value = job_output

        from runpod_flash.protos.remote_execution import FunctionRequest

        request = FunctionRequest(
            function_name="test",
            function_code="def test(): return 1",
        )
        response = await stub.ExecuteFunction(request)
        assert response.success is True

    @pytest.mark.asyncio
    async def test_execute_function_job_error(self, stub, mock_server):
        """ExecuteFunction handles job errors."""
        job_output = MagicMock(error="Job failed", output={"stdout": "some output"})
        mock_server.run.return_value = job_output

        from runpod_flash.protos.remote_execution import FunctionRequest

        request = FunctionRequest(
            function_name="test",
            function_code="def test(): return 1",
        )
        response = await stub.ExecuteFunction(request)
        assert response.success is False
        assert "Job failed" in response.error

    @pytest.mark.asyncio
    async def test_execute_function_exception(self, stub, mock_server):
        """ExecuteFunction returns error response on exception."""
        mock_server.run.side_effect = ConnectionError("Network error")

        from runpod_flash.protos.remote_execution import FunctionRequest

        request = FunctionRequest(
            function_name="test",
            function_code="def test(): return 1",
        )
        response = await stub.ExecuteFunction(request)
        assert response.success is False
        assert "Network error" in response.error

    @pytest.mark.asyncio
    async def test_execute_function_sync(self, stub, mock_server):
        """ExecuteFunction with sync=True calls runsync."""
        mock_output = {"success": True, "result": "encoded_result"}
        job_output = MagicMock(error=None, output=mock_output)
        mock_server.runsync.return_value = job_output

        from runpod_flash.protos.remote_execution import FunctionRequest

        request = FunctionRequest(
            function_name="test",
            function_code="def test(): return 1",
        )
        response = await stub.ExecuteFunction(request, sync=True)
        mock_server.runsync.assert_called_once()
        assert response.success is True
