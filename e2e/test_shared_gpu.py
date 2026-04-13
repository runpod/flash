"""GPU E2E tests against session-scoped shared endpoints (GpuGroup.ANY).

All tests share endpoints provisioned once at session start.
Extended timeouts account for GPU cold-start latency (~5-10 min).

Covered scenarios:
  GPU QB function
  GPU QB class-based worker
  GPU load-balanced endpoint (multi-route)
"""

import pytest
import runpod


# ---------------------------------------------------------------------------
# GPU QB function
# ---------------------------------------------------------------------------


class TestGpuQBFunction:
    """GPU QB function endpoint deploys and responds correctly."""

    def test_basic_invocation(self, provisioned: dict, api_key: str) -> None:
        if "gpu_fn" not in provisioned:
            pytest.skip("gpu_fn endpoint failed to provision (GPU unavailable?)")
        runpod.api_key = api_key
        output = runpod.Endpoint(provisioned["gpu_fn"]).run_sync(
            {"msg": "gpu-smoke"}, timeout=600
        )
        assert output is not None
        assert output.get("hello") == "gpu-smoke"
        assert output.get("status") == "ok"

    def test_empty_input(self, provisioned: dict, api_key: str) -> None:
        if "gpu_fn" not in provisioned:
            pytest.skip("gpu_fn endpoint failed to provision")
        runpod.api_key = api_key
        output = runpod.Endpoint(provisioned["gpu_fn"]).run_sync(
            {"msg": ""}, timeout=120
        )
        assert output is not None
        assert output.get("hello") == ""


# ---------------------------------------------------------------------------
# GPU QB class-based worker
# ---------------------------------------------------------------------------


class TestGpuQBClass:
    """GPU class-based QB endpoint deploys and responds correctly."""

    def test_single_method_invocation(self, provisioned: dict, api_key: str) -> None:
        if "gpu_cls" not in provisioned:
            pytest.skip("gpu_cls endpoint failed to provision (GPU unavailable?)")
        runpod.api_key = api_key
        output = runpod.Endpoint(provisioned["gpu_cls"]).run_sync(
            {"x": 5.0}, timeout=600
        )
        assert output is not None
        assert output.get("result") == 20.0, f"Expected 20.0 (5.0×4), got: {output}"
        assert output.get("status") == "ok"


# ---------------------------------------------------------------------------
# GPU load-balanced endpoint
# ---------------------------------------------------------------------------


class TestGpuLBEndpoint:
    """GPU LB endpoint exposes multiple HTTP routes correctly."""

    def test_ping(self, provisioned: dict, api_key: str) -> None:
        from conftest import call_lb
        if "gpu_lb" not in provisioned:
            pytest.skip("gpu_lb endpoint failed to provision")
        ping = call_lb(provisioned["gpu_lb"], api_key, "/ping", method="GET", timeout=60)
        print(f"/ping: {ping}")

    def test_post_predict(self, provisioned: dict, api_key: str) -> None:
        from conftest import call_lb
        if "gpu_lb" not in provisioned:
            pytest.skip("gpu_lb endpoint failed to provision")
        out = call_lb(
            provisioned["gpu_lb"], api_key, "/predict",
            method="POST", json_data={"value": 7.0}, timeout=600
        )
        assert out is not None
        assert out.get("prediction") == 14.0, f"Unexpected prediction: {out}"
        assert out.get("status") == "ok"

    def test_get_health(self, provisioned: dict, api_key: str) -> None:
        from conftest import call_lb
        if "gpu_lb" not in provisioned:
            pytest.skip("gpu_lb endpoint failed to provision")
        out = call_lb(
            provisioned["gpu_lb"], api_key, "/health", method="GET", timeout=60
        )
        assert out is not None
        assert out.get("status") == "healthy"
