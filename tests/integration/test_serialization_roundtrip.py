"""Integration tests for serialization round-trips.

Exercises the full serialize_arg → base64 → deserialize_arg path
to catch silent data corruption bugs.
"""

import pytest

from runpod_flash.runtime.serialization import (
    deserialize_arg,
    deserialize_args,
    deserialize_kwargs,
    serialize_arg,
    serialize_args,
    serialize_kwargs,
)


class TestSerializationRoundtrip:
    """End-to-end round-trip tests through cloudpickle + base64 encoding."""

    def test_primitive_types_roundtrip(self):
        """int, float, str, bool, None all survive serialization."""
        primitives = [42, 3.14, "hello world", True, False, None, 0, -1, "", 1e100]
        for value in primitives:
            result = deserialize_arg(serialize_arg(value))
            assert result == value, f"Round-trip failed for {value!r}"
            assert type(result) is type(value)

    def test_complex_types_roundtrip(self):
        """dict, list, nested structures survive serialization."""
        cases = [
            [1, 2, 3],
            {"key": "value", "nested": {"a": [1, 2]}},
            (1, "two", 3.0),
            {1, 2, 3},
            {"list": [{"nested": True}], "tuple": (1, 2)},
            [],
            {},
            b"binary data",
        ]
        for value in cases:
            result = deserialize_arg(serialize_arg(value))
            assert result == value, f"Round-trip failed for {value!r}"

    def test_lambda_roundtrip(self):
        """Lambda functions survive cloudpickle serialization."""
        fn = lambda x, y: x + y  # noqa: E731
        restored = deserialize_arg(serialize_arg(fn))
        assert restored(3, 4) == 7
        assert restored("a", "b") == "ab"

    def test_custom_class_roundtrip(self):
        """User-defined class instances survive serialization."""

        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y

            def __eq__(self, other):
                return self.x == other.x and self.y == other.y

        point = Point(3, 7)
        restored = deserialize_arg(serialize_arg(point))
        assert restored == point
        assert restored.x == 3
        assert restored.y == 7

    def test_function_with_closure_roundtrip(self):
        """Function capturing outer scope variables survives serialization."""
        multiplier = 10

        def scale(x):
            return x * multiplier

        restored = deserialize_arg(serialize_arg(scale))
        assert restored(5) == 50

    def test_unserializable_raises(self):
        """Non-picklable objects raise SerializationError."""
        from runpod_flash.runtime.exceptions import SerializationError

        # Use a generator object — cloudpickle cannot serialize active generators
        def _gen():
            yield 1

        gen = _gen()
        next(gen)  # Advance to make it an active generator
        with pytest.raises(SerializationError):
            serialize_arg(gen)

    def test_args_list_roundtrip(self):
        """serialize_args/deserialize_args handle positional arg lists."""
        args = (42, "hello", [1, 2, 3])
        serialized = serialize_args(args)
        assert isinstance(serialized, list)
        assert len(serialized) == 3
        assert all(isinstance(s, str) for s in serialized)

        restored = deserialize_args(serialized)
        assert restored[0] == 42
        assert restored[1] == "hello"
        assert restored[2] == [1, 2, 3]

    def test_kwargs_dict_roundtrip(self):
        """serialize_kwargs/deserialize_kwargs handle keyword arg dicts."""
        kwargs = {"name": "test", "count": 5, "nested": {"a": 1}}
        serialized = serialize_kwargs(kwargs)
        assert isinstance(serialized, dict)
        assert all(isinstance(k, str) for k in serialized.keys())
        assert all(isinstance(v, str) for v in serialized.values())

        restored = deserialize_kwargs(serialized)
        assert restored == kwargs

    def test_numpy_array_roundtrip(self):
        """RT-SER-004: numpy arrays survive serialize → deserialize roundtrip."""
        np = pytest.importorskip("numpy")

        # 1D array
        arr_1d = np.array([1.0, 2.0, 3.0])
        restored_1d = deserialize_arg(serialize_arg(arr_1d))
        np.testing.assert_array_equal(restored_1d, arr_1d)
        assert restored_1d.dtype == arr_1d.dtype

        # 2D array
        arr_2d = np.array([[1, 2, 3], [4, 5, 6]])
        restored_2d = deserialize_arg(serialize_arg(arr_2d))
        np.testing.assert_array_equal(restored_2d, arr_2d)
        assert restored_2d.shape == (2, 3)

        # Different dtypes
        for dtype in [np.float32, np.int64, np.bool_]:
            arr = np.zeros((3, 3), dtype=dtype)
            restored = deserialize_arg(serialize_arg(arr))
            np.testing.assert_array_equal(restored, arr)
            assert restored.dtype == dtype
