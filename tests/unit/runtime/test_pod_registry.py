"""Unit tests for PodRegistry service discovery."""

import json
from unittest.mock import AsyncMock

import pytest

from runpod_flash.core.api.pod_client import PodApiResponse, PortMapping
from runpod_flash.core.exceptions import PodNotFoundError, PodNotRunningError
from runpod_flash.core.resources.pod_lifecycle import PodTracker
from runpod_flash.runtime.pod_registry import PodRegistry


def _write_pods_json(flash_dir, entries: dict) -> None:
    """Write pods.json directly for test setup."""
    pods_file = flash_dir / "pods.json"
    pods_file.write_text(json.dumps(entries))


def _make_api_response(
    *,
    pod_id: str = "pod-abc123",
    name: str = "my-pod",
    desired_status: str = "RUNNING",
    host_ip: str = "10.0.0.1",
    host_port: int = 8080,
) -> PodApiResponse:
    """Build a PodApiResponse for testing."""
    return PodApiResponse(
        pod_id=pod_id,
        name=name,
        desired_status=desired_status,
        image_name="my-image:latest",
        gpu_display_name="RTX 4090",
        public_ip=host_ip,
        ports={
            "8080": PortMapping(host_ip=host_ip, host_port=host_port, protocol="tcp")
        },
        cost_per_hr=0.5,
        uptime_seconds=3600,
        machine_id="machine-1",
    )


@pytest.fixture()
def flash_dir(tmp_path):
    """Create a .flash directory with a tracked pod."""
    _write_pods_json(
        tmp_path,
        {
            "my-pod": {
                "name": "my-pod",
                "pod_id": "pod-abc123",
                "image": "my-image:latest",
                "gpu": "RTX 4090",
                "state": "running",
                "address": "http://10.0.0.1:8080",
                "config_hash": "abc",
                "created_at": "2026-01-01T00:00:00",
            }
        },
    )
    return tmp_path


class TestPodRegistry:
    """Tests for PodRegistry.resolve()."""

    @pytest.mark.asyncio()
    async def test_resolve_running_pod(self, flash_dir):
        """Resolve returns base URL for a running pod."""
        tracker = PodTracker(flash_dir)
        api_client = AsyncMock()
        api_client.get.return_value = _make_api_response(desired_status="RUNNING")

        registry = PodRegistry(tracker, api_client)
        address = await registry.resolve("my-pod")

        assert address == "https://10.0.0.1:8080"
        api_client.get.assert_awaited_once_with("pod-abc123")

    @pytest.mark.asyncio()
    async def test_resolve_stopped_pod_raises(self, flash_dir):
        """Resolve raises PodNotRunningError for a stopped pod."""
        tracker = PodTracker(flash_dir)
        api_client = AsyncMock()
        api_client.get.return_value = _make_api_response(desired_status="EXITED")

        registry = PodRegistry(tracker, api_client)

        with pytest.raises(PodNotRunningError) as exc_info:
            await registry.resolve("my-pod")

        assert exc_info.value.pod_name == "my-pod"

    @pytest.mark.asyncio()
    async def test_resolve_unknown_pod_raises(self, flash_dir):
        """Resolve raises PodNotFoundError for an untracked pod."""
        tracker = PodTracker(flash_dir)
        api_client = AsyncMock()

        registry = PodRegistry(tracker, api_client)

        with pytest.raises(PodNotFoundError) as exc_info:
            await registry.resolve("nonexistent-pod")

        assert exc_info.value.pod_name == "nonexistent-pod"
        api_client.get.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_cache_avoids_repeated_api_calls(self, flash_dir):
        """Second resolve uses cache, no additional API call."""
        tracker = PodTracker(flash_dir)
        api_client = AsyncMock()
        api_client.get.return_value = _make_api_response(desired_status="RUNNING")

        registry = PodRegistry(tracker, api_client)

        first = await registry.resolve("my-pod")
        second = await registry.resolve("my-pod")

        assert first == second == "https://10.0.0.1:8080"
        api_client.get.assert_awaited_once()
