"""Validation utilities for runpod_flash configuration.

Provides validation functions for required environment variables and configuration.
"""

from runpod_flash.core.credentials import get_api_key
from runpod_flash.core.exceptions import RunpodAPIKeyError


def validate_api_key() -> str:
    """Validate that RUNPOD_API_KEY environment variable is set.

    Returns:
        The API key value if present.

    Raises:
        RunpodAPIKeyError: If RUNPOD_API_KEY is not set or is empty.
    """
    api_key = get_api_key()

    if not api_key or not api_key.strip():
        raise RunpodAPIKeyError()

    return api_key


def validate_api_key_with_context(operation: str) -> str:
    """Validate API key with additional context about the operation.

    Args:
        operation: Description of what operation requires the API key.

    Returns:
        The API key value if present.

    Raises:
        RunpodAPIKeyError: If RUNPOD_API_KEY is not set, with operation context.
    """
    try:
        return validate_api_key()
    except RunpodAPIKeyError as e:
        context_message = f"Cannot {operation}: {str(e)}"
        raise RunpodAPIKeyError(context_message) from e
