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

    def test_empty_input(self):
        """Handler passes empty kwargs when input is empty."""

        def no_args():
            return "ok"

        handler = create_deployed_handler(no_args)
        result = handler({"input": {}})

        assert result == "ok"

    def test_missing_input_key(self):
        """Handler defaults to empty dict when 'input' key missing."""

        def no_args():
            return "ok"

        handler = create_deployed_handler(no_args)
        result = handler({})

        assert result == "ok"

    def test_function_raises_returns_error_dict(self):
        """Handler catches exceptions and returns error dict."""

        def failing():
            raise ValueError("something broke")

        handler = create_deployed_handler(failing)
        result = handler({"input": {}})

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

        def complex_result():
            return {"items": [1, 2, 3], "nested": {"key": "value"}}

        handler = create_deployed_handler(complex_result)
        result = handler({"input": {}})

        assert result == {"items": [1, 2, 3], "nested": {"key": "value"}}

    def test_none_return_value(self):
        """Handler returns None when function returns None."""

        def returns_none():
            return None

        handler = create_deployed_handler(returns_none)
        result = handler({"input": {}})

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

        async def async_fail():
            raise RuntimeError("async error")

        handler = create_deployed_handler(async_fail)
        result = handler({"input": {}})

        assert isinstance(result, dict)
        assert "async error" in result["error"]
        assert "traceback" in result
