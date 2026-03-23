"""Tests for pod integration in flash run."""

from unittest.mock import AsyncMock, MagicMock

from runpod_flash.core.resources.pod import Pod, PodState


class TestStopPods:
    """Test _stop_pods helper."""

    def test_stops_running_pods(self):
        from runpod_flash.cli.commands.run import _stop_pods

        lifecycle = MagicMock()
        lifecycle.stop = AsyncMock()

        pod = Pod("test", image="img")
        pod._state = PodState.RUNNING
        pod._pod_id = "pod-1"

        _stop_pods([pod], lifecycle)
        lifecycle.stop.assert_called_once()

    def test_skips_non_running_pods(self):
        from runpod_flash.cli.commands.run import _stop_pods

        lifecycle = MagicMock()
        lifecycle.stop = AsyncMock()

        pod = Pod("test", image="img")
        pod._state = PodState.STOPPED
        pod._pod_id = "pod-1"

        _stop_pods([pod], lifecycle)
        lifecycle.stop.assert_not_called()

    def test_handles_stop_failure_gracefully(self):
        from runpod_flash.cli.commands.run import _stop_pods

        lifecycle = MagicMock()
        lifecycle.stop = AsyncMock(side_effect=Exception("API down"))

        pod = Pod("test", image="img")
        pod._state = PodState.RUNNING
        pod._pod_id = "pod-1"

        # Should not raise
        _stop_pods([pod], lifecycle)
