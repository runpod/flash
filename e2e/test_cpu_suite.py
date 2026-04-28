"""Shared CPU E2E suite — session-scoped endpoint pool.

Provisions four CPU endpoints once at session start and shares them across
all test classes. Undeploys at session teardown via sweep_endpoints.

Workers:
  qb_endpoint   — QB function: echo(msg) → dict
  deps_endpoint — QB with numpy/pandas deps
  class_endpoint — QB with a class-based handler
  lb_endpoint   — LB with /health and /echo routes
"""

import concurrent.futures
import shutil
import uuid
from typing import Generator

import httpx
import pytest
import runpod

from conftest import _REAL_API_KEY, sweep_endpoints
from provisioner import provision

# ---------------------------------------------------------------------------
# Worker code templates
# ---------------------------------------------------------------------------


def _qb_echo_worker(name: str) -> str:
    return f'''\
from runpod_flash import Endpoint


@Endpoint(name="{name}", cpu="cpu3c-1-2", workers=(0, 1))
async def echo(msg: str = "") -> dict:
    return {{"echo": msg}}
'''


def _qb_deps_worker(name: str) -> str:
    return f'''\
import numpy as np
import pandas as pd
from runpod_flash import Endpoint


@Endpoint(name="{name}", cpu="cpu3c-1-2", workers=(0, 1))
async def compute(x: float = 1.0) -> dict:
    arr = np.array([x, x * 2, x * 3])
    df = pd.DataFrame({{"vals": arr}})
    return {{"mean": float(arr.mean()), "sum": float(df["vals"].sum())}}
'''


def _qb_class_worker(name: str) -> str:
    return f'''\
from runpod_flash import Endpoint


@Endpoint(name="{name}", cpu="cpu3c-1-2", workers=(0, 1))
class Greeter:
    def greet(self, name: str = "world") -> dict:
        return {{"greeting": f"Hello, {{name}}!"}}
'''


def _lb_worker(name: str) -> str:
    return f'''\
from runpod_flash import Endpoint

api = Endpoint(name="{name}", cpu="cpu3c-1-2", workers=(1, 2))


@api.get("/health")
async def health() -> dict:
    return {{"status": "healthy"}}


@api.post("/echo")
async def echo(data: dict) -> dict:
    return {{"echo": data}}
'''


# ---------------------------------------------------------------------------
# Session fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _session_api_key() -> Generator[str, None, None]:
    if not _REAL_API_KEY:
        pytest.skip("No credentials available — skipping E2E test")
    runpod.api_key = _REAL_API_KEY
    yield _REAL_API_KEY
    sweep_endpoints(_REAL_API_KEY)


def _provision_named(
    code_fn,
    base_name: str,
    api_key: str,
    extra_deps: list[str] | None = None,
):
    name = f"{base_name}-{uuid.uuid4().hex[:8]}"
    return provision(code_fn(name), name=name, api_key=api_key, extra_deps=extra_deps)


@pytest.fixture(scope="session")
def qb_endpoint(_session_api_key: str) -> Generator[str, None, None]:
    endpoint_id, tmp_dir = _provision_named(
        _qb_echo_worker, "flash-qa-qb", _session_api_key
    )
    yield endpoint_id
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def deps_endpoint(_session_api_key: str) -> Generator[str, None, None]:
    endpoint_id, tmp_dir = _provision_named(
        _qb_deps_worker,
        "flash-qa-deps",
        _session_api_key,
        extra_deps=["numpy", "pandas"],
    )
    yield endpoint_id
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def class_endpoint(_session_api_key: str) -> Generator[str, None, None]:
    endpoint_id, tmp_dir = _provision_named(
        _qb_class_worker, "flash-qa-class", _session_api_key
    )
    yield endpoint_id
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def lb_endpoint(_session_api_key: str) -> Generator[str, None, None]:
    endpoint_id, tmp_dir = _provision_named(_lb_worker, "flash-qa-lb", _session_api_key)
    yield endpoint_id
    shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lb_get(endpoint_id: str, path: str, api_key: str, timeout: float = 120.0):
    url = f"https://{endpoint_id}.api.runpod.ai{path}"
    resp = httpx.get(
        url, headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout
    )
    resp.raise_for_status()
    return resp.json()


def _lb_post(
    endpoint_id: str, path: str, payload: dict, api_key: str, timeout: float = 120.0
):
    url = f"https://{endpoint_id}.api.runpod.ai{path}"
    resp = httpx.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def _lb_url(endpoint_id: str, path: str) -> str:
    return f"https://{endpoint_id}.api.runpod.ai{path}"


# ---------------------------------------------------------------------------
# QB function tests
# ---------------------------------------------------------------------------


class TestCpuQBFunction:
    """QB function endpoint: echo(msg) → dict."""

    def test_smoke(self, qb_endpoint: str) -> None:
        out = runpod.Endpoint(qb_endpoint).run_sync({"msg": "smoke"}, timeout=180)
        assert out is not None
        assert out.get("echo") == "smoke"

    def test_empty_string(self, qb_endpoint: str) -> None:
        out = runpod.Endpoint(qb_endpoint).run_sync({"msg": ""}, timeout=60)
        assert out is not None
        assert out.get("echo") == ""

    def test_unicode(self, qb_endpoint: str) -> None:
        msg = "héllo wörld 🔥"
        out = runpod.Endpoint(qb_endpoint).run_sync({"msg": msg}, timeout=60)
        assert out is not None
        assert out.get("echo") == msg


# ---------------------------------------------------------------------------
# Concurrent invocations
# ---------------------------------------------------------------------------


class TestCpuQBFunctionConcurrent:
    """10 parallel invocations against a single QB endpoint."""

    def test_ten_parallel_calls(self, qb_endpoint: str) -> None:
        ep = runpod.Endpoint(qb_endpoint)

        def call(i: int):
            return ep.run_sync({"msg": f"call-{i}"}, timeout=60)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(call, i) for i in range(10)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == 10
        assert all(r is not None for r in results)
        echoed = {r["echo"] for r in results}
        assert echoed == {f"call-{i}" for i in range(10)}, (
            f"Echo values don't match sent messages: {echoed}"
        )


# ---------------------------------------------------------------------------
# Dependency import test
# ---------------------------------------------------------------------------


class TestCpuQBFunctionDeps:
    """QB endpoint that imports numpy and pandas."""

    def test_numpy_pandas_available(self, deps_endpoint: str) -> None:
        out = runpod.Endpoint(deps_endpoint).run_sync({"x": 2.0}, timeout=180)
        assert out is not None
        assert out.get("mean") == pytest.approx(4.0)
        assert out.get("sum") == pytest.approx(12.0)


# ---------------------------------------------------------------------------
# Class-based QB handler
# ---------------------------------------------------------------------------


class TestCpuQBClass:
    """QB endpoint with a class-based handler (single-method, auto-dispatched)."""

    def test_single_method_invocation(self, class_endpoint: str) -> None:
        out = runpod.Endpoint(class_endpoint).run_sync({"name": "tester"}, timeout=180)
        assert out is not None
        assert out.get("greeting") == "Hello, tester!"


# ---------------------------------------------------------------------------
# LB endpoint tests
# ---------------------------------------------------------------------------


class TestCpuLBEndpoint:
    """LB endpoint: custom GET and POST routes."""

    def test_get_health(self, lb_endpoint: str, _session_api_key: str) -> None:
        out = _lb_get(lb_endpoint, "/health", _session_api_key)
        assert out is not None
        assert out.get("status") == "healthy"

    def test_post_echo(self, lb_endpoint: str, _session_api_key: str) -> None:
        payload = {"key": "value", "num": 42}
        # FastAPI wraps named body parameters: {"data": <value>}
        out = _lb_post(lb_endpoint, "/echo", {"data": payload}, _session_api_key)
        assert out is not None
        assert out.get("echo") == payload

    def test_unauthorized_request(self, lb_endpoint: str) -> None:
        """LB endpoint must reject requests with no Bearer token."""
        resp = httpx.get(_lb_url(lb_endpoint, "/health"), timeout=30.0)
        assert resp.status_code in (401, 403), (
            f"Expected 401 or 403 for unauthenticated request, got {resp.status_code}"
        )
