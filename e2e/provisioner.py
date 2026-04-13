"""Endpoint provisioner for E2E session-scoped fixtures.

provision() deploys a Flash worker and returns its endpoint_id.
All shared endpoints are deployed in parallel at session start.

Git ref injection
-----------------
Set FLASH_SDK_GIT_REF to a commit SHA or branch name to install that exact
version of runpod-flash inside the worker container instead of the latest
PyPI release. In CI, set this to github.sha so workers run the branch under
test rather than the last published release.

    FLASH_SDK_GIT_REF=${{ github.sha }}   # in CI workflow
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from conftest import endpoint_id_from_state

# ---------------------------------------------------------------------------
# Git ref injection
# ---------------------------------------------------------------------------

FLASH_GIT_REF: str = os.environ.get("FLASH_SDK_GIT_REF", "")
_FLASH_REPO = "https://github.com/runpod/runpod-flash"


def flash_dep() -> str:
    """Return the runpod-flash pip requirement string for worker pyproject.toml.

    CI (FLASH_SDK_GIT_REF set): installs the exact commit under test.
    Local dev (unset): installs the latest PyPI release — workers do NOT run
    local code changes. Set FLASH_SDK_GIT_REF to a branch or SHA to override.
    """
    if FLASH_GIT_REF:
        return f"runpod-flash @ git+{_FLASH_REPO}@{FLASH_GIT_REF}"
    return "runpod-flash"


# ---------------------------------------------------------------------------
# Provisioner
# ---------------------------------------------------------------------------

_PYPROJECT_TMPL = """\
[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = [{deps}]
"""


def provision(
    worker_code: str,
    *,
    name: str,
    api_key: str,
    extra_deps: list[str] | None = None,
    deploy_timeout: int = 600,
) -> tuple[str, Path]:
    """Deploy a Flash worker and return (endpoint_id, project_dir).

    The returned project_dir is a temporary directory that owns the .flash
    state. The caller is responsible for cleanup — call shutil.rmtree() on
    project_dir when the endpoint is no longer needed.

    Args:
        worker_code: Python source of the worker file.
        name: Endpoint name (must be unique per CI run).
        api_key: RunPod API key passed explicitly to the subprocess env.
        extra_deps: Additional pip requirements (beyond runpod-flash).
        deploy_timeout: Seconds before subprocess.run times out.

    Returns:
        (endpoint_id, project_dir)

    Raises:
        RuntimeError: If flash deploy exits non-zero.
    """
    deps = [flash_dep()]
    if extra_deps:
        deps.extend(extra_deps)
    deps_quoted = ", ".join(f'"{d}"' for d in deps)
    pyproject = _PYPROJECT_TMPL.format(name=name, deps=deps_quoted)

    tmp_dir = Path(tempfile.mkdtemp(prefix=f"flash-e2e-{name}-"))
    (tmp_dir / "worker.py").write_text(worker_code)
    (tmp_dir / "pyproject.toml").write_text(pyproject)

    env = os.environ.copy()
    env["RUNPOD_API_KEY"] = api_key  # explicit — does not depend on autouse fixture

    try:
        result = subprocess.run(
            ["uv", "run", "flash", "deploy"],
            cwd=tmp_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=deploy_timeout,
        )
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    if result.returncode != 0:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError(
            f"flash deploy failed for '{name}' (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    endpoint_id = endpoint_id_from_state(tmp_dir)
    return endpoint_id, tmp_dir
