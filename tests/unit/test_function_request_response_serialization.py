"""Tests for JSON serialization format support in FunctionRequest/Response.

Validates that the proto models support both cloudpickle (default) and JSON
serialization formats, maintaining backward compatibility with existing callers.
"""

from runpod_flash.protos.remote_execution import FunctionRequest, FunctionResponse


class TestFunctionRequestSerializationFormat:
    """Tests for serialization_format field on FunctionRequest."""

    def test_function_request_defaults_to_cloudpickle(self):
        """Default serialization_format is 'cloudpickle' for backward compat."""
        request = FunctionRequest(
            function_name="my_func",
            execution_type="function",
        )
        assert request.serialization_format == "cloudpickle"

    def test_function_request_supports_json_serialization_format(self):
        """Request can be created with serialization_format='json' and plain JSON args."""
        request = FunctionRequest(
            function_name="my_func",
            execution_type="function",
            serialization_format="json",
            args=[{"key": "value"}, 42],
            kwargs={"param": [1, 2, 3]},
        )
        assert request.serialization_format == "json"
        assert request.args == [{"key": "value"}, 42]
        assert request.kwargs == {"param": [1, 2, 3]}

    def test_function_request_json_args_accept_any_type(self):
        """Args can contain dicts, ints, strings, lists, floats, None, bools."""
        mixed_args = [
            {"nested": {"deep": True}},
            42,
            "plain string",
            [1, 2, 3],
            3.14,
            None,
            True,
        ]
        request = FunctionRequest(
            function_name="my_func",
            execution_type="function",
            serialization_format="json",
            args=mixed_args,
            kwargs={
                "dict_param": {"a": 1},
                "int_param": 99,
                "list_param": [4, 5, 6],
            },
        )
        assert request.args == mixed_args
        assert request.kwargs["dict_param"] == {"a": 1}
        assert request.kwargs["int_param"] == 99
        assert request.kwargs["list_param"] == [4, 5, 6]

    def test_backward_compat_string_args(self):
        """Existing base64-encoded cloudpickle string args still work.

        List[str] is a subtype of List[Any], so existing callers that pass
        strings continue to function without changes.
        """
        b64_encoded_args = ["c29tZV9iYXNlNjRfZGF0YQ==", "bW9yZV9kYXRh"]
        b64_encoded_kwargs = {"x": "c29tZV9iYXNlNjRfZGF0YQ=="}

        request = FunctionRequest(
            function_name="my_func",
            execution_type="function",
            args=b64_encoded_args,
            kwargs=b64_encoded_kwargs,
        )
        # Default format is cloudpickle
        assert request.serialization_format == "cloudpickle"
        # String args are preserved as-is
        assert request.args == b64_encoded_args
        assert request.kwargs == b64_encoded_kwargs

    def test_constructor_args_accept_any_type(self):
        """Constructor args/kwargs also accept Any types for class execution."""
        request = FunctionRequest(
            class_name="MyClass",
            execution_type="class",
            serialization_format="json",
            constructor_args=[1, "two", {"three": 3}],
            constructor_kwargs={"config": {"batch_size": 32}},
        )
        assert request.constructor_args == [1, "two", {"three": 3}]
        assert request.constructor_kwargs == {"config": {"batch_size": 32}}

    def test_constructor_args_backward_compat_strings(self):
        """Constructor args still work with old-style string values."""
        request = FunctionRequest(
            class_name="MyClass",
            execution_type="class",
            constructor_args=["b64_string_1", "b64_string_2"],
            constructor_kwargs={"param": "b64_encoded_value"},
        )
        assert request.serialization_format == "cloudpickle"
        assert request.constructor_args == ["b64_string_1", "b64_string_2"]
        assert request.constructor_kwargs == {"param": "b64_encoded_value"}


class TestFunctionResponseJsonResult:
    """Tests for json_result field on FunctionResponse."""

    def test_function_response_json_result(self):
        """FunctionResponse can carry a json_result for JSON-serialized responses."""
        response = FunctionResponse(
            success=True,
            json_result={"prediction": 0.95, "label": "cat"},
        )
        assert response.success is True
        assert response.json_result == {"prediction": 0.95, "label": "cat"}
        assert response.result is None

    def test_function_response_json_result_defaults_to_none(self):
        """json_result is None by default, preserving backward compat."""
        response = FunctionResponse(success=True, result="b64_cloudpickle_data")
        assert response.json_result is None
        assert response.result == "b64_cloudpickle_data"

    def test_function_response_json_result_various_types(self):
        """json_result accepts any JSON-serializable value."""
        # List result
        response_list = FunctionResponse(success=True, json_result=[1, 2, 3])
        assert response_list.json_result == [1, 2, 3]

        # Scalar result
        response_int = FunctionResponse(success=True, json_result=42)
        assert response_int.json_result == 42

        # String result
        response_str = FunctionResponse(success=True, json_result="hello")
        assert response_str.json_result == "hello"

        # Nested dict result
        response_nested = FunctionResponse(
            success=True,
            json_result={"items": [{"id": 1}, {"id": 2}]},
        )
        assert response_nested.json_result == {"items": [{"id": 1}, {"id": 2}]}

    def test_function_response_backward_compat_cloudpickle_result(self):
        """Existing cloudpickle result field continues to work."""
        response = FunctionResponse(
            success=True,
            result="base64_cloudpickle_encoded_result",
        )
        assert response.result == "base64_cloudpickle_encoded_result"
        assert response.json_result is None
