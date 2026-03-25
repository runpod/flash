"""Shared serialization utilities for cloudpickle + base64 encoding."""

import base64
import concurrent.futures
from typing import Any, Dict, List

import cloudpickle

from .config import DESERIALIZE_TIMEOUT_SECONDS, MAX_PAYLOAD_SIZE
from .exceptions import (
    DeserializeTimeoutError,
    PayloadTooLargeError,
    SerializationError,
)


def serialize_arg(arg: Any) -> str:
    """Serialize single argument with cloudpickle + base64.

    Args:
        arg: Argument to serialize.

    Returns:
        Base64-encoded cloudpickle serialized string.

    Raises:
        SerializationError: If serialization fails.
    """
    try:
        return base64.b64encode(cloudpickle.dumps(arg)).decode("utf-8")
    except Exception as e:
        raise SerializationError(f"Failed to serialize argument: {e}") from e


def serialize_args(args: tuple) -> List[str]:
    """Serialize positional arguments.

    Args:
        args: Tuple of arguments to serialize.

    Returns:
        List of base64-encoded serialized arguments.

    Raises:
        SerializationError: If serialization fails.
    """
    try:
        return [serialize_arg(arg) for arg in args]
    except SerializationError:
        raise
    except Exception as e:
        raise SerializationError(f"Failed to serialize args: {e}") from e


def serialize_kwargs(kwargs: dict) -> Dict[str, str]:
    """Serialize keyword arguments.

    Args:
        kwargs: Dictionary of keyword arguments.

    Returns:
        Dictionary with base64-encoded serialized values.

    Raises:
        SerializationError: If serialization fails.
    """
    try:
        return {k: serialize_arg(v) for k, v in kwargs.items()}
    except SerializationError:
        raise
    except Exception as e:
        raise SerializationError(f"Failed to serialize kwargs: {e}") from e


def _check_payload_size(data: str) -> None:
    """Reject a base64-encoded payload that exceeds MAX_PAYLOAD_SIZE.

    Raises:
        PayloadTooLargeError: If len(data) > MAX_PAYLOAD_SIZE.
    """
    size = len(data)
    if size > MAX_PAYLOAD_SIZE:
        limit_mb = MAX_PAYLOAD_SIZE / (1024 * 1024)
        actual_mb = size / (1024 * 1024)
        raise PayloadTooLargeError(
            f"Payload size {actual_mb:.1f} MB exceeds limit of {limit_mb:.1f} MB"
        )


def _unpickle_with_timeout(data: bytes, timeout: int) -> Any:
    """Run cloudpickle.loads in a worker thread with a wall-clock timeout.

    Args:
        data: Pickled bytes to deserialize.
        timeout: Maximum seconds to allow.

    Returns:
        Deserialized Python object.

    Raises:
        DeserializeTimeoutError: If deserialization exceeds timeout.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(cloudpickle.loads, data)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise DeserializeTimeoutError(f"Deserialization timed out after {timeout}s")


def deserialize_arg(arg_b64: str) -> Any:
    """Deserialize single base64-encoded cloudpickle argument.

    Validates payload size before decoding and applies a wall-clock
    timeout to the unpickle step.

    Args:
        arg_b64: Base64-encoded serialized argument.

    Returns:
        Deserialized argument.

    Raises:
        PayloadTooLargeError: If the encoded payload exceeds MAX_PAYLOAD_SIZE.
        DeserializeTimeoutError: If cloudpickle.loads exceeds DESERIALIZE_TIMEOUT_SECONDS.
        SerializationError: If deserialization fails for any other reason.
    """
    try:
        _check_payload_size(arg_b64)
        raw = base64.b64decode(arg_b64)
        return _unpickle_with_timeout(raw, DESERIALIZE_TIMEOUT_SECONDS)
    except (PayloadTooLargeError, DeserializeTimeoutError):
        raise
    except Exception as e:
        raise SerializationError(f"Failed to deserialize argument: {e}") from e


def deserialize_args(args_b64: List[str]) -> List[Any]:
    """Deserialize list of base64-encoded arguments.

    Args:
        args_b64: List of base64-encoded serialized arguments.

    Returns:
        List of deserialized arguments.

    Raises:
        PayloadTooLargeError: If any encoded argument exceeds MAX_PAYLOAD_SIZE.
        DeserializeTimeoutError: If any cloudpickle.loads exceeds the timeout.
        SerializationError: If deserialization fails for any other reason.
    """
    try:
        return [deserialize_arg(arg) for arg in args_b64]
    except (PayloadTooLargeError, DeserializeTimeoutError, SerializationError):
        raise
    except Exception as e:
        raise SerializationError(f"Failed to deserialize args: {e}") from e


def deserialize_kwargs(kwargs_b64: Dict[str, str]) -> Dict[str, Any]:
    """Deserialize dict of base64-encoded keyword arguments.

    Args:
        kwargs_b64: Dictionary with base64-encoded serialized values.

    Returns:
        Dictionary with deserialized values.

    Raises:
        PayloadTooLargeError: If any encoded value exceeds MAX_PAYLOAD_SIZE.
        DeserializeTimeoutError: If any cloudpickle.loads exceeds the timeout.
        SerializationError: If deserialization fails for any other reason.
    """
    try:
        return {k: deserialize_arg(v) for k, v in kwargs_b64.items()}
    except (PayloadTooLargeError, DeserializeTimeoutError, SerializationError):
        raise
    except Exception as e:
        raise SerializationError(f"Failed to deserialize kwargs: {e}") from e
