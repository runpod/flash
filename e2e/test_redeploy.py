"""Redeploy E2E tests — rolling release and worker recycle verification.

Each test manages its own deploy/undeploy. No session-scoped fixtures.

Excluded from this file (known platform failures, tracked in Linear):
  TestRedeployAlwaysOn, TestRedeployNoDowntime, TestRedeployInFlight
  → single-slot always-on (workers=(1,1)) recycle not working (AE-2940/2941/2942)
  → see test_redeploy_always_on.py
"""

import concurrent.futures
import os
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import runpod

from conftest import endpoint_id_from_state, sweep_endpoints
from provisioner import flash_dep

_RECYCLE_TIMEOUT = 300  # seconds — CPU worker recycle observed at >120s in practice
_IDLE_WAIT = 60  # seconds without requests after deploy so the worker can drain idle and trigger recycle

# ---------------------------------------------------------------------------
# Worker code templates
# ---------------------------------------------------------------------------

_BASE_PYPROJECT = """\
[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = ["{dep}"]
"""


def _pyproject(name: str) -> str:
    return _BASE_PYPROJECT.format(name=name, dep=flash_dep())


def _versioned_worker(name: str, version: str, workers: str = "workers=(0, 1)") -> str:
    """QB worker that returns version and RUNPOD_POD_ID for recycle verification."""
    return f'''\
import os
from runpod_flash import Endpoint

@Endpoint(name="{name}", cpu="cpu3c-1-2", {workers})
async def echo(msg: str = "") -> dict:
    return {{
        "version": "{version}",
        "worker_id": os.environ.get("RUNPOD_POD_ID", "unknown"),
        "msg": msg,
    }}
'''


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _deploy(code: str, name: str, tmp_path: Path, env: dict, label: str = "") -> None:
    (tmp_path / "worker.py").write_text(code)
    r = subprocess.run(
        ["uv", "run", "flash", "deploy"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    tag = f"{label} " if label else ""
    assert r.returncode == 0, f"{tag}deploy failed:\n{r.stdout}\n{r.stderr}"


def _undeploy(name: str, cwd: Path, env: dict) -> None:
    try:
        subprocess.run(
            ["uv", "run", "flash", "undeploy", name, "--force"],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        print(f"WARNING: undeploy of {name} timed out after 60s")


def poll_until_version(
    endpoint_id: str,
    api_key: str,
    target_version: str,
    timeout: int,
    interval: int = 5,
) -> tuple[float, dict]:
    """Poll endpoint until it returns target_version or timeout elapses.

    Returns (elapsed_seconds_since_first_call, first_matching_response).
    Raises TimeoutError if timeout elapses before target_version is seen.
    """
    ep = runpod.Endpoint(endpoint_id)
    deadline = time.monotonic() + timeout
    start = time.monotonic()
    while True:
        try:
            out = ep.run_sync({"msg": "poll"}, timeout=60)
            if out and out.get("version") == target_version:
                return time.monotonic() - start, out
        except Exception as exc:
            print(f"[poll_until_version] {exc}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"Version {target_version!r} not seen on {endpoint_id!r} within {timeout}s"
            )
        time.sleep(min(interval, remaining))


@contextmanager
def continuous_caller(
    endpoint_id: str,
    api_key: str,
    interval: float = 1.0,
) -> Generator[list, None, None]:
    """Call endpoint at regular intervals in a background thread.

    Yields a results list populated as calls complete:
        [(timestamp_float, response_or_None, error_or_None), ...]

    Stops and joins when the context exits.
    """
    results: list[tuple[float, dict | None, Exception | None]] = []
    stop = threading.Event()

    def _loop() -> None:
        ep = runpod.Endpoint(endpoint_id)
        while not stop.is_set():
            ts = time.monotonic()
            try:
                out = ep.run_sync({"msg": "continuous"}, timeout=60)
                results.append((ts, out, None))
            except Exception as exc:
                results.append((ts, None, exc))
            time.sleep(interval)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    try:
        yield results
    finally:
        stop.set()
        t.join(timeout=15)


# ---------------------------------------------------------------------------
# Scale-to-zero: new code live after redeploy
# ---------------------------------------------------------------------------


class TestRedeployScaleToZero:
    """workers=(0,1), CPU: v2 code is live after redeploy; worker ID changes."""

    def test_new_code_live_after_redeploy(self, tmp_path: Path, api_key: str) -> None:
        name = f"flash-qa-rdp-sto-{uuid.uuid4().hex[:8]}"
        env = os.environ.copy()
        (tmp_path / "pyproject.toml").write_text(_pyproject(name))
        runpod.api_key = api_key

        try:
            _deploy(_versioned_worker(name, "v1"), name, tmp_path, env, "v1")
            endpoint_id = endpoint_id_from_state(tmp_path)

            out_v1 = runpod.Endpoint(endpoint_id).run_sync(
                {"msg": "check"}, timeout=180
            )
            assert out_v1 and out_v1.get("version") == "v1"
            worker_id_v1 = out_v1["worker_id"]

            _deploy(_versioned_worker(name, "v2"), name, tmp_path, env, "v2")
            time.sleep(_IDLE_WAIT)  # let worker drain idle so the recycle can fire

            elapsed, out_v2 = poll_until_version(
                endpoint_id, api_key, "v2", timeout=_RECYCLE_TIMEOUT, interval=30
            )
            print(f"[scale-to-zero] v2 live {elapsed:.1f}s after idle wait")

            assert out_v2["version"] == "v2"
            assert out_v2["worker_id"] != worker_id_v1, (
                f"worker_id unchanged after redeploy: {worker_id_v1!r}"
            )
        finally:
            _undeploy(name, tmp_path, env)
            sweep_endpoints(api_key)


# ---------------------------------------------------------------------------
# Multi-worker scale-to-zero: full cutover
# ---------------------------------------------------------------------------


class TestRedeployMultiWorker:
    """workers=(0,4), CPU: multiple concurrent workers all serve v2 after redeploy."""

    def test_full_cutover_multi_worker(self, tmp_path: Path, api_key: str) -> None:
        name = f"flash-qa-rdp-mw-{uuid.uuid4().hex[:8]}"
        env = os.environ.copy()
        (tmp_path / "pyproject.toml").write_text(_pyproject(name))
        runpod.api_key = api_key

        try:
            _deploy(
                _versioned_worker(name, "v1", "workers=(0, 4)"),
                name,
                tmp_path,
                env,
                "v1",
            )
            endpoint_id = endpoint_id_from_state(tmp_path)

            # Spin up multiple workers concurrently to populate the worker pool
            ep = runpod.Endpoint(endpoint_id)
            worker_ids_v1: set[str] = set()
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                futs = [
                    pool.submit(lambda: ep.run_sync({"msg": "spin-up"}, timeout=120))
                    for _ in range(8)
                ]
                for fut in concurrent.futures.as_completed(futs):
                    out = fut.result()
                    if out:
                        worker_ids_v1.add(out.get("worker_id", "unknown"))
            print(f"[multi-worker] v1 worker IDs seen: {worker_ids_v1}")

            _deploy(
                _versioned_worker(name, "v2", "workers=(0, 4)"),
                name,
                tmp_path,
                env,
                "v2",
            )
            time.sleep(_IDLE_WAIT)  # let workers drain idle so the recycle can fire

            elapsed, _ = poll_until_version(
                endpoint_id, api_key, "v2", timeout=_RECYCLE_TIMEOUT, interval=30
            )
            print(f"[multi-worker] first v2 response {elapsed:.1f}s after idle wait")

            # After first v2, no further v1 responses should appear
            worker_ids_v2: set[str] = set()
            for _ in range(8):
                out = ep.run_sync({"msg": "verify"}, timeout=60)
                if out:
                    assert out.get("version") == "v2", (
                        f"Stale v1 worker still serving after cutover: {out}"
                    )
                    worker_ids_v2.add(out.get("worker_id", "unknown"))
            print(f"[multi-worker] v2 worker IDs seen: {worker_ids_v2}")
        finally:
            _undeploy(name, tmp_path, env)
            sweep_endpoints(api_key)


# ---------------------------------------------------------------------------
# Multi-worker always-on: full cutover with zero errors
# ---------------------------------------------------------------------------


class TestRedeployMultiWorkerAlwaysOn:
    """workers=(2,4), CPU: all workers cut over to v2 with zero errors."""

    def test_all_workers_cut_over_to_v2(self, tmp_path: Path, api_key: str) -> None:
        name = f"flash-qa-rdp-mwao-{uuid.uuid4().hex[:8]}"
        env = os.environ.copy()
        (tmp_path / "pyproject.toml").write_text(_pyproject(name))
        runpod.api_key = api_key

        try:
            _deploy(
                _versioned_worker(name, "v1", "workers=(2, 4)"),
                name,
                tmp_path,
                env,
                "v1",
            )
            endpoint_id = endpoint_id_from_state(tmp_path)

            out = runpod.Endpoint(endpoint_id).run_sync({"msg": "warmup"}, timeout=180)
            assert out and out.get("version") == "v1"

            with continuous_caller(endpoint_id, api_key, interval=10.0) as results:
                time.sleep(30)  # baseline before deploy

                _deploy(
                    _versioned_worker(name, "v2", "workers=(2, 4)"),
                    name,
                    tmp_path,
                    env,
                    "v2",
                )

                # Wait until last 5 results are all v2 or timeout
                deadline = time.monotonic() + _RECYCLE_TIMEOUT
                while time.monotonic() < deadline:
                    recent = [r for r in results[-5:] if r[1]]
                    if len(recent) >= 5 and all(
                        r[1].get("version") == "v2" for r in recent
                    ):
                        break
                    time.sleep(2)

                time.sleep(5)  # capture stable v2 period

            log_entries = [
                (f"t={ts:.1f}s", resp.get("version"), resp.get("worker_id"))
                for ts, resp, _ in results
                if resp
            ]
            print(f"[multi-worker-ao] transition sequence ({len(log_entries)} calls):")
            for entry in log_entries:
                print(f"  {entry}")

            errors = [err for _, _, err in results if err]
            versions = [resp.get("version") for _, resp, _ in results if resp]

            assert "v2" in versions, (
                f"v2 never observed in {len(versions)} responses; "
                f"versions seen: {set(versions)}"
            )
            assert versions[-1] == "v2", f"Last response not v2: {versions[-1]!r}"
            assert len(errors) == 0, (
                f"{len(errors)} error(s) during transition "
                f"(indicates hard-kill worker recycle — graceful drain expected): {errors}"
            )
        finally:
            _undeploy(name, tmp_path, env)
            sweep_endpoints(api_key)
