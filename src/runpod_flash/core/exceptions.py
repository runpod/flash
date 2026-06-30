"""Custom exceptions for runpod_flash.

Provides clear, actionable error messages for common failure scenarios.
"""


class RunpodAPIKeyError(Exception):
    """Raised when RUNPOD_API_KEY environment variable is missing or invalid.

    This exception provides helpful guidance on how to obtain and configure
    the API key required for remote execution and deployment features.
    """

    def __init__(self, message: str | None = None):
        """Initialize with optional custom message.

        Args:
            message: Optional custom error message. If not provided, uses default.
        """
        if message is None:
            message = self._default_message()
        super().__init__(message)

    @staticmethod
    def _default_message() -> str:
        """Generate default error message with setup instructions.

        Returns:
            Formatted error message with actionable steps.
        """
        return (
            "No RunPod API key found. Set one with:\n"
            "\n"
            "  flash login                              # interactive setup\n"
            "                 or\n"
            "  export RUNPOD_API_KEY=<your-api-key>     # environment variable\n"
            "                 or\n"
            "  echo 'RUNPOD_API_KEY=<your-api-key>' >> .env\n"
            "\n"
            "Get a key: https://docs.runpod.io/get-started/api-keys"
        )
