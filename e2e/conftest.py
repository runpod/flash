"""E2E test configuration.

Session-scoped fixtures deploy all shared endpoints in parallel at session
start and tear them down at session end via sweep_endpoints().

Per-test lifecycle tests (redeploy, autoscaling, network volume) manage their
own deploy/undeploy inside each test method.
"""

import asyncio
import json
import os
import pickle
import shutil
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Generator

import pytest

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def _api_key_from_config() -> str | None:
    """Read API key from ~/.runpod/config.toml if not in environment."""
    config_file = Path.home() / ".runpod" / "config.toml"
    if not config_file.exists():
        return None
    try:
        data = tomllib.loads(config_file.read_text())
        return data.get("default", {}).get("api_key")
    except Exception:
        return None


# Capture before any monkeypatching happens
_REAL_API_KEY = os.environ.get("RUNPOD_API_KEY") or _api_key_from_config()


@pytest.fixture(autouse=True)
def restore_real_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore RUNPOD_API_KEY for subprocess calls after the global conftest removes it."""
    if _REAL_API_KEY:
        monkeypatch.setenv("RUNPOD_API_KEY", _REAL_API_KEY)
    elif os.environ.get("CI"):
        pytest.fail(
            "RUNPOD_API_KEY secret not configured — set it in repository secrets"
        )
    else:
        pytest.skip("No credentials available — skipping E2E test")


@pytest.fixture(scope="session")
def api_key() -> str:
    """API key for the entire test session — available before autouse fixture runs."""
    key = _REAL_API_KEY
    if not key:
        if os.environ.get("CI"):
            pytest.fail("RUNPOD_API_KEY not set")
        pytest.skip("No credentials — skipping E2E tests")
    return key


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def endpoint_id_from_state(project_dir: Path) -> str:
    """Read deployed endpoint ID from .flash/resources.pkl."""
    state_file = project_dir / ".flash" / "resources.pkl"
    if not state_file.exists():
        raise FileNotFoundError(f"State file not found: {state_file}")
    with open(state_file, "rb") as f:
        data = pickle.load(f)
    resources = data[0] if isinstance(data, tuple) else data
    for _key, resource in resources.items():
        endpoint_id = getattr(resource, "id", None)
        if endpoint_id:
            return endpoint_id
    raise ValueError(f"No endpoint ID found in state file. Keys: {list(resources)}")


def sweep_endpoints(api_key: str) -> None:
    """Delete all endpoints on the account.

    The e2e RUNPOD_API_KEY is dedicated to testing. Always call this in
    finally blocks to release quota regardless of graceful undeploy status.
    """
    from runpod_flash.core.api.runpod import RunpodGraphQLClient

    async def _run(key: str) -> None:
        client = RunpodGraphQLClient(key)
        result = await client._execute_graphql(
            "query { myself { endpoints { id name } } }"
        )
        endpoints = result.get("myself", {}).get("endpoints", [])
        for ep in endpoints:
            eid, ename = ep["id"], ep.get("name", ep["id"])
            try:
                await client.delete_endpoint(eid)
                print(f"Deleted endpoint {ename} ({eid})")
            except Exception as del_err:
                print(f"Failed to delete {ename} ({eid}): {del_err}")

    try:
        asyncio.run(_run(api_key))
    except Exception as sweep_err:
        print(f"Endpoint sweep failed: {sweep_err}")


def call_lb(
    endpoint_id: str,
    api_key: str,
    path: str,
    *,
    method: str = "POST",
    json_data: object = None,
    timeout: int = 60,
) -> object:
    """Make an HTTP call to a deployed LB endpoint.

    URL: https://{endpoint_id}.api.runpod.ai{path}
    Returns parsed JSON body, or None for empty responses.
    Raises AssertionError on HTTP errors.
    """
    url = f"https://{endpoint_id}.api.runpod.ai{path}"
    data = json.dumps(json_data).encode() if json_data is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            return json.loads(body) if body.strip() else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        raise AssertionError(
            f"LB HTTP {exc.code} from {method} {url}: {body}"
        ) from exc


# ---------------------------------------------------------------------------
# Session-scoped endpoint provisioning
# ---------------------------------------------------------------------------

# Unique suffix per session — prevents name collisions across concurrent CI runs
_SESSION_ID = uuid.uuid4().hex[:8]


def _n(role: str) -> str:
    """Build a stable per-session endpoint name for a given role."""
    return f"flash-qa-{role}-{_SESSION_ID}"


# Worker code templates — one per shared endpoint role.
# Names are filled in at fixture setup time via _n().

_CPU_FN_CODE = """\
from runpod_flash import Endpoint

@Endpoint(name="{name}", cpu="cpu3c-1-2", workers=(0, 2))
async def echo(msg: str = "") -> dict:
    return {{"echo": msg, "status": "ok"}}
"""

_CPU_CLS_CODE = """\
from runpod_flash import Endpoint

@Endpoint(name="{name}", cpu="cpu3c-1-2", workers=(0, 1))
class Calculator:
    def __init__(self) -> None:
        self.factor = 3

    def multiply(self, x: int = 1) -> dict:
        return {{"result": x * self.factor, "status": "ok"}}
"""

_CPU_LB_CODE = """\
from runpod_flash import Endpoint

api = Endpoint(name="{name}", cpu="cpu3c-1-2", workers=(1, 1))

@api.post("/echo")
async def echo(msg: str = "") -> dict:
    return {{"echo": msg, "status": "ok"}}

@api.get("/health")
async def health() -> dict:
    return {{"status": "healthy"}}
"""

_CPU_DEPS_CODE = """\
from runpod_flash import Endpoint

@Endpoint(name="{name}", cpu="cpu3c-1-2", workers=(0, 1), dependencies=["numpy", "pandas"])
async def compute(x: float = 1.0) -> dict:
    import numpy as np
    import pandas as pd

    arr = np.array([x, x * 2, x * 3])
    return {{"sum": float(arr.sum()), "dtype": pd.Series([x]).dtype.name}}
"""

_GPU_FN_CODE = """\
from runpod_flash import Endpoint, GpuGroup

@Endpoint(name="{name}", gpu=GpuGroup.ANY, workers=(0, 1))
async def hello(msg: str = "") -> dict:
    return {{"hello": msg, "status": "ok"}}
"""

_GPU_CLS_CODE = """\
from runpod_flash import Endpoint, GpuGroup

@Endpoint(name="{name}", gpu=GpuGroup.ANY, workers=(0, 1))
class GPUWorker:
    def __init__(self) -> None:
        self.factor = 4

    def compute(self, x: float = 1.0) -> dict:
        return {{"result": x * self.factor, "status": "ok"}}
"""

_GPU_LB_CODE = """\
from runpod_flash import Endpoint, GpuGroup

api = Endpoint(name="{name}", gpu=GpuGroup.ANY, workers=(1, 1))

@api.post("/predict")
async def predict(value: float = 0.0) -> dict:
    return {{"prediction": value * 2, "status": "ok"}}

@api.get("/health")
async def health() -> dict:
    return {{"status": "healthy", "gpu": True}}
"""

_SHARED_WORKERS: dict[str, tuple[str, list[str], int]] = {
    # key: (code_template, extra_deps, deploy_timeout_seconds)
    "cpu_fn":   (_CPU_FN_CODE,   [],                   300),
    "cpu_cls":  (_CPU_CLS_CODE,  [],                   300),
    "cpu_lb":   (_CPU_LB_CODE,   [],                   300),
    "cpu_deps": (_CPU_DEPS_CODE, ["numpy", "pandas"],  300),
    "gpu_fn":   (_GPU_FN_CODE,   [],                   600),
    "gpu_cls":  (_GPU_CLS_CODE,  [],                   600),
    "gpu_lb":   (_GPU_LB_CODE,   [],                   600),
}


@pytest.fixture(scope="session")
def provisioned(api_key: str) -> Generator[dict[str, str], None, None]:
    """Deploy all shared endpoints in parallel; yield endpoint_id map; sweep at end.

    Returns a dict mapping role → endpoint_id, e.g.:
        {"cpu_fn": "abc123", "cpu_lb": "def456", ...}

    If a worker fails to deploy (e.g. GPU inventory unavailable), its key is
    absent from the dict. Tests must call pytest.skip() when their key is missing.
    """
    from provisioner import provision

    # Pre-sweep: remove any stale endpoints from previous runs before provisioning
    print("[provisioned] sweeping stale endpoints before deploy...")
    sweep_endpoints(api_key)

    endpoint_ids: dict[str, str] = {}
    tmp_dirs: list[Path] = []

    def _deploy(role: str, code_tmpl: str, extra_deps: list[str], timeout: int) -> tuple[str, str, Path]:
        name = _n(role)
        code = code_tmpl.format(name=name)
        endpoint_id, tmp_dir = provision(
            code,
            name=name,
            api_key=api_key,
            extra_deps=extra_deps,
            deploy_timeout=timeout,
        )
        return role, endpoint_id, tmp_dir

    try:
        with ThreadPoolExecutor() as pool:
            futures = {
                pool.submit(_deploy, role, tmpl, deps, t): role
                for role, (tmpl, deps, t) in _SHARED_WORKERS.items()
            }
            for future in as_completed(futures):
                role = futures[future]
                try:
                    r, eid, tmp_dir = future.result()
                    endpoint_ids[r] = eid
                    tmp_dirs.append(tmp_dir)
                    print(f"[provisioned] {r} → {eid}")
                except Exception as exc:
                    print(f"[provisioned] WARNING: failed to deploy {role}: {exc}")

        yield endpoint_ids

    finally:
        sweep_endpoints(api_key)
        for d in tmp_dirs:
            shutil.rmtree(d, ignore_errors=True)
