"""GPU smoke test — deploy → invoke → undeploy on a GPU worker.

Requires GPU quota on the account and a valid RUNPOD_API_KEY.
"""

import os
import subprocess
import uuid
from pathlib import Path

import runpod

from conftest import endpoint_id_from_state, sweep_endpoints
from provisioner import flash_dep

_WORKER_NAME = f"flash-qa-gpu-smoke-{uuid.uuid4().hex[:8]}"

_WORKER_CODE = f'''\
from runpod_flash import Endpoint


@Endpoint(name="{_WORKER_NAME}")
async def echo(msg: str = "") -> dict:
    return {{"echo": msg, "status": "ok"}}
'''

_PYPROJECT_TOML = f'''\
[project]
name = "{_WORKER_NAME}"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = ["{flash_dep()}"]
'''


class TestGpuSmoke:
    """GPU smoke: deploy → invoke → undeploy on a default GPU worker."""

    def test_deploy_invoke_undeploy(self, tmp_path: Path, api_key: str) -> None:
        env = os.environ.copy()
        (tmp_path / "worker.py").write_text(_WORKER_CODE)
        (tmp_path / "pyproject.toml").write_text(_PYPROJECT_TOML)

        try:
            result = subprocess.run(
                ["uv", "run", "flash", "deploy"],
                cwd=tmp_path,
                env=env,
                capture_output=True,
                text=True,
                timeout=600,
            )
            assert result.returncode == 0, (
                f"flash deploy failed (exit {result.returncode}):\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )

            endpoint_id = endpoint_id_from_state(tmp_path)
            runpod.api_key = env["RUNPOD_API_KEY"]

            output = runpod.Endpoint(endpoint_id).run_sync(
                {"msg": "smoke"}, timeout=300
            )
            assert output is not None, "run_sync returned None"
            assert output.get("echo") == "smoke", f"Unexpected output: {output}"
            assert output.get("status") == "ok", f"Unexpected status: {output}"

        finally:
            try:
                subprocess.run(
                    ["uv", "run", "flash", "undeploy", _WORKER_NAME, "--force"],
                    cwd=tmp_path,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            except subprocess.TimeoutExpired:
                print("WARNING: GPU undeploy timed out after 60s")
            sweep_endpoints(env["RUNPOD_API_KEY"])
