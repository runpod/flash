"""Thread-local context for API key propagation across remote calls."""

import contextvars
from typing import Optional

# Context variable for API key extracted from incoming requests
_api_key_context: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "api_key_context", default=None
)


def set_api_key(api_key: Optional[str]) -> contextvars.Token:
    """Set API key in current context.

    Args:
        api_key: RunPod API key to use for remote calls

    Returns:
        Token that can be used to reset the context
    """
    return _api_key_context.set(api_key)


def get_api_key() -> Optional[str]:
    """Get API key from current context.

    Returns:
        API key if set, None otherwise
    """
    return _api_key_context.get()


def clear_api_key(token: Optional[contextvars.Token] = None) -> None:
    """Clear API key from current context.

    Args:
        token: Optional token from set_api_key() to reset to previous value.
               If None, sets context to None (backwards compatible).
    """
    if token is not None:
        _api_key_context.reset(token)
    else:
        _api_key_context.set(None)
