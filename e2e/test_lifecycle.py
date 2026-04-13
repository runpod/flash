"""Lifecycle E2E tests — each test manages its own deploy/undeploy.

These scenarios genuinely require a fresh endpoint per test:
  Scale-to-zero (workers=(0, 4)) — cold-start must complete
  Always-on (workers=(1, 4)) — warm worker must serve immediately
  Redeploy v1 → v2 — same endpoint ID retained, v2 code live
  Network volume — write/read across invocations via mounted volume
"""

import os
import subprocess
import uuid
from pathlib import Path

import pytest
import runpod

from conftest import endpoint_id_from_state, sweep_endpoints
from provisioner import flash_dep, provision

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_VOLUME_ID = os.environ.get("RUNPOD_NETWORK_VOLUME_ID", "")

_BASE_PYPROJECT = """\
[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = ["{dep}"]
"""


def _pyproject(name: str) -> str:
    return _BASE_PYPROJECT.format(name=name, dep=flash_dep())


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


# ---------------------------------------------------------------------------
# Scale-to-zero
# ---------------------------------------------------------------------------


class TestScaleToZero:
    """workers=(0, 4) — scale-to-zero, first call cold-starts."""

    def test_cold_start_completes(self, tmp_path: Path, api_key: str) -> None:
        name = f"flash-qa-s2z-{uuid.uuid4().hex[:8]}"
        code = f'''\
from runpod_flash import Endpoint

@Endpoint(name="{name}", cpu="cpu3c-1-2", workers=(0, 4))
async def echo(msg: str = "") -> dict:
    return {{"echo": msg, "status": "ok"}}
'''
        env = os.environ.copy()
        (tmp_path / "worker.py").write_text(code)
        (tmp_path / "pyproject.toml").write_text(_pyproject(name))

        try:
            result = subprocess.run(
                ["uv", "run", "flash", "deploy"],
                cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300,
            )
            assert result.returncode == 0, (
                f"deploy failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
            )
            endpoint_id = endpoint_id_from_state(tmp_path)
            runpod.api_key = api_key
            # Extended timeout — cold start from zero workers
            output = runpod.Endpoint(endpoint_id).run_sync({"msg": "cold"}, timeout=240)
            assert output is not None
            assert output.get("echo") == "cold"
            assert output.get("status") == "ok"
        finally:
            _undeploy(name, tmp_path, env)
            sweep_endpoints(api_key)


# ---------------------------------------------------------------------------
# Always-on
# ---------------------------------------------------------------------------


class TestAlwaysOn:
    """workers=(1, 4) — always-on worker is warm after deploy."""

    def test_warm_worker_responds(self, tmp_path: Path, api_key: str) -> None:
        name = f"flash-qa-aon-{uuid.uuid4().hex[:8]}"
        code = f'''\
from runpod_flash import Endpoint

@Endpoint(name="{name}", cpu="cpu3c-1-2", workers=(1, 4))
async def echo(msg: str = "") -> dict:
    return {{"echo": msg, "status": "ok"}}
'''
        env = os.environ.copy()
        (tmp_path / "worker.py").write_text(code)
        (tmp_path / "pyproject.toml").write_text(_pyproject(name))

        try:
            result = subprocess.run(
                ["uv", "run", "flash", "deploy"],
                cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300,
            )
            assert result.returncode == 0, (
                f"deploy failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
            )
            endpoint_id = endpoint_id_from_state(tmp_path)
            runpod.api_key = api_key
            output = runpod.Endpoint(endpoint_id).run_sync({"msg": "warm"}, timeout=180)
            assert output is not None
            assert output.get("echo") == "warm"
            assert output.get("status") == "ok"
        finally:
            _undeploy(name, tmp_path, env)
            sweep_endpoints(api_key)


# ---------------------------------------------------------------------------
# Redeploy
# ---------------------------------------------------------------------------


class TestRedeploy:
    """Second deploy retains the same endpoint ID; v2 code goes live."""

    def test_redeploy_retains_endpoint_id(self, tmp_path: Path, api_key: str) -> None:
        name = f"flash-qa-redeploy-{uuid.uuid4().hex[:8]}"
        env = os.environ.copy()
        (tmp_path / "pyproject.toml").write_text(_pyproject(name))

        def _worker(version: str) -> str:
            return f'''\
from runpod_flash import Endpoint

@Endpoint(name="{name}", cpu="cpu3c-1-2")
async def echo(msg: str = "") -> dict:
    return {{"msg": msg, "version": "{version}"}}
'''
        try:
            # Deploy v1
            (tmp_path / "worker.py").write_text(_worker("v1"))
            r = subprocess.run(
                ["uv", "run", "flash", "deploy"],
                cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300,
            )
            assert r.returncode == 0, f"v1 deploy failed:\n{r.stdout}\n{r.stderr}"
            endpoint_id_v1 = endpoint_id_from_state(tmp_path)

            # Deploy v2 — same project dir, same endpoint name
            (tmp_path / "worker.py").write_text(_worker("v2"))
            r = subprocess.run(
                ["uv", "run", "flash", "deploy"],
                cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300,
            )
            assert r.returncode == 0, f"v2 redeploy failed:\n{r.stdout}\n{r.stderr}"
            endpoint_id_v2 = endpoint_id_from_state(tmp_path)

            assert endpoint_id_v1 == endpoint_id_v2, (
                f"Redeploy created a new endpoint: v1={endpoint_id_v1}, v2={endpoint_id_v2}"
            )

            runpod.api_key = api_key
            output = runpod.Endpoint(endpoint_id_v2).run_sync({"msg": "hello"}, timeout=180)
            assert output is not None
            assert output.get("msg") == "hello"
            assert output.get("version") == "v2", f"Expected v2, got: {output}"
        finally:
            _undeploy(name, tmp_path, env)
            sweep_endpoints(api_key)


# ---------------------------------------------------------------------------
# Network volume
# ---------------------------------------------------------------------------


class TestNetworkVolume:
    """Files written to a mounted volume persist across invocations.

    RunPod mounts network volumes at /runpod-volume on serverless workers.
    """

    @pytest.mark.skipif(not _VOLUME_ID, reason="RUNPOD_NETWORK_VOLUME_ID not set")
    def test_volume_write_read(self, tmp_path: Path, api_key: str) -> None:
        name = f"flash-qa-vol-{uuid.uuid4().hex[:8]}"
        mount = "/runpod-volume"
        test_file = f"{mount}/flash_e2e_test.txt"
        code = f'''\
from runpod_flash import Endpoint, NetworkVolume

_vol = NetworkVolume(id="{_VOLUME_ID}")

@Endpoint(name="{name}", cpu="cpu3c-1-2", volume=_vol)
async def file_ops(action: str = "write", content: str = "") -> dict:
    path = "{test_file}"
    if action == "write":
        with open(path, "w") as fh:
            fh.write(content)
        return {{"written": content}}
    if action == "read":
        with open(path) as fh:
            return {{"content": fh.read()}}
    return {{"error": f"unknown action: {{action}}"}}
'''
        env = os.environ.copy()
        (tmp_path / "worker.py").write_text(code)
        (tmp_path / "pyproject.toml").write_text(_pyproject(name))

        try:
            result = subprocess.run(
                ["uv", "run", "flash", "deploy"],
                cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300,
            )
            assert result.returncode == 0, (
                f"deploy failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
            )
            endpoint_id = endpoint_id_from_state(tmp_path)
            runpod.api_key = api_key
            ep = runpod.Endpoint(endpoint_id)

            sentinel = f"e2e-{uuid.uuid4().hex[:12]}"

            write_out = ep.run_sync({"action": "write", "content": sentinel}, timeout=180)
            assert write_out is not None
            assert write_out.get("written") == sentinel, f"Write output: {write_out}"

            read_out = ep.run_sync({"action": "read"}, timeout=180)
            assert read_out is not None
            assert read_out.get("content") == sentinel, (
                f"Wrote {sentinel!r}, read {read_out.get('content')!r}"
            )
        finally:
            _undeploy(name, tmp_path, env)
            sweep_endpoints(api_key)
