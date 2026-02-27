"""Tests for stubs/serverless.py - ServerlessEndpointStub."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from runpod_flash.stubs.serverless import ServerlessEndpointStub


@pytest.fixture
def mock_server():
    server = MagicMock()
    server.run = AsyncMock()
    server.runsync = AsyncMock()
    return server


@pytest.fixture
def stub(mock_server):
    return ServerlessEndpointStub(mock_server)


class TestPreparePayload:
    """Test prepare_payload method."""

    def test_calls_function_with_args(self, stub):
        """prepare_payload calls the function and returns its result."""

        def my_func(x, y):
            return {"sum": x + y}

        result = stub.prepare_payload(my_func, 3, 5)
        assert result == {"sum": 8}

    def test_calls_function_with_kwargs(self, stub):
        """prepare_payload passes kwargs through."""

        def my_func(name="default"):
            return {"name": name}

        result = stub.prepare_payload(my_func, name="test")
        assert result == {"name": "test"}

    def test_calls_function_no_args(self, stub):
        """prepare_payload works with no-arg functions."""

        def my_func():
            return {"status": "ok"}

        result = stub.prepare_payload(my_func)
        assert result == {"status": "ok"}


class TestExecute:
    """Test execute method."""

    @pytest.mark.asyncio
    async def test_execute_async_calls_run(self, stub, mock_server):
        """execute with sync=False calls server.run()."""
        mock_server.run.return_value = MagicMock(output="result")

        await stub.execute({"data": "test"}, sync=False)
        mock_server.run.assert_called_once_with({"data": "test"})
        mock_server.runsync.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_sync_calls_runsync(self, stub, mock_server):
        """execute with sync=True calls server.runsync()."""
        mock_server.runsync.return_value = MagicMock(output="result")

        await stub.execute({"data": "test"}, sync=True)
        mock_server.runsync.assert_called_once_with({"data": "test"})
        mock_server.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_default_is_async(self, stub, mock_server):
        """Default sync=False means run() is called."""
        mock_server.run.return_value = MagicMock(output="result")

        await stub.execute({"data": "test"})
        mock_server.run.assert_called_once()


class TestHandleResponse:
    """Test handle_response method."""

    def test_returns_output_when_set(self, stub):
        """Returns output when response has output."""
        response = MagicMock(output={"result": 42}, error=None)
        assert stub.handle_response(response) == {"result": 42}

    def test_raises_on_error(self, stub):
        """Raises Exception when response has error."""
        response = MagicMock(output=None, error="Something went wrong")
        with pytest.raises(Exception, match="Remote execution failed"):
            stub.handle_response(response)

    def test_raises_value_error_on_invalid(self, stub):
        """Raises ValueError when neither output nor error is set."""
        response = MagicMock(output=None, error=None)
        with pytest.raises(ValueError, match="Invalid response"):
            stub.handle_response(response)

    def test_output_takes_priority_over_error(self, stub):
        """When both output and error exist, output is returned."""
        response = MagicMock(output={"data": "ok"}, error="some error")
        assert stub.handle_response(response) == {"data": "ok"}
