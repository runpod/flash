"""Integration tests for the stub dispatch chain.

Exercises: resource → stub_resource() → stub.prepare_request → mock execute →
stub.handle_response, verifying the full client-side path.
"""

import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import cloudpickle
import pytest

from runpod_flash.core.resources import LiveServerless, ServerlessEndpoint, JobOutput
from runpod_flash.protos.remote_execution import FunctionResponse
from runpod_flash.stubs.registry import stub_resource


def _run(coro):
    """Run a coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestLiveServerlessStubDispatch:
    """LiveServerless → LiveServerlessStub → prepare → execute → handle."""

    def test_live_serverless_stub_prepare_and_handle(self):
        """Full prepare_request → mock ExecuteFunction → handle_response."""
        resource = LiveServerless(
            name="test-gpu",
            gpu_count=1,
            gpu_ids="AMPERE_48",
            workers_min=0,
            workers_max=1,
        )

        stub_fn = stub_resource(resource)
        assert callable(stub_fn)

        # Define a function to test with (must be inspectable with source)
        def multiply(a, b):
            return a * b

        # Build a successful response with serialized result
        expected_result = 42
        serialized_result = base64.b64encode(cloudpickle.dumps(expected_result)).decode(
            "utf-8"
        )
        mock_response = FunctionResponse(success=True, result=serialized_result)

        # Mock at the stub level — LiveServerlessStub.ExecuteFunction
        with patch(
            "runpod_flash.stubs.live_serverless.LiveServerlessStub.ExecuteFunction",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = _run(stub_fn(multiply, [], None, True, 6, 7))

        assert result == expected_result

    def test_live_serverless_stub_error_response(self):
        """Error response from server is raised as exception."""
        resource = LiveServerless(
            name="test-gpu-err",
            gpu_count=1,
            gpu_ids="AMPERE_48",
            workers_min=0,
            workers_max=1,
        )

        stub_fn = stub_resource(resource)

        def failing_func():
            pass

        mock_response = FunctionResponse(
            success=False, error="Remote crash", result=None
        )

        with (
            patch(
                "runpod_flash.stubs.live_serverless.LiveServerlessStub.ExecuteFunction",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
            pytest.raises(Exception, match="Remote execution failed"),
        ):
            _run(stub_fn(failing_func, [], None, True))


class TestServerlessEndpointStubDispatch:
    """ServerlessEndpoint → ServerlessEndpointStub → prepare → execute → handle."""

    def test_serverless_endpoint_stub_roundtrip(self):
        """Prepare payload → mock execute → handle response."""
        resource = ServerlessEndpoint(
            name="test-deployed",
            endpoint_id="ep-test-123",
            imageName="runpod/test:latest",
        )

        stub_fn = stub_resource(resource)
        assert callable(stub_fn)

        # For ServerlessEndpoint, the decorated function IS the payload builder
        def build_payload(data, multiplier=2):
            return {"data": data, "multiplier": multiplier}

        expected_output = {"result": 42}
        mock_job = JobOutput(
            id="mock-job",
            workerId="mock-worker",
            status="COMPLETED",
            delayTime=10,
            executionTime=100,
            output=expected_output,
        )

        with patch(
            "runpod_flash.stubs.serverless.ServerlessEndpointStub.execute",
            new_callable=AsyncMock,
            return_value=mock_job,
        ):
            result = _run(
                stub_fn(build_payload, None, None, True, [1, 2, 3], multiplier=5)
            )

        assert result == expected_output


class TestProductionWrapperInjection:
    """With RUNPOD_ENDPOINT_ID set, ProductionWrapper wraps the stub."""

    def test_production_wrapper_injection(self, monkeypatch):
        """Setting RUNPOD_ENDPOINT_ID causes ProductionWrapper to wrap the stub."""
        monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "ep-prod-123")

        resource = LiveServerless(
            name="test-prod",
            gpu_count=1,
            gpu_ids="AMPERE_48",
            workers_min=0,
            workers_max=1,
        )

        with patch(
            "runpod_flash.runtime.production_wrapper.create_production_wrapper"
        ) as mock_create:
            mock_wrapper = MagicMock()
            mock_wrapper.wrap_function_execution = AsyncMock(
                return_value="wrapped_result"
            )
            mock_wrapper.wrap_class_method_execution = AsyncMock(
                return_value="wrapped_class_result"
            )
            mock_create.return_value = mock_wrapper

            stub_fn = stub_resource(resource)

            def dummy_func():
                pass

            result = _run(stub_fn(dummy_func, [], None, True))

        assert result == "wrapped_result"
        mock_wrapper.wrap_function_execution.assert_awaited_once()
