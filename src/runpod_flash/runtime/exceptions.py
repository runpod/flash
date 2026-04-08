"""Custom exceptions for cross-endpoint runtime."""


class FlashRuntimeError(Exception):
    """Base exception for runtime errors in cross-endpoint execution."""

    pass


class RemoteExecutionError(FlashRuntimeError):
    """Raised when remote function execution fails."""

    pass


class SerializationError(FlashRuntimeError):
    """Raised when serialization or deserialization of arguments fails."""

    pass


class PayloadTooLargeError(SerializationError):
    """Raised when a serialized argument exceeds MAX_PAYLOAD_SIZE."""

    pass


class DeserializeTimeoutError(SerializationError):
    """Raised when cloudpickle.loads() exceeds DESERIALIZE_TIMEOUT_SECONDS."""

    pass


class GraphQLError(FlashRuntimeError):
    """Base exception for GraphQL-related errors."""

    pass


class GraphQLMutationError(GraphQLError):
    """Raised when a GraphQL mutation fails unexpectedly."""

    pass


class GraphQLQueryError(GraphQLError):
    """Raised when a GraphQL query fails unexpectedly."""

    pass


class ManifestError(FlashRuntimeError):
    """Raised when manifest is invalid, missing, or has unexpected structure."""

    pass


class ManifestServiceUnavailableError(FlashRuntimeError):
    """Raised when manifest service is unavailable."""

    pass
