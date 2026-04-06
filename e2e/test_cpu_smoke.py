"""CPU smoke: deploy → invoke → undeploy.

Verifies the full deployment pipeline end-to-end. Runs every release.
"""

import os
import subprocess
import uuid
from pathlib import Path

import runpod

from conftest import endpoint_id_from_state, sweep_endpoints

WORKER_NAME = f"flash-qa-smoke-{uuid.uuid4().hex[:8]}"

WORKER_CODE = f'''\
from runpod_flash import Endpoint


@Endpoint(name="{WORKER_NAME}", cpu="cpu3c-1-2")
async def echo(msg: str = "") -> dict:
    return {{"echo": msg, "status": "ok"}}
'''

PYPROJECT_TOML = f'''\
[project]
name = "{WORKER_NAME}"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = ["runpod-flash"]
'''


class TestCpuSmoke:
    """CPU smoke: deploy → invoke → undeploy."""

    def test_deploy_invoke_undeploy(self, tmp_path: Path) -> None:
        """Deploy a minimal CPU worker, invoke it, verify output, undeploy."""
        env = os.environ.copy()

        (tmp_path / "worker.py").write_text(WORKER_CODE)
        (tmp_path / "pyproject.toml").write_text(PYPROJECT_TOML)

        try:
            # Deploy
            result = subprocess.run(
                ["uv", "run", "flash", "deploy"],
                cwd=tmp_path,
                env=env,
                capture_output=True,
                text=True,
                timeout=300,
            )
            assert result.returncode == 0, (
                f"flash deploy failed (exit {result.returncode}):\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )

            endpoint_id = endpoint_id_from_state(tmp_path)

            # Invoke
            runpod.api_key = env.get("RUNPOD_API_KEY")
            output = runpod.Endpoint(endpoint_id).run_sync(
                {"msg": "smoke"}, timeout=180
            )

            assert output is not None, "run_sync returned None"
            assert output.get("echo") == "smoke", f"Unexpected output: {output}"
            assert output.get("status") == "ok", f"Unexpected status: {output}"

        finally:
            # Attempt graceful undeploy first
            try:
                undeploy = subprocess.run(
                    ["uv", "run", "flash", "undeploy", WORKER_NAME, "--force"],
                    cwd=tmp_path,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if undeploy.returncode != 0:
                    print(
                        f"WARNING: undeploy failed (exit {undeploy.returncode}):\n"
                        f"stdout: {undeploy.stdout}\nstderr: {undeploy.stderr}"
                    )
            except subprocess.TimeoutExpired:
                print("WARNING: undeploy timed out after 60s")

            # Always sweep all endpoints — dedicated e2e account, stale
            # endpoints hit the worker quota on subsequent runs.
            sweep_endpoints(env["RUNPOD_API_KEY"])
