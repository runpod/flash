"""Tests for pod lifecycle manager, tracker, and drift detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from runpod_flash.core.api.pod_client import PodApiResponse, PortMapping
from runpod_flash.core.exceptions import InvalidPodStateError
from runpod_flash.core.resources.pod import Pod, PodState
from runpod_flash.core.resources.pod_lifecycle import (
    PodLifecycleManager,
    PodTracker,
    PodTrackerEntry,
    detect_pod_drift,
)


def _make_api_response(**overrides: object) -> PodApiResponse:
    """Build a PodApiResponse with sensible defaults."""
    defaults = {
        "pod_id": "pod-1",
        "name": "test",
        "desired_status": "RUNNING",
        "image_name": "img",
        "gpu_display_name": None,
        "public_ip": None,
        "ports": {"8000/tcp": PortMapping("1.2.3.4", 43215, "tcp")},
        "cost_per_hr": 1.0,
        "uptime_seconds": 0,
        "machine_id": "m1",
    }
    defaults.update(overrides)
    return PodApiResponse(**defaults)


def _make_pod(
    name: str = "test-pod", image: str = "img:latest", gpu: str | None = "NVIDIA A100"
) -> Pod:
    return Pod(name=name, image=image, gpu=gpu)


# ---------------------------------------------------------------------------
# TestPodTracker
# ---------------------------------------------------------------------------


class TestPodTracker:
    def test_save_and_load(self, tmp_path: Path) -> None:
        tracker = PodTracker(tmp_path)
        pod = _make_pod()
        pod._pod_id = "pod-abc"
        pod._state = PodState.RUNNING
        pod._address = "http://1.2.3.4:8000"

        tracker.save(pod)
        entry = tracker.load("test-pod")

        assert entry is not None
        assert entry.name == "test-pod"
        assert entry.pod_id == "pod-abc"
        assert entry.image == "img:latest"
        assert entry.gpu == "NVIDIA A100"
        assert entry.state == "running"
        assert entry.address == "http://1.2.3.4:8000"

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        tracker = PodTracker(tmp_path)
        assert tracker.load("no-such-pod") is None

    def test_load_all_empty(self, tmp_path: Path) -> None:
        tracker = PodTracker(tmp_path)
        assert tracker.load_all() == []

    def test_load_all_multiple(self, tmp_path: Path) -> None:
        tracker = PodTracker(tmp_path)

        pod_a = _make_pod(name="pod-a")
        pod_a._pod_id = "id-a"
        pod_a._state = PodState.RUNNING
        tracker.save(pod_a)

        pod_b = _make_pod(name="pod-b")
        pod_b._pod_id = "id-b"
        pod_b._state = PodState.STOPPED
        tracker.save(pod_b)

        entries = tracker.load_all()
        assert len(entries) == 2
        names = {e.name for e in entries}
        assert names == {"pod-a", "pod-b"}

    def test_remove(self, tmp_path: Path) -> None:
        tracker = PodTracker(tmp_path)
        pod = _make_pod()
        pod._pod_id = "pod-1"
        pod._state = PodState.RUNNING
        tracker.save(pod)

        tracker.remove("test-pod")
        assert tracker.load("test-pod") is None

    def test_save_overwrites(self, tmp_path: Path) -> None:
        tracker = PodTracker(tmp_path)
        pod = _make_pod()
        pod._pod_id = "pod-1"
        pod._state = PodState.RUNNING
        pod._address = "http://old:8000"
        tracker.save(pod)

        pod._address = "http://new:9000"
        tracker.save(pod)

        entry = tracker.load("test-pod")
        assert entry is not None
        assert entry.address == "http://new:9000"


# ---------------------------------------------------------------------------
# TestPodLifecycleManager
# ---------------------------------------------------------------------------


class TestPodLifecycleManager:
    def _make_manager(self, tmp_path: Path) -> tuple[PodLifecycleManager, AsyncMock]:
        api = AsyncMock()
        tracker = PodTracker(tmp_path)
        manager = PodLifecycleManager(api, tracker)
        return manager, api

    @pytest.mark.asyncio
    async def test_provision(self, tmp_path: Path) -> None:
        manager, api = self._make_manager(tmp_path)
        api.create.return_value = _make_api_response()
        pod = _make_pod()

        result = await manager.provision(pod)

        api.create.assert_awaited_once_with(pod)
        assert result._state == PodState.RUNNING
        assert result._pod_id == "pod-1"
        assert result._address == "http://1.2.3.4:43215"

    @pytest.mark.asyncio
    async def test_stop(self, tmp_path: Path) -> None:
        manager, api = self._make_manager(tmp_path)
        pod = _make_pod()
        pod._pod_id = "pod-1"
        pod._state = PodState.RUNNING

        result = await manager.stop(pod)

        api.stop.assert_awaited_once_with("pod-1")
        assert result._state == PodState.STOPPED
        assert result._address is None

    @pytest.mark.asyncio
    async def test_resume_passes_gpu_count(self, tmp_path: Path) -> None:
        manager, api = self._make_manager(tmp_path)
        api.resume.return_value = _make_api_response()
        pod = _make_pod()
        pod._pod_id = "pod-1"
        pod._state = PodState.STOPPED

        result = await manager.resume(pod)

        api.resume.assert_awaited_once_with("pod-1", pod.config.gpu_count)
        assert result._state == PodState.RUNNING

    @pytest.mark.asyncio
    async def test_terminate(self, tmp_path: Path) -> None:
        manager, api = self._make_manager(tmp_path)
        pod = _make_pod()
        pod._pod_id = "pod-1"
        pod._state = PodState.RUNNING

        result = await manager.terminate(pod)

        api.terminate.assert_awaited_once_with("pod-1")
        assert result._state == PodState.TERMINATED
        assert result._address is None

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self, tmp_path: Path) -> None:
        manager, _api = self._make_manager(tmp_path)
        pod = _make_pod()
        # Pod starts in DEFINED, cannot go straight to STOPPING
        with pytest.raises(InvalidPodStateError):
            await manager.stop(pod)

    @pytest.mark.asyncio
    async def test_sync_state(self, tmp_path: Path) -> None:
        manager, api = self._make_manager(tmp_path)
        api.get.return_value = _make_api_response(desired_status="EXITED", ports=None)
        pod = _make_pod()
        pod._pod_id = "pod-1"
        pod._state = PodState.RUNNING

        result = await manager.sync_state(pod)

        api.get.assert_awaited_once_with("pod-1")
        assert result._state == PodState.STOPPED
        assert result._address is None


# ---------------------------------------------------------------------------
# TestPodDrift
# ---------------------------------------------------------------------------


class TestPodDrift:
    def test_no_drift(self) -> None:
        pod = _make_pod()
        entry = PodTrackerEntry(
            name=pod.name,
            pod_id="pod-1",
            image=pod.image,
            gpu=str(pod.gpu),
            state="running",
            address="http://1.2.3.4:8000",
            config_hash=pod.config_hash,
            created_at="2026-01-01T00:00:00+00:00",
        )
        assert detect_pod_drift(pod, entry) is None

    def test_image_changed(self) -> None:
        pod = _make_pod(image="new-image:v2")
        entry = PodTrackerEntry(
            name=pod.name,
            pod_id="pod-1",
            image="old-image:v1",
            gpu=str(pod.gpu),
            state="running",
            address=None,
            config_hash=pod.config_hash,
            created_at="2026-01-01T00:00:00+00:00",
        )
        drift = detect_pod_drift(pod, entry)
        assert drift is not None
        assert drift.image_changed is True
        assert drift.requires_rebuild is True

    def test_env_changed_no_rebuild(self) -> None:
        pod = _make_pod()
        pod.env["NEW_VAR"] = "value"
        # Entry has the old config hash (before env was added)
        old_pod = _make_pod()
        entry = PodTrackerEntry(
            name=pod.name,
            pod_id="pod-1",
            image=pod.image,
            gpu=str(pod.gpu),
            state="running",
            address=None,
            config_hash=old_pod.config_hash,
            created_at="2026-01-01T00:00:00+00:00",
        )
        drift = detect_pod_drift(pod, entry)
        assert drift is not None
        assert drift.env_changed is True
        assert drift.requires_rebuild is False
