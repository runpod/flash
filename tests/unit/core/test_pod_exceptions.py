"""Tests for pod-related exceptions."""

from __future__ import annotations

from runpod_flash.core.exceptions import (
    InvalidPodStateError,
    PodNotFoundError,
    PodNotRunningError,
    PodRequestError,
    PodStartupTimeoutError,
)


class TestPodNotRunningError:
    def test_message_includes_pod_name_and_state(self) -> None:
        err = PodNotRunningError("my-pod", "stopped")
        assert "my-pod" in str(err)
        assert "stopped" in str(err)

    def test_message_includes_remediation_command(self) -> None:
        err = PodNotRunningError("my-pod", "stopped")
        assert "flash pod start my-pod" in str(err)

    def test_attributes_stored(self) -> None:
        err = PodNotRunningError("my-pod", "stopped")
        assert err.pod_name == "my-pod"
        assert err.state == "stopped"


class TestPodNotFoundError:
    def test_message_includes_pod_name(self) -> None:
        err = PodNotFoundError("ghost-pod")
        assert "ghost-pod" in str(err)

    def test_message_includes_status_command(self) -> None:
        err = PodNotFoundError("ghost-pod")
        assert "flash pod status" in str(err)

    def test_attributes_stored(self) -> None:
        err = PodNotFoundError("ghost-pod")
        assert err.pod_name == "ghost-pod"


class TestInvalidPodStateError:
    def test_message_includes_all_info(self) -> None:
        valid = {"stopping", "terminating"}
        err = InvalidPodStateError("my-pod", "running", "resuming", valid)
        msg = str(err)
        assert "my-pod" in msg
        assert "running" in msg
        assert "resuming" in msg

    def test_valid_transitions_sorted_in_message(self) -> None:
        valid = {"terminating", "stopping"}
        err = InvalidPodStateError("my-pod", "running", "resuming", valid)
        msg = str(err)
        # Sorted alphabetically
        assert "stopping, terminating" in msg

    def test_attributes_stored(self) -> None:
        valid = {"stopping", "terminating"}
        err = InvalidPodStateError("my-pod", "running", "resuming", valid)
        assert err.pod_name == "my-pod"
        assert err.current == "running"
        assert err.target == "resuming"
        assert err.valid == valid


class TestPodRequestError:
    def test_message_includes_status_code(self) -> None:
        err = PodRequestError(404, b"not found")
        assert "404" in str(err)

    def test_message_includes_truncated_body(self) -> None:
        err = PodRequestError(500, b"x" * 300)
        msg = str(err)
        assert "500" in msg
        # Body should be truncated
        assert len(msg) < 400

    def test_attributes_stored(self) -> None:
        err = PodRequestError(500, b"error body")
        assert err.status_code == 500
        assert err.body == b"error body"


class TestPodStartupTimeoutError:
    def test_message_includes_pod_name_and_timeout(self) -> None:
        err = PodStartupTimeoutError("slow-pod", 120)
        msg = str(err)
        assert "slow-pod" in msg
        assert "120" in msg

    def test_attributes_stored(self) -> None:
        err = PodStartupTimeoutError("slow-pod", 120)
        assert err.pod_name == "slow-pod"
        assert err.timeout_seconds == 120
