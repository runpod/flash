"""Tests for generic_handler module."""

import base64

import cloudpickle

from runpod_flash.runtime.generic_handler import (
    create_deployed_handler,
    create_handler,
    deserialize_arguments,
    execute_function,
    serialize_result,
)


def test_serialize_result_simple_value():
    """Test serializing simple Python values."""
    result = serialize_result(42)
    deserialized = cloudpickle.loads(base64.b64decode(result))
    assert deserialized == 42


def test_serialize_result_dict():
    """Test serializing dict."""
    result = serialize_result({"key": "value", "number": 123})
    deserialized = cloudpickle.loads(base64.b64decode(result))
    assert deserialized == {"key": "value", "number": 123}


def test_serialize_result_list():
    """Test serializing list."""
    result = serialize_result([1, 2, 3, "four"])
    deserialized = cloudpickle.loads(base64.b64decode(result))
    assert deserialized == [1, 2, 3, "four"]


def test_deserialize_arguments_empty():
    """Test deserializing empty arguments."""
    job_input = {}
    args, kwargs = deserialize_arguments(job_input)
    assert args == []
    assert kwargs == {}


def test_deserialize_arguments_only_args():
    """Test deserializing only positional arguments."""
    arg1 = cloudpickle.dumps(42)
    arg2 = cloudpickle.dumps("hello")

    job_input = {
        "args": [
            base64.b64encode(arg1).decode("utf-8"),
            base64.b64encode(arg2).decode("utf-8"),
        ]
    }

    args, kwargs = deserialize_arguments(job_input)
    assert args == [42, "hello"]
    assert kwargs == {}


def test_deserialize_arguments_only_kwargs():
    """Test deserializing only keyword arguments."""
    val1 = cloudpickle.dumps(42)
    val2 = cloudpickle.dumps("hello")

    job_input = {
        "kwargs": {
            "x": base64.b64encode(val1).decode("utf-8"),
            "y": base64.b64encode(val2).decode("utf-8"),
        }
    }

    args, kwargs = deserialize_arguments(job_input)
    assert args == []
    assert kwargs == {"x": 42, "y": "hello"}


def test_deserialize_arguments_mixed():
    """Test deserializing both args and kwargs."""
    arg1 = cloudpickle.dumps(10)
    kwarg1 = cloudpickle.dumps(20)

    job_input = {
        "args": [base64.b64encode(arg1).decode("utf-8")],
        "kwargs": {"key": base64.b64encode(kwarg1).decode("utf-8")},
    }

    args, kwargs = deserialize_arguments(job_input)
    assert args == [10]
    assert kwargs == {"key": 20}


def test_execute_function_simple():
    """Test executing a simple function."""

    def add(a, b):
        return a + b

    result = execute_function(add, [1, 2], {}, "function", {})
    assert result == 3


def test_execute_function_with_kwargs():
    """Test executing function with keyword arguments."""

    def greet(name, greeting="Hello"):
        return f"{greeting}, {name}!"

    result = execute_function(greet, ["Alice"], {"greeting": "Hi"}, "function", {})
    assert result == "Hi, Alice!"


def test_execute_function_class():
    """Test executing class constructor and method."""

    class Calculator:
        def __init__(self, initial=0):
            self.value = initial

        def add(self, x):
            self.value += x
            return self.value

    job_input = {
        "method_name": "add",
        "method_args": [base64.b64encode(cloudpickle.dumps(5)).decode("utf-8")],
        "method_kwargs": {},
    }

    result = execute_function(Calculator, [10], {}, "class", job_input)
    assert result == 15


def test_create_handler_simple_function():
    """Test handler with simple function."""

    def multiply(a, b):
        return a * b

    handler = create_handler({"multiply": multiply})

    job = {
        "input": {
            "function_name": "multiply",
            "execution_type": "function",
            "args": [
                base64.b64encode(cloudpickle.dumps(6)).decode("utf-8"),
                base64.b64encode(cloudpickle.dumps(7)).decode("utf-8"),
            ],
            "kwargs": {},
        }
    }

    response = handler(job)
    assert response["success"] is True
    result = cloudpickle.loads(base64.b64decode(response["result"]))
    assert result == 42


def test_create_handler_missing_function():
    """Test handler with unknown function name."""

    def dummy():
        return "dummy"

    handler = create_handler({"dummy": dummy})

    job = {
        "input": {
            "function_name": "nonexistent",
            "execution_type": "function",
            "args": [],
            "kwargs": {},
        }
    }

    response = handler(job)
    assert response["success"] is False
    assert "not found" in response["error"]
    assert "dummy" in response["error"]


def test_create_handler_function_error():
    """Test handler when function raises error."""

    def error_func():
        raise ValueError("Test error")

    handler = create_handler({"error_func": error_func})

    job = {
        "input": {
            "function_name": "error_func",
            "execution_type": "function",
            "args": [],
            "kwargs": {},
        }
    }

    response = handler(job)
    assert response["success"] is False
    assert "Test error" in response["error"]
    assert "traceback" in response


def test_create_handler_class_method():
    """Test handler executing class method."""

    class Counter:
        def __init__(self, start=0):
            self.count = start

        def increment(self, amount=1):
            self.count += amount
            return self.count

    handler = create_handler({"Counter": Counter})

    job = {
        "input": {
            "function_name": "Counter",
            "execution_type": "class",
            "args": [base64.b64encode(cloudpickle.dumps(10)).decode("utf-8")],
            "kwargs": {},
            "method_name": "increment",
            "method_args": [base64.b64encode(cloudpickle.dumps(5)).decode("utf-8")],
            "method_kwargs": {},
        }
    }

    response = handler(job)
    assert response["success"] is True
    result = cloudpickle.loads(base64.b64decode(response["result"]))
    assert result == 15


def test_create_handler_multiple_functions():
    """Test handler with multiple functions in registry."""

    def add(a, b):
        return a + b

    def subtract(a, b):
        return a - b

    handler = create_handler({"add": add, "subtract": subtract})

    # Test add
    job1 = {
        "input": {
            "function_name": "add",
            "execution_type": "function",
            "args": [
                base64.b64encode(cloudpickle.dumps(5)).decode("utf-8"),
                base64.b64encode(cloudpickle.dumps(3)).decode("utf-8"),
            ],
            "kwargs": {},
        }
    }

    response1 = handler(job1)
    result1 = cloudpickle.loads(base64.b64decode(response1["result"]))
    assert result1 == 8

    # Test subtract
    job2 = {
        "input": {
            "function_name": "subtract",
            "execution_type": "function",
            "args": [
                base64.b64encode(cloudpickle.dumps(10)).decode("utf-8"),
                base64.b64encode(cloudpickle.dumps(3)).decode("utf-8"),
            ],
            "kwargs": {},
        }
    }

    response2 = handler(job2)
    result2 = cloudpickle.loads(base64.b64decode(response2["result"]))
    assert result2 == 7


def test_create_handler_complex_objects():
    """Test handler with complex Python objects."""

    def process_dict(data):
        return {**data, "processed": True}

    handler = create_handler({"process_dict": process_dict})

    input_data = {"key": "value", "nested": {"a": 1, "b": 2}}
    job = {
        "input": {
            "function_name": "process_dict",
            "execution_type": "function",
            "args": [base64.b64encode(cloudpickle.dumps(input_data)).decode("utf-8")],
            "kwargs": {},
        }
    }

    response = handler(job)
    assert response["success"] is True
    result = cloudpickle.loads(base64.b64decode(response["result"]))
    assert result == {"key": "value", "nested": {"a": 1, "b": 2}, "processed": True}


def test_create_handler_empty_registry():
    """Test handler with empty function registry."""
    handler = create_handler({})

    job = {
        "input": {
            "function_name": "anything",
            "execution_type": "function",
            "args": [],
            "kwargs": {},
        }
    }

    response = handler(job)
    assert response["success"] is False
    assert "not found" in response["error"]


def test_create_handler_default_execution_type():
    """Test handler defaults to 'function' execution type."""

    def dummy():
        return "done"

    handler = create_handler({"dummy": dummy})

    job = {
        "input": {
            "function_name": "dummy",
            "args": [],
            "kwargs": {},
            # No execution_type specified
        }
    }

    response = handler(job)
    assert response["success"] is True
    result = cloudpickle.loads(base64.b64decode(response["result"]))
    assert result == "done"


def test_create_handler_with_return_none():
    """Test handler when function returns None."""

    def returns_none():
        return None

    handler = create_handler({"returns_none": returns_none})

    job = {
        "input": {
            "function_name": "returns_none",
            "execution_type": "function",
            "args": [],
            "kwargs": {},
        }
    }

    response = handler(job)
    assert response["success"] is True
    result = cloudpickle.loads(base64.b64decode(response["result"]))
    assert result is None


def test_create_handler_input_none():
    """Test handler returns error when job input is None instead of crashing."""

    def dummy():
        return "dummy"

    handler = create_handler({"dummy": dummy})

    job = {"input": None}

    response = handler(job)
    assert response["success"] is False
    assert "not found" in response["error"]


def test_create_handler_input_missing():
    """Test handler returns error when job has no input key."""

    def dummy():
        return "dummy"

    handler = create_handler({"dummy": dummy})

    job = {}

    response = handler(job)
    assert response["success"] is False
    assert "not found" in response["error"]


def test_create_handler_input_non_dict():
    """Test handler rejects non-dict input types."""

    def dummy():
        return "dummy"

    handler = create_handler({"dummy": dummy})

    job = {"input": "not a dict"}

    response = handler(job)
    assert response["success"] is False
    assert "Invalid job input type" in response["error"]
    assert "str" in response["error"]


def test_create_deployed_handler_input_none():
    """Test deployed handler rejects None input."""

    def dummy(x: int = 1):
        return x

    handler = create_deployed_handler(dummy)

    job = {"input": None}

    result = handler(job)
    assert result["success"] is False
    assert "Empty or null input" in result["error"]


def test_create_deployed_handler_input_missing():
    """Test deployed handler rejects missing input key."""

    def dummy(x: int = 1):
        return x

    handler = create_deployed_handler(dummy)

    job = {}

    result = handler(job)
    assert result["success"] is False
    assert "Empty or null input" in result["error"]


def test_create_deployed_handler_input_non_dict():
    """Test deployed handler rejects non-dict input types."""

    def dummy(x: int = 1):
        return x

    handler = create_deployed_handler(dummy)

    job = {"input": [1, 2, 3]}

    result = handler(job)
    assert result["success"] is False
    assert "error" in result
    assert "list" in result["error"]
