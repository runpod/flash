"""Integration tests for the generic handler execution pipeline.

Exercises the full flow: serialize args client-side → handler deserializes →
executes function → serializes result → verify output.
"""

from runpod_flash.runtime.generic_handler import (
    create_deployed_handler,
    create_handler,
)
from runpod_flash.runtime.serialization import (
    deserialize_arg,
    serialize_args,
    serialize_kwargs,
)


def _make_job(function_name, args=(), kwargs=None, execution_type="function", **extra):
    """Build a RunPod-style job input dict with serialized args."""
    job_input = {
        "function_name": function_name,
        "execution_type": execution_type,
        "args": serialize_args(args),
        "kwargs": serialize_kwargs(kwargs or {}),
        **extra,
    }
    return {"id": "test-job-001", "input": job_input}


class TestFunctionExecutionRoundtrip:
    """Handler receives serialized args, executes, returns serialized result."""

    def test_function_execution_roundtrip(self):
        """Simple function: serialize → handler → deserialize result."""

        def add(a, b):
            return a + b

        handler = create_handler({"add": add})
        job = _make_job("add", args=(3, 7))
        result = handler(job)

        assert result["success"] is True
        assert deserialize_arg(result["result"]) == 10

    def test_function_with_kwargs(self):
        """Function with keyword arguments through handler."""

        def greet(name, greeting="Hello"):
            return f"{greeting}, {name}!"

        handler = create_handler({"greet": greet})
        job = _make_job("greet", kwargs={"name": "World", "greeting": "Hi"})
        result = handler(job)

        assert result["success"] is True
        assert deserialize_arg(result["result"]) == "Hi, World!"

    def test_complex_return_types(self):
        """Handler correctly serializes complex return values."""

        def compute():
            return {"numbers": [1, 2, 3], "nested": {"ok": True}}

        handler = create_handler({"compute": compute})
        job = _make_job("compute")
        result = handler(job)

        assert result["success"] is True
        restored = deserialize_arg(result["result"])
        assert restored == {"numbers": [1, 2, 3], "nested": {"ok": True}}


class TestClassMethodExecutionRoundtrip:
    """Handler executes class constructor + method call."""

    def test_class_method_execution_roundtrip(self):
        """Class instantiation + method call through handler."""

        class Calculator:
            def __init__(self, base):
                self.base = base

            def add(self, x):
                return self.base + x

        handler = create_handler({"Calculator": Calculator})

        job_input = {
            "function_name": "Calculator",
            "execution_type": "class",
            "args": serialize_args((10,)),
            "kwargs": serialize_kwargs({}),
            "method_name": "add",
            "method_args": serialize_args((5,)),
            "method_kwargs": serialize_kwargs({}),
        }
        job = {"id": "test-job-002", "input": job_input}
        result = handler(job)

        assert result["success"] is True
        assert deserialize_arg(result["result"]) == 15


class TestHandlerErrorPropagation:
    """Handler returns structured errors for function failures."""

    def test_handler_error_propagation(self):
        """Function that raises → handler returns error dict."""

        def fail():
            raise ValueError("intentional failure")

        handler = create_handler({"fail": fail})
        job = _make_job("fail")
        result = handler(job)

        assert result["success"] is False
        assert "intentional failure" in result["error"]
        assert "traceback" in result

    def test_missing_function_error(self):
        """Request for unregistered function → error dict."""
        handler = create_handler({"exists": lambda: 1})
        job = _make_job("does_not_exist")
        result = handler(job)

        assert result["success"] is False
        assert (
            "not found" in result["error"].lower()
            or "does_not_exist" in result["error"]
        )


class TestAsyncFunctionExecution:
    """Async functions are executed correctly through the deployed handler."""

    def test_async_function_execution(self):
        """Async function through create_deployed_handler (plain JSON kwargs)."""

        async def async_add(a, b):
            return a + b

        handler = create_deployed_handler(async_add)
        job = {"id": "test-job-async", "input": {"a": 10, "b": 20}}
        result = handler(job)

        assert result == 30


class TestDeployedHandler:
    """create_deployed_handler for single-function QB endpoints."""

    def test_deployed_handler_plain_kwargs(self):
        """Deployed handler receives plain JSON kwargs (no cloudpickle)."""

        def process(data, multiplier=1):
            return sum(data) * multiplier

        handler = create_deployed_handler(process)
        job = {"id": "test-job-003", "input": {"data": [1, 2, 3], "multiplier": 2}}
        result = handler(job)

        assert result == 12

    def test_deployed_handler_async_function(self):
        """Deployed handler handles async functions."""

        async def async_process(value):
            return value * 2

        handler = create_deployed_handler(async_process)
        job = {"id": "test-job-004", "input": {"value": 21}}
        result = handler(job)

        assert result == 42

    def test_deployed_handler_error(self):
        """Deployed handler returns error dict on failure."""

        def bad_func(x):
            raise RuntimeError("boom")

        handler = create_deployed_handler(bad_func)
        job = {"id": "test-job-005", "input": {"x": 1}}
        result = handler(job)

        assert isinstance(result, dict)
        assert "error" in result
        assert "boom" in result["error"]
