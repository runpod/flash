"""Extended tests for runtime/generic_handler.py - uncovered paths."""

import json
from unittest.mock import patch


from runpod_flash.runtime.generic_handler import (
    create_deployed_handler,
    create_handler,
    execute_function,
    load_manifest,
)


class TestLoadManifest:
    """Test load_manifest with various scenarios."""

    def test_loads_from_explicit_path(self, tmp_path):
        manifest = {"resources": {"gpu": {}}, "function_registry": {"func1": "gpu"}}
        manifest_path = tmp_path / "flash_manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        result = load_manifest(manifest_path)
        assert result["resources"] == {"gpu": {}}

    def test_returns_default_on_missing_explicit_path(self, tmp_path):
        result = load_manifest(tmp_path / "nonexistent.json")
        assert result == {"resources": {}, "function_registry": {}}

    def test_returns_default_on_invalid_json(self, tmp_path):
        bad_path = tmp_path / "flash_manifest.json"
        bad_path.write_text("not valid json{{{")

        result = load_manifest(bad_path)
        assert result == {"resources": {}, "function_registry": {}}

    def test_fallback_search_cwd(self, tmp_path):
        """Searches cwd for manifest when no explicit path given."""
        manifest = {"resources": {}, "function_registry": {"f": "r"}}
        (tmp_path / "flash_manifest.json").write_text(json.dumps(manifest))

        with patch(
            "runpod_flash.runtime.generic_handler.Path.cwd", return_value=tmp_path
        ):
            result = load_manifest()
            assert result["function_registry"] == {"f": "r"}

    def test_returns_empty_when_not_found_anywhere(self, tmp_path):
        with patch(
            "runpod_flash.runtime.generic_handler.Path.cwd", return_value=tmp_path
        ):
            result = load_manifest()
            assert result == {"resources": {}, "function_registry": {}}


class TestExecuteFunction:
    """Test execute_function for both function and class execution types."""

    def test_function_execution(self):
        def add(x, y):
            return x + y

        result = execute_function(add, [3, 5], {}, "function", {})
        assert result == 8

    def test_function_with_kwargs(self):
        def greet(name="World"):
            return f"Hello, {name}!"

        result = execute_function(greet, [], {"name": "Flash"}, "function", {})
        assert result == "Hello, Flash!"

    def test_class_execution(self):
        class Calculator:
            def __init__(self, base):
                self.base = base

            def add(self, x):
                return self.base + x

        job_input = {
            "method_name": "add",
            "method_args": [],
            "method_kwargs": {},
        }

        # Need to mock deserialize_arguments for method args
        with patch(
            "runpod_flash.runtime.generic_handler.deserialize_arguments",
            return_value=([5], {}),
        ):
            result = execute_function(Calculator, [10], {}, "class", job_input)
            assert result == 15

    def test_class_default_method_is_call(self):
        class Callable:
            def __init__(self):
                pass

            def __call__(self, x):
                return x * 2

        job_input = {"method_args": [], "method_kwargs": {}}

        with patch(
            "runpod_flash.runtime.generic_handler.deserialize_arguments",
            return_value=([7], {}),
        ):
            result = execute_function(Callable, [], {}, "class", job_input)
            assert result == 14


class TestCreateHandler:
    """Test create_handler factory."""

    def test_handler_executes_registered_function(self):
        def my_func(x):
            return x * 2

        handler = create_handler({"my_func": my_func})

        # Build a mock job with serialized args
        from runpod_flash.runtime.serialization import serialize_arg

        job = {
            "input": {
                "function_name": "my_func",
                "execution_type": "function",
                "args": [serialize_arg(5)],
                "kwargs": {},
            }
        }

        result = handler(job)
        assert result["success"] is True
        assert result["result"] is not None

    def test_handler_function_not_found(self):
        handler = create_handler({"existing": lambda: None})

        job = {"input": {"function_name": "nonexistent"}}
        result = handler(job)
        assert result["success"] is False
        assert "not found" in result["error"]
        assert "existing" in result["error"]

    def test_handler_exception(self):
        def failing_func():
            raise ValueError("intentional error")

        handler = create_handler({"failing_func": failing_func})

        job = {
            "input": {
                "function_name": "failing_func",
                "execution_type": "function",
                "args": [],
                "kwargs": {},
            }
        }

        result = handler(job)
        assert result["success"] is False
        assert "intentional error" in result["error"]
        assert result["traceback"] != ""

    def test_handler_empty_input(self):
        handler = create_handler({})
        result = handler({})
        assert result["success"] is False


class TestCreateDeployedHandler:
    """Test create_deployed_handler for single-function endpoints."""

    def test_sync_function(self):
        def process(x: int, y: int):
            return {"sum": x + y}

        handler = create_deployed_handler(process)
        result = handler({"input": {"x": 3, "y": 5}})
        assert result == {"sum": 8}

    def test_async_function(self):
        async def async_process(msg: str):
            return {"echo": msg}

        handler = create_deployed_handler(async_process)
        result = handler({"input": {"msg": "hello"}})
        assert result == {"echo": "hello"}

    def test_exception_returns_error_dict(self):
        def failing(x: int):
            raise ValueError("bad input")

        handler = create_deployed_handler(failing)
        result = handler({"input": {"x": 1}})
        assert "error" in result
        assert "bad input" in result["error"]
        assert "traceback" in result

    def test_empty_input(self):
        def no_args():
            return {"status": "ok"}

        handler = create_deployed_handler(no_args)
        result = handler({"input": {}})
        assert result == {"status": "ok"}

    def test_missing_input_key(self):
        def no_args():
            return {"status": "ok"}

        handler = create_deployed_handler(no_args)
        result = handler({})
        assert result == {"status": "ok"}
