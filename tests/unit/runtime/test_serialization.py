"""Tests for serialization utilities."""

import time
from unittest.mock import patch

import cloudpickle
import pytest

from runpod_flash.runtime.config import MAX_PAYLOAD_SIZE
from runpod_flash.runtime.exceptions import (
    DeserializeTimeoutError,
    PayloadTooLargeError,
    SerializationError,
)
from runpod_flash.runtime.serialization import (
    _check_payload_size,
    _unpickle_with_timeout,
    deserialize_arg,
    deserialize_args,
    deserialize_kwargs,
    serialize_arg,
    serialize_args,
    serialize_kwargs,
)


class TestSerializeArg:
    """Test serialize_arg function."""

    def test_serialize_simple_arg(self):
        """Test serializing a simple argument."""
        result = serialize_arg(42)
        assert isinstance(result, str)
        import base64

        decoded = base64.b64decode(result)
        assert len(decoded) > 0

    def test_serialize_raises_on_cloudpickle_error(self):
        """Test serialize_arg handles cloudpickle errors."""
        with patch("cloudpickle.dumps") as mock_dumps:
            mock_dumps.side_effect = RuntimeError("Unexpected cloudpickle error")
            with pytest.raises(
                SerializationError, match="Failed to serialize argument"
            ):
                serialize_arg(42)


class TestSerializeArgs:
    """Test serialize_args function."""

    def test_serialize_multiple_args(self):
        """Test serializing multiple arguments."""
        result = serialize_args((1, "test", [1, 2, 3]))
        assert len(result) == 3
        assert all(isinstance(item, str) for item in result)

    def test_serialize_empty_args(self):
        """Test serializing empty args tuple."""
        result = serialize_args(())
        assert result == []

    def test_serialize_args_propagates_serialization_error(self):
        """Test serialize_args propagates SerializationError."""
        with patch(
            "runpod_flash.runtime.serialization.serialize_arg"
        ) as mock_serialize:
            mock_serialize.side_effect = SerializationError("Known error")
            with pytest.raises(SerializationError, match="Known error"):
                serialize_args((1, 2))

    def test_serialize_args_unexpected_error(self):
        """Test serialize_args handles unexpected exceptions."""
        with patch(
            "runpod_flash.runtime.serialization.serialize_arg"
        ) as mock_serialize:
            mock_serialize.side_effect = RuntimeError("Unexpected error")
            with pytest.raises(SerializationError, match="Failed to serialize args"):
                serialize_args((1, 2))


class TestSerializeKwargs:
    """Test serialize_kwargs function."""

    def test_serialize_kwargs(self):
        """Test serializing keyword arguments."""
        result = serialize_kwargs({"key1": 42, "key2": "test"})
        assert len(result) == 2
        assert "key1" in result
        assert "key2" in result
        assert all(isinstance(v, str) for v in result.values())

    def test_serialize_empty_kwargs(self):
        """Test serializing empty kwargs dict."""
        result = serialize_kwargs({})
        assert result == {}

    def test_serialize_kwargs_propagates_serialization_error(self):
        """Test serialize_kwargs propagates SerializationError."""
        with patch(
            "runpod_flash.runtime.serialization.serialize_arg"
        ) as mock_serialize:
            mock_serialize.side_effect = SerializationError("Known error")
            with pytest.raises(SerializationError, match="Known error"):
                serialize_kwargs({"key": 42})

    def test_serialize_kwargs_unexpected_error(self):
        """Test serialize_kwargs handles unexpected exceptions."""
        with patch(
            "runpod_flash.runtime.serialization.serialize_arg"
        ) as mock_serialize:
            mock_serialize.side_effect = RuntimeError("Unexpected error")
            with pytest.raises(SerializationError, match="Failed to serialize kwargs"):
                serialize_kwargs({"key": 42})


class TestCheckPayloadSize:
    """Test _check_payload_size function."""

    def test_within_limit(self):
        """Payloads within MAX_PAYLOAD_SIZE pass silently."""
        _check_payload_size("a" * 100)

    def test_at_limit(self):
        """Payload exactly at MAX_PAYLOAD_SIZE passes."""
        _check_payload_size("a" * MAX_PAYLOAD_SIZE)

    def test_over_limit(self):
        """Payload exceeding MAX_PAYLOAD_SIZE raises PayloadTooLargeError."""
        with pytest.raises(PayloadTooLargeError, match="exceeds limit"):
            _check_payload_size("a" * (MAX_PAYLOAD_SIZE + 1))

    def test_error_message_includes_sizes(self):
        """Error message reports actual and limit sizes in MB."""
        oversized = "a" * (MAX_PAYLOAD_SIZE + 1)
        with pytest.raises(PayloadTooLargeError) as exc_info:
            _check_payload_size(oversized)
        msg = str(exc_info.value)
        assert "MB" in msg
        assert "10.0 MB" in msg


class TestUnpickleWithTimeout:
    """Test _unpickle_with_timeout function."""

    def test_normal_deserialization(self):
        """Small payloads deserialize within the timeout."""
        data = cloudpickle.dumps(42)
        assert _unpickle_with_timeout(data, 5) == 42

    def test_timeout_raises(self):
        """A slow unpickle triggers DeserializeTimeoutError."""

        def slow_loads(data):
            time.sleep(5)
            return None

        with patch("runpod_flash.runtime.serialization.cloudpickle") as mock_cp:
            mock_cp.loads = slow_loads
            with pytest.raises(DeserializeTimeoutError, match="timed out"):
                _unpickle_with_timeout(b"fake", 1)


class TestDeserializeArg:
    """Test deserialize_arg function."""

    def test_roundtrip(self):
        """Serialize then deserialize returns the original value."""
        serialized = serialize_arg(42)
        result = deserialize_arg(serialized)
        assert result == 42

    def test_raises_on_invalid_base64(self):
        """Invalid base64 raises SerializationError."""
        with pytest.raises(SerializationError, match="Failed to deserialize argument"):
            deserialize_arg("not-valid-base64!!!")

    def test_rejects_oversized_payload(self):
        """Payload larger than MAX_PAYLOAD_SIZE raises PayloadTooLargeError."""
        oversized = "A" * (MAX_PAYLOAD_SIZE + 1)
        with pytest.raises(PayloadTooLargeError):
            deserialize_arg(oversized)

    def test_timeout_on_slow_unpickle(self):
        """Slow cloudpickle.loads raises DeserializeTimeoutError."""
        valid_b64 = serialize_arg("hello")

        def slow_loads(data):
            time.sleep(5)

        with patch("runpod_flash.runtime.serialization.cloudpickle") as mock_cp:
            mock_cp.loads = slow_loads
            with patch(
                "runpod_flash.runtime.serialization.DESERIALIZE_TIMEOUT_SECONDS", 1
            ):
                with pytest.raises(DeserializeTimeoutError):
                    deserialize_arg(valid_b64)


class TestDeserializeArgs:
    """Test deserialize_args function."""

    def test_deserialize_multiple_args(self):
        """Test deserializing multiple arguments."""
        serialized = serialize_args((1, "test", [1, 2, 3]))
        result = deserialize_args(serialized)
        assert result == [1, "test", [1, 2, 3]]

    def test_deserialize_empty_args(self):
        """Test deserializing empty args list."""
        result = deserialize_args([])
        assert result == []

    def test_propagates_payload_too_large(self):
        """PayloadTooLargeError from a single arg propagates."""
        oversized = "A" * (MAX_PAYLOAD_SIZE + 1)
        with pytest.raises(PayloadTooLargeError):
            deserialize_args([oversized])

    def test_deserialize_args_propagates_serialization_error(self):
        """Test deserialize_args propagates SerializationError."""
        with patch(
            "runpod_flash.runtime.serialization.deserialize_arg"
        ) as mock_deserialize:
            mock_deserialize.side_effect = SerializationError("Known error")
            with pytest.raises(SerializationError, match="Known error"):
                deserialize_args(["arg1", "arg2"])

    def test_deserialize_args_unexpected_error(self):
        """Test deserialize_args handles unexpected exceptions."""
        with patch(
            "runpod_flash.runtime.serialization.deserialize_arg"
        ) as mock_deserialize:
            mock_deserialize.side_effect = RuntimeError("Unexpected error")
            with pytest.raises(SerializationError, match="Failed to deserialize args"):
                deserialize_args(["arg1", "arg2"])


class TestDeserializeKwargs:
    """Test deserialize_kwargs function."""

    def test_deserialize_kwargs(self):
        """Test deserializing keyword arguments."""
        serialized = serialize_kwargs({"key1": 42, "key2": "test"})
        result = deserialize_kwargs(serialized)
        assert result == {"key1": 42, "key2": "test"}

    def test_deserialize_empty_kwargs(self):
        """Test deserializing empty kwargs dict."""
        result = deserialize_kwargs({})
        assert result == {}

    def test_propagates_payload_too_large(self):
        """PayloadTooLargeError from a single kwarg value propagates."""
        oversized = "A" * (MAX_PAYLOAD_SIZE + 1)
        with pytest.raises(PayloadTooLargeError):
            deserialize_kwargs({"big": oversized})

    def test_deserialize_kwargs_propagates_serialization_error(self):
        """Test deserialize_kwargs propagates SerializationError."""
        with patch(
            "runpod_flash.runtime.serialization.deserialize_arg"
        ) as mock_deserialize:
            mock_deserialize.side_effect = SerializationError("Known error")
            with pytest.raises(SerializationError, match="Known error"):
                deserialize_kwargs({"key": "value"})

    def test_deserialize_kwargs_unexpected_error(self):
        """Test deserialize_kwargs handles unexpected exceptions."""
        with patch(
            "runpod_flash.runtime.serialization.deserialize_arg"
        ) as mock_deserialize:
            mock_deserialize.side_effect = RuntimeError("Unexpected error")
            with pytest.raises(
                SerializationError, match="Failed to deserialize kwargs"
            ):
                deserialize_kwargs({"key": "value"})
