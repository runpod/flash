"""Custom exceptions for runpod_flash.

Provides clear, actionable error messages for common failure scenarios.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from runpod_flash.core.resources.pod import PodState

BODY_TRUNCATE_LENGTH = 200


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


class PodNotRunningError(Exception):
    """Raised when an operation requires a running pod but the pod is in another state."""

    def __init__(self, pod_name: str, state: "PodState") -> None:
        self.pod_name = pod_name
        self.state = state
        super().__init__(
            f"Pod '{pod_name}' is in state '{state}', not running. "
            f"Start it with: flash pod start {pod_name}"
        )


class PodNotFoundError(Exception):
    """Raised when a pod cannot be found by name."""

    def __init__(self, pod_name: str) -> None:
        self.pod_name = pod_name
        super().__init__(
            f"Pod '{pod_name}' not found. Check available pods with: flash pod status"
        )


class InvalidPodStateError(Exception):
    """Raised when a state transition is not valid for the current pod state."""

    def __init__(
        self,
        pod_name: str,
        current: "PodState",
        target: "PodState",
        valid: set["PodState"],
    ) -> None:
        self.pod_name = pod_name
        self.current = current
        self.target = target
        self.valid = valid
        sorted_valid = ", ".join(sorted(str(v) for v in valid))
        super().__init__(
            f"Pod '{pod_name}' cannot transition from '{current}' to '{target}'. "
            f"Valid transitions: {sorted_valid}"
        )


class PodRequestError(Exception):
    """Raised when a Runpod API request fails."""

    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self.body = body
        truncated = body[:BODY_TRUNCATE_LENGTH].decode(errors="replace")
        super().__init__(
            f"Pod API request failed with status {status_code}: {truncated}"
        )


class PodStartupTimeoutError(Exception):
    """Raised when a pod does not reach running state within the timeout."""

    def __init__(self, pod_name: str, timeout_seconds: int) -> None:
        self.pod_name = pod_name
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Pod '{pod_name}' did not start within {timeout_seconds} seconds"
        )
