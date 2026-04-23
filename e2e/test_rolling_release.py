"""Rolling release E2E tests — drift detection.

Verifies the reconcile/update path that runs on every flash deploy:

  - No spurious release when code and config are unchanged
  - Genuine config change triggers a real update
"""

import os
import subprocess
import uuid
from pathlib import Path

import runpod

from conftest import endpoint_id_from_state, sweep_endpoints
from provisioner import flash_dep

# ---------------------------------------------------------------------------
# Worker code
# ---------------------------------------------------------------------------

_PYPROJECT_TMPL = """\
[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = ["{dep}"]
"""


def _pyproject(name: str) -> str:
    return _PYPROJECT_TMPL.format(name=name, dep=flash_dep())


def _echo_worker(name: str, workers: str = "workers=(1, 1)") -> str:
    return f'''\
import os
from runpod_flash import Endpoint


@Endpoint(name="{name}", cpu="cpu3c-1-2", {workers})
async def echo(msg: str = "") -> dict:
    return {{
        "echo": msg,
        "worker_id": os.environ.get("RUNPOD_POD_ID", "unknown"),
    }}
'''


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _deploy(code: str, name: str, cwd: Path, env: dict) -> subprocess.CompletedProcess:
    (cwd / "worker.py").write_text(code)
    return subprocess.run(
        ["uv", "run", "flash", "deploy"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


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
        print(f"WARNING: undeploy of {name} timed out")


def _deploy_env(api_key: str) -> dict:
    env = os.environ.copy()
    env["RUNPOD_API_KEY"] = api_key
    env["NO_COLOR"] = "1"  # strip ANSI from rich output so stdout is plain text
    return env


class TestRollingReleaseNoSpuriousRelease:
    """Two successive deploys with identical code and config must be a no-op.

    The second deploy must show 'cached' in output, not 'deployed'.
    Worker ID must be unchanged — no new release was triggered.
    Uses workers=(1,1) to keep a warm worker for a stable worker_id.
    """

    def test_identical_redeploy_is_cached(self, tmp_path: Path, api_key: str) -> None:
        name = f"flash-qa-rr-nsr-{uuid.uuid4().hex[:8]}"
        env = _deploy_env(api_key)
        (tmp_path / "pyproject.toml").write_text(_pyproject(name))
        runpod.api_key = api_key

        try:
            r1 = _deploy(_echo_worker(name), name, tmp_path, env)
            assert r1.returncode == 0, (
                f"Initial deploy failed:\n{r1.stdout}\n{r1.stderr}"
            )
            endpoint_id = endpoint_id_from_state(tmp_path)

            out1 = runpod.Endpoint(endpoint_id).run_sync({"msg": "before"}, timeout=180)
            assert out1 is not None, "First invocation returned None"
            worker_id_before = out1.get("worker_id", "")

            # Second deploy — identical code and config
            r2 = _deploy(_echo_worker(name), name, tmp_path, env)
            assert r2.returncode == 0, (
                f"Second deploy failed:\n{r2.stdout}\n{r2.stderr}"
            )

            # v1.14.0 CLI always prints "Deployed to production" regardless of whether
            # the platform triggered a worker recycle — no "cached" signal in output.
            # Worker ID comparison below is the authoritative behavioral check.

            out2 = runpod.Endpoint(endpoint_id).run_sync({"msg": "after"}, timeout=60)
            assert out2 is not None, "Post-redeploy invocation returned None"
            worker_id_after = out2.get("worker_id", "")

            assert worker_id_before == worker_id_after, (
                f"Worker ID changed after no-op redeploy — spurious rolling release fired: "
                f"{worker_id_before!r} → {worker_id_after!r}"
            )
        finally:
            _undeploy(name, tmp_path, env)
            sweep_endpoints(api_key)


class TestRollingReleaseConfigChangeTriggersDrift:
    """Changing workers=(0,1) to workers=(1,1) must trigger a real update.

    Verifies that drift detection is not suppressed for genuine config changes.
    """

    def test_config_change_triggers_update(self, tmp_path: Path, api_key: str) -> None:
        name = f"flash-qa-rr-ccd-{uuid.uuid4().hex[:8]}"
        env = _deploy_env(api_key)
        (tmp_path / "pyproject.toml").write_text(_pyproject(name))

        try:
            # Deploy with scale-to-zero
            r1 = _deploy(
                _echo_worker(name, workers="workers=(0, 1)"), name, tmp_path, env
            )
            assert r1.returncode == 0, (
                f"Initial deploy failed:\n{r1.stdout}\n{r1.stderr}"
            )

            # Re-deploy with always-on (config change only — same code)
            r2 = _deploy(
                _echo_worker(name, workers="workers=(1, 1)"), name, tmp_path, env
            )
            assert r2.returncode == 0, (
                f"Config-change deploy failed:\n{r2.stdout}\n{r2.stderr}"
            )

            # v1.14.0 CLI always prints "Deployed to production" — no distinct
            # "drift detected" vs "cached" signal. The endpoint update log line is
            # the only CLI observable; it appears only when the endpoint is mutated.
            combined = r2.stdout + r2.stderr
            assert "updating endpoint" in combined.lower(), (
                f"Expected endpoint update log in config-change deploy output:\n{combined}"
            )
        finally:
            _undeploy(name, tmp_path, env)
            sweep_endpoints(api_key)
