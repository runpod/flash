"""Tests for pod integration in flash deploy."""

from runpod_flash.core.resources.pod import Pod
from runpod_flash.core.resources.pod_lifecycle import (
    PodDrift,
    PodTrackerEntry,
    detect_pod_drift,
)


class TestPodDrift:
    def test_no_drift(self):
        pod = Pod("test", image="img:v1")
        entry = PodTrackerEntry(
            name="test",
            pod_id="p1",
            image="img:v1",
            gpu=None,
            state="running",
            address="https://x",
            config_hash=pod.config_hash,
            created_at="2026-01-01",
        )
        assert detect_pod_drift(pod, entry) is None

    def test_image_changed(self):
        pod = Pod("test", image="img:v2")
        entry = PodTrackerEntry(
            name="test",
            pod_id="p1",
            image="img:v1",
            gpu=None,
            state="running",
            address="https://x",
            config_hash="old",
            created_at="2026-01-01",
        )
        drift = detect_pod_drift(pod, entry)
        assert drift is not None
        assert drift.image_changed is True
        assert drift.requires_rebuild is True

    def test_env_changed_no_rebuild(self):
        pod = Pod("test", image="img:v1", env={"NEW": "val"})
        entry = PodTrackerEntry(
            name="test",
            pod_id="p1",
            image="img:v1",
            gpu=None,
            state="running",
            address="https://x",
            config_hash="old",
            created_at="2026-01-01",
        )
        drift = detect_pod_drift(pod, entry)
        assert drift is not None
        assert drift.image_changed is False
        assert drift.requires_rebuild is False

    def test_drift_dataclass_fields(self):
        drift = PodDrift(
            image_changed=True,
            env_changed=False,
            gpu_changed=True,
            config_changed=True,
        )
        assert drift.requires_rebuild is True

        drift2 = PodDrift(
            image_changed=False,
            env_changed=True,
            gpu_changed=False,
            config_changed=True,
        )
        assert drift2.requires_rebuild is False
