"""Custom exceptions for runpod_flash.

Provides clear, actionable error messages for common failure scenarios.
"""

from runpod_flash.core.credentials import get_credentials_path


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
        credentials_path = get_credentials_path()
        return f"""RUNPOD_API_KEY environment variable is required but not set.

To use Flash remote execution features, you need a Runpod API key.

Get your API key:
  https://docs.runpod.io/get-started/api-keys

Set your API key using one of these methods:

  1. Environment variable:
     export RUNPOD_API_KEY=your_api_key_here

  2. In your project's .env file:
     echo "RUNPOD_API_KEY=your_api_key_here" >> .env

  3. In your shell profile (~/.bashrc, ~/.zshrc):
     echo 'export RUNPOD_API_KEY=your_api_key_here' >> ~/.bashrc

  4. Use the flash login flow:
     flash login

  5. Save directly to credentials file:
     {credentials_path}

Note: If you created a .env file, make sure it's in your current directory
or project root where Flash can find it."""
