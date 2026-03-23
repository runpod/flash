"""Tests for flash pod CLI commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import typer
import typer.testing

from runpod_flash.cli.commands.pod import pod_app
from runpod_flash.core.resources.pod import Pod, PodState
from runpod_flash.core.resources.pod_lifecycle import PodTrackerEntry

# All tests use a standalone Typer app wrapping the pod sub-app
# so the CliRunner invokes pod commands directly.
_app = typer.Typer()
_app.add_typer(pod_app, name="pod")
runner = typer.testing.CliRunner()

MODULE = "runpod_flash.cli.commands.pod"


def _make_entry(
    name: str = "test-pod",
    pod_id: str = "pod-abc123",
    image: str = "ubuntu:latest",
    gpu: str | None = "NVIDIA A100 80GB PCIe",
    state: str = "running",
    address: str | None = "http://1.2.3.4:8080",
    config_hash: str = "abc123",
    created_at: str = "2026-01-01T00:00:00+00:00",
) -> PodTrackerEntry:
    return PodTrackerEntry(
        name=name,
        pod_id=pod_id,
        image=image,
        gpu=gpu,
        state=state,
        address=address,
        config_hash=config_hash,
        created_at=created_at,
    )


class TestStatusCommand:
    """Tests for `flash pod status`."""

    @patch(f"{MODULE}._get_tracker")
    def test_status_no_pods(self, mock_get_tracker: MagicMock) -> None:
        tracker = MagicMock()
        tracker.load_all.return_value = []
        mock_get_tracker.return_value = tracker

        result = runner.invoke(_app, ["pod", "status"])

        assert result.exit_code == 0
        assert "No tracked pods" in result.output

    @patch(f"{MODULE}._get_tracker")
    def test_status_with_pods(self, mock_get_tracker: MagicMock) -> None:
        entry = _make_entry()
        tracker = MagicMock()
        tracker.load_all.return_value = [entry]
        mock_get_tracker.return_value = tracker

        result = runner.invoke(_app, ["pod", "status"])

        assert result.exit_code == 0
        assert "test-pod" in result.output
        assert "running" in result.output
        assert "ubuntu:latest" in result.output

    @patch(f"{MODULE}._get_tracker")
    def test_status_single_pod(self, mock_get_tracker: MagicMock) -> None:
        entry = _make_entry()
        tracker = MagicMock()
        tracker.load.return_value = entry
        mock_get_tracker.return_value = tracker

        result = runner.invoke(_app, ["pod", "status", "test-pod"])

        assert result.exit_code == 0
        assert "test-pod" in result.output
        assert "pod-abc123" in result.output

    @patch(f"{MODULE}._get_tracker")
    def test_status_single_pod_not_found(self, mock_get_tracker: MagicMock) -> None:
        tracker = MagicMock()
        tracker.load.return_value = None
        mock_get_tracker.return_value = tracker

        result = runner.invoke(_app, ["pod", "status", "ghost"])

        assert result.exit_code == 1
        assert "not found" in result.output


class TestCreateCommand:
    """Tests for `flash pod create`."""

    @patch(f"{MODULE}._get_lifecycle")
    def test_create_provisions_pod(self, mock_get_lifecycle: MagicMock) -> None:
        mock_lifecycle = MagicMock()

        async def fake_provision(pod: Pod) -> Pod:
            pod._pod_id = "pod-new123"
            pod._state = PodState.RUNNING
            pod._address = "http://5.6.7.8:8080"
            return pod

        mock_lifecycle.provision = AsyncMock(side_effect=fake_provision)
        mock_get_lifecycle.return_value = mock_lifecycle

        result = runner.invoke(
            _app,
            [
                "pod",
                "create",
                "my-pod",
                "--image",
                "pytorch:latest",
                "--gpu",
                "NVIDIA A100 80GB PCIe",
            ],
        )

        assert result.exit_code == 0
        assert "Pod created successfully" in result.output
        assert "my-pod" in result.output
        assert "pod-new123" in result.output
        mock_lifecycle.provision.assert_called_once()

    @patch(f"{MODULE}._get_lifecycle")
    def test_create_cpu_pod(self, mock_get_lifecycle: MagicMock) -> None:
        mock_lifecycle = MagicMock()

        async def fake_provision(pod: Pod) -> Pod:
            pod._pod_id = "pod-cpu1"
            pod._state = PodState.RUNNING
            pod._address = None
            return pod

        mock_lifecycle.provision = AsyncMock(side_effect=fake_provision)
        mock_get_lifecycle.return_value = mock_lifecycle

        result = runner.invoke(
            _app,
            ["pod", "create", "cpu-pod", "--image", "ubuntu:latest"],
        )

        assert result.exit_code == 0
        assert "cpu-pod" in result.output


class TestStopCommand:
    """Tests for `flash pod stop`."""

    @patch(f"{MODULE}._get_lifecycle")
    @patch(f"{MODULE}._get_tracker")
    def test_stop_not_found(
        self, mock_get_tracker: MagicMock, mock_get_lifecycle: MagicMock
    ) -> None:
        tracker = MagicMock()
        tracker.load.return_value = None
        mock_get_tracker.return_value = tracker

        result = runner.invoke(_app, ["pod", "stop", "nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output

    @patch(f"{MODULE}._get_lifecycle")
    @patch(f"{MODULE}._get_tracker")
    def test_stop_success(
        self, mock_get_tracker: MagicMock, mock_get_lifecycle: MagicMock
    ) -> None:
        entry = _make_entry(state="running")
        tracker = MagicMock()
        tracker.load.return_value = entry
        mock_get_tracker.return_value = tracker

        mock_lifecycle = MagicMock()
        mock_lifecycle.stop = AsyncMock()
        mock_get_lifecycle.return_value = mock_lifecycle

        result = runner.invoke(_app, ["pod", "stop", "test-pod"])

        assert result.exit_code == 0
        assert "stopped" in result.output


class TestTerminateCommand:
    """Tests for `flash pod terminate`."""

    def test_terminate_requires_confirmation(self) -> None:
        """Without --yes, terminate should prompt and abort on 'n'."""
        result = runner.invoke(_app, ["pod", "terminate", "test-pod"], input="n\n")

        assert "Aborted" in result.output or result.exit_code != 0

    @patch(f"{MODULE}._get_lifecycle")
    @patch(f"{MODULE}._get_tracker")
    def test_terminate_with_yes(
        self, mock_get_tracker: MagicMock, mock_get_lifecycle: MagicMock
    ) -> None:
        entry = _make_entry(state="running")
        tracker = MagicMock()
        tracker.load.return_value = entry
        mock_get_tracker.return_value = tracker

        mock_lifecycle = MagicMock()
        mock_lifecycle.terminate = AsyncMock()
        mock_get_lifecycle.return_value = mock_lifecycle

        result = runner.invoke(_app, ["pod", "terminate", "test-pod", "--yes"])

        assert result.exit_code == 0
        assert "terminated" in result.output


class TestStartCommand:
    """Tests for `flash pod start`."""

    @patch(f"{MODULE}._get_lifecycle")
    @patch(f"{MODULE}._get_tracker")
    def test_start_success(
        self, mock_get_tracker: MagicMock, mock_get_lifecycle: MagicMock
    ) -> None:
        entry = _make_entry(state="stopped")
        tracker = MagicMock()
        tracker.load.return_value = entry
        mock_get_tracker.return_value = tracker

        mock_lifecycle = MagicMock()

        async def fake_resume(pod: Pod) -> Pod:
            pod._state = PodState.RUNNING
            pod._address = "http://1.2.3.4:8080"
            return pod

        mock_lifecycle.resume = AsyncMock(side_effect=fake_resume)
        mock_get_lifecycle.return_value = mock_lifecycle

        result = runner.invoke(_app, ["pod", "start", "test-pod"])

        assert result.exit_code == 0
        assert "started" in result.output


class TestSshCommand:
    """Tests for `flash pod ssh`."""

    @patch(f"{MODULE}._get_tracker")
    def test_ssh_not_running(self, mock_get_tracker: MagicMock) -> None:
        entry = _make_entry(state="stopped")
        tracker = MagicMock()
        tracker.load.return_value = entry
        mock_get_tracker.return_value = tracker

        result = runner.invoke(_app, ["pod", "ssh", "test-pod"])

        assert result.exit_code == 1
        assert "not running" in result.output

    @patch(f"{MODULE}._get_tracker")
    def test_ssh_running(self, mock_get_tracker: MagicMock) -> None:
        entry = _make_entry(state="running", address="http://1.2.3.4:8080")
        tracker = MagicMock()
        tracker.load.return_value = entry
        mock_get_tracker.return_value = tracker

        result = runner.invoke(_app, ["pod", "ssh", "test-pod"])

        assert result.exit_code == 0
        assert "SSH Connection Info" in result.output
        assert "1.2.3.4" in result.output
