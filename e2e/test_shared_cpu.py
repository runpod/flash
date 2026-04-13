"""CPU E2E tests against session-scoped shared endpoints.

All tests in this file share endpoints provisioned once at session start.
No deploy/undeploy inside individual tests — that happens in conftest.provisioned.

Covered scenarios:
  E2E-002  CPU QB function: basic invocation, input variants
  E2E-004  CPU QB function with dependencies (numpy, pandas)
  E2E-006  CPU QB class-based worker
  E2E-008  CPU load-balanced endpoint (multi-route)
  E2E-018  Concurrent invocations
"""

import concurrent.futures

import pytest
import runpod


# ---------------------------------------------------------------------------
# QB function — basic inputs
# ---------------------------------------------------------------------------


class TestCpuQBFunction:
    """E2E-002: CPU QB function handles varied inputs correctly."""

    def test_smoke(self, provisioned: dict, api_key: str) -> None:
        if "cpu_fn" not in provisioned:
            pytest.skip("cpu_fn endpoint failed to provision")
        runpod.api_key = api_key
        output = runpod.Endpoint(provisioned["cpu_fn"]).run_sync(
            {"msg": "smoke"}, timeout=180
        )
        assert output is not None
        assert output.get("echo") == "smoke"
        assert output.get("status") == "ok"

    def test_empty_string(self, provisioned: dict, api_key: str) -> None:
        if "cpu_fn" not in provisioned:
            pytest.skip("cpu_fn endpoint failed to provision")
        runpod.api_key = api_key
        output = runpod.Endpoint(provisioned["cpu_fn"]).run_sync(
            {"msg": ""}, timeout=60
        )
        assert output is not None
        assert output.get("echo") == ""

    def test_unicode(self, provisioned: dict, api_key: str) -> None:
        if "cpu_fn" not in provisioned:
            pytest.skip("cpu_fn endpoint failed to provision")
        runpod.api_key = api_key
        output = runpod.Endpoint(provisioned["cpu_fn"]).run_sync(
            {"msg": "héllo wörld 🚀"}, timeout=60
        )
        assert output is not None
        assert output.get("echo") == "héllo wörld 🚀"

    @pytest.mark.xfail(
        reason="AE-2744 open: empty dict input causes ~42s hang in deployed workers",
        strict=False,
    )
    def test_default_arg(self, provisioned: dict, api_key: str) -> None:
        """No msg key — worker should use default empty string."""
        if "cpu_fn" not in provisioned:
            pytest.skip("cpu_fn endpoint failed to provision")
        runpod.api_key = api_key
        output = runpod.Endpoint(provisioned["cpu_fn"]).run_sync({}, timeout=60)
        assert output is not None
        assert output.get("echo") == ""


# ---------------------------------------------------------------------------
# QB function — concurrent
# ---------------------------------------------------------------------------

_CONCURRENCY = 10


def _invoke(endpoint_id: str, index: int) -> tuple[int, object]:
    ep = runpod.Endpoint(endpoint_id)
    output = ep.run_sync({"msg": f"job-{index}"}, timeout=120)
    return index, output


class TestCpuQBFunctionConcurrent:
    """E2E-018: 10 parallel run_sync calls all complete with correct output."""

    def test_ten_parallel_calls(self, provisioned: dict, api_key: str) -> None:
        if "cpu_fn" not in provisioned:
            pytest.skip("cpu_fn endpoint failed to provision")
        runpod.api_key = api_key
        endpoint_id = provisioned["cpu_fn"]

        with concurrent.futures.ThreadPoolExecutor(max_workers=_CONCURRENCY) as pool:
            futures = [pool.submit(_invoke, endpoint_id, i) for i in range(_CONCURRENCY)]
            results: dict[int, object] = {}
            errors: list[str] = []
            for future in concurrent.futures.as_completed(futures):
                try:
                    idx, output = future.result()
                    results[idx] = output
                except Exception as exc:
                    errors.append(str(exc))

        assert not errors, f"Jobs raised exceptions: {errors}"
        assert len(results) == _CONCURRENCY

        for i in range(_CONCURRENCY):
            out = results[i]
            assert out is not None, f"Job {i} returned None"
            assert out.get("echo") == f"job-{i}", f"Job {i} wrong output: {out}"


# ---------------------------------------------------------------------------
# QB function with dependencies
# ---------------------------------------------------------------------------


class TestCpuQBFunctionDeps:
    """E2E-004: numpy and pandas are importable and usable inside the worker."""

    def test_numpy_pandas_available(self, provisioned: dict, api_key: str) -> None:
        if "cpu_deps" not in provisioned:
            pytest.skip("cpu_deps endpoint failed to provision")
        runpod.api_key = api_key
        output = runpod.Endpoint(provisioned["cpu_deps"]).run_sync(
            {"x": 3.0}, timeout=180
        )
        assert output is not None
        # 3.0 + 6.0 + 9.0 = 18.0
        assert abs(output.get("sum", 0) - 18.0) < 1e-6, f"Unexpected sum: {output}"
        assert "dtype" in output, f"Missing dtype in output: {output}"


# ---------------------------------------------------------------------------
# QB class-based worker
# ---------------------------------------------------------------------------


class TestCpuQBClass:
    """E2E-006: class-based QB endpoint (AE-2435 regression guard)."""

    def test_single_method_invocation(self, provisioned: dict, api_key: str) -> None:
        if "cpu_cls" not in provisioned:
            pytest.skip("cpu_cls endpoint failed to provision")
        runpod.api_key = api_key
        output = runpod.Endpoint(provisioned["cpu_cls"]).run_sync(
            {"x": 5}, timeout=180
        )
        assert output is not None
        assert output.get("result") == 15, f"Expected 15 (5×3), got: {output}"
        assert output.get("status") == "ok"


# ---------------------------------------------------------------------------
# CPU load-balanced endpoint
# ---------------------------------------------------------------------------


class TestCpuLBEndpoint:
    """E2E-008: CPU LB endpoint exposes multiple HTTP routes."""

    def test_ping(self, provisioned: dict, api_key: str) -> None:
        from conftest import call_lb
        if "cpu_lb" not in provisioned:
            pytest.skip("cpu_lb endpoint failed to provision")
        ping = call_lb(provisioned["cpu_lb"], api_key, "/ping", method="GET")
        print(f"/ping: {ping}")

    def test_post_echo(self, provisioned: dict, api_key: str) -> None:
        from conftest import call_lb
        if "cpu_lb" not in provisioned:
            pytest.skip("cpu_lb endpoint failed to provision")
        out = call_lb(
            provisioned["cpu_lb"], api_key, "/echo",
            method="POST", json_data={"msg": "hello"}
        )
        assert out is not None
        assert out.get("echo") == "hello"
        assert out.get("status") == "ok"

    def test_get_health(self, provisioned: dict, api_key: str) -> None:
        from conftest import call_lb
        if "cpu_lb" not in provisioned:
            pytest.skip("cpu_lb endpoint failed to provision")
        out = call_lb(provisioned["cpu_lb"], api_key, "/health", method="GET")
        assert out is not None
        assert out.get("status") == "healthy"
