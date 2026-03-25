"""Configuration constants for runtime module."""

# HTTP client configuration
DEFAULT_REQUEST_TIMEOUT = 10  # seconds
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 2

# Manifest cache configuration
DEFAULT_CACHE_TTL = 300  # seconds

# Serialization limits
# max size of a single base64-encoded argument before decoding.
# base64 expands data by ~33%, so 10 MB encoded is ~7.5 MB decoded.
MAX_PAYLOAD_SIZE = 10 * 1024 * 1024  # 10 MB

# max wall-clock seconds for a single cloudpickle.loads() call
DESERIALIZE_TIMEOUT_SECONDS = 30
