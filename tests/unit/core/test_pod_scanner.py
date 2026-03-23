"""Tests for PodScanner module-level pod discovery."""

from __future__ import annotations

from types import ModuleType

from runpod_flash.core.pod_scanner import PodScanner
from runpod_flash.core.resources.pod import Pod


def _make_module(**attrs: object) -> ModuleType:
    """Create a synthetic module with the given attributes."""
    mod = ModuleType("fake_app")
    for name, value in attrs.items():
        setattr(mod, name, value)
    return mod


class TestPodScanner:
    def test_finds_module_level_pods(self) -> None:
        pod_a = Pod(name="worker-a", image="img-a")
        pod_b = Pod(name="worker-b", image="img-b", gpu="NVIDIA A100")
        mod = _make_module(
            worker_a=pod_a,
            worker_b=pod_b,
            some_string="not a pod",
            some_int=42,
        )

        scanner = PodScanner()
        pods = scanner.scan(mod)

        assert len(pods) == 2
        names = {p.name for p in pods}
        assert names == {"worker-a", "worker-b"}

    def test_returns_empty_when_no_pods(self) -> None:
        mod = _make_module(config={"key": "value"}, flag=True)

        scanner = PodScanner()
        pods = scanner.scan(mod)

        assert pods == []

    def test_handles_module_with_single_pod(self) -> None:
        pod = Pod(name="solo", image="solo-img")
        mod = _make_module(my_pod=pod)

        scanner = PodScanner()
        pods = scanner.scan(mod)

        assert len(pods) == 1
        assert pods[0].name == "solo"
