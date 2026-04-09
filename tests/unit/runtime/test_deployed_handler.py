"""Tests for create_deployed_handler."""

from runpod_flash.runtime.generic_handler import create_deployed_handler


class TestCreateDeployedHandler:
    """Test deployed handler factory (plain JSON, single function)."""

    def test_sync_function_with_kwargs(self):
        """Handler passes plain JSON kwargs to sync function."""

        def add(x, y):
            return x + y

        handler = create_deployed_handler(add)
        result = handler({"input": {"x": 1, "y": 2}})

        assert result == 3

    def test_async_function_with_kwargs(self):
        """Handler awaits async function and returns result."""

        async def async_add(x, y):
            return x + y

        handler = create_deployed_handler(async_add)
        result = handler({"input": {"x": 10, "y": 20}})

        assert result == 30

    def test_empty_input_rejected(self):
        """Empty input is rejected even for zero-arg functions (platform behavior)."""

        def no_args():
            return "ok"

        handler = create_deployed_handler(no_args)
        result = handler({"input": {}})

        assert result["success"] is False
        assert "Empty or null input" in result["error"]

    def test_missing_input_key_rejected(self):
        """Missing input key is rejected even for zero-arg functions."""

        def no_args():
            return "ok"

        handler = create_deployed_handler(no_args)
        result = handler({})

        assert result["success"] is False
        assert "Empty or null input" in result["error"]

    def test_function_raises_returns_error_dict(self):
        """Handler catches exceptions and returns error dict."""

        def failing(x: int):
            raise ValueError("something broke")

        handler = create_deployed_handler(failing)
        result = handler({"input": {"x": 1}})

        assert isinstance(result, dict)
        assert "error" in result
        assert "something broke" in result["error"]
        assert "traceback" in result

    def test_missing_kwargs_returns_error(self):
        """Handler returns error when required kwargs are missing."""

        def requires_args(x, y):
            return x + y

        handler = create_deployed_handler(requires_args)
        result = handler({"input": {"x": 1}})

        assert isinstance(result, dict)
        assert "error" in result

    def test_complex_return_value(self):
        """Handler returns complex JSON-serializable types."""

        def complex_result(flag: bool):
            return {"items": [1, 2, 3], "nested": {"key": "value"}}

        handler = create_deployed_handler(complex_result)
        result = handler({"input": {"flag": True}})

        assert result == {"items": [1, 2, 3], "nested": {"key": "value"}}

    def test_none_return_value(self):
        """Handler returns None when function returns None."""

        def returns_none(flag: bool):
            return None

        handler = create_deployed_handler(returns_none)
        result = handler({"input": {"flag": True}})

        assert result is None

    def test_kwargs_passthrough(self):
        """Handler passes all input keys as kwargs."""

        def echo(**kwargs):
            return kwargs

        handler = create_deployed_handler(echo)
        result = handler({"input": {"a": 1, "b": "two", "c": [3]}})

        assert result == {"a": 1, "b": "two", "c": [3]}

    def test_async_function_raising(self):
        """Handler catches async exceptions and returns error dict."""

        async def async_fail(x: int):
            raise RuntimeError("async error")

        handler = create_deployed_handler(async_fail)
        result = handler({"input": {"x": 1}})

        assert isinstance(result, dict)
        assert "async error" in result["error"]
        assert "traceback" in result
