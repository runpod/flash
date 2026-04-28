"""E2E test configuration.

Restores real credentials that the global conftest removes for unit test isolation.
E2E tests need real credentials to deploy, invoke, and undeploy live endpoints.
"""

import asyncio
import os
import pickle
import sys
from pathlib import Path

# Ensure the e2e/ directory is on sys.path so test files can import local
# modules (provisioner, etc.) regardless of how pytest resolves the rootdir.
_E2E_DIR = str(Path(__file__).parent)
if _E2E_DIR not in sys.path:
    sys.path.insert(0, _E2E_DIR)

import pytest  # noqa: E402

try:
    import tomllib  # noqa: E402
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]  # noqa: E402


def _api_key_from_config() -> str | None:
    """Read API key from ~/.runpod/config.toml if not in environment."""
    config_file = Path.home() / ".runpod" / "config.toml"
    if not config_file.exists():
        return None
    try:
        data = tomllib.loads(config_file.read_text())
        return data.get("default", {}).get("api_key")
    except Exception as exc:
        print(f"Warning: could not parse ~/.runpod/config.toml: {exc}")
        return None


# Capture before any monkeypatching happens
_REAL_API_KEY = os.environ.get("RUNPOD_API_KEY") or _api_key_from_config()


def endpoint_id_from_state(project_dir: Path) -> str:
    """Read deployed endpoint ID from .flash/resources.pkl.

    The state file is a (resources_dict, config_hashes_dict) tuple.
    resources_dict keys are "ResourceType:name", values are resource objects with .id.

    Raises FileNotFoundError if the state file is missing (deploy did not complete).
    Raises ValueError if the file exists but contains no endpoint ID (format may have changed).
    """
    state_file = project_dir / ".flash" / "resources.pkl"
    if not state_file.exists():
        raise FileNotFoundError(f"State file not found: {state_file}")
    try:
        with open(state_file, "rb") as f:
            data = pickle.load(f)
    except Exception as exc:
        raise ValueError(
            f"Failed to deserialize state file {state_file} — "
            f"the .flash/resources.pkl format may have changed: {exc}"
        ) from exc
    resources = data[0] if isinstance(data, tuple) else data
    for _key, resource in resources.items():
        endpoint_id = getattr(resource, "id", None)
        if endpoint_id:
            return endpoint_id
    raise ValueError(
        f"No endpoint ID found in state file {state_file}. "
        f"Keys present: {list(resources)}. "
        f"Check that the resource object has an 'id' attribute."
    )


def sweep_endpoints(api_key: str, *, prefix: str = "flash-qa-") -> None:
    """Delete endpoints whose names start with prefix.

    Defaults to "flash-qa-" so only test-created endpoints are removed.
    Pass prefix="" to delete all endpoints on the account (use with caution).
    """
    from runpod_flash.core.api.runpod import RunpodGraphQLClient

    async def _run(key: str) -> None:
        client = RunpodGraphQLClient(key)
        result = await client._execute_graphql(
            "query { myself { endpoints { id name } } }"
        )
        all_endpoints = result.get("myself", {}).get("endpoints", [])
        endpoints = [
            ep
            for ep in all_endpoints
            if not prefix or ep.get("name", "").startswith(prefix)
        ]
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


@pytest.fixture(autouse=True)
def restore_real_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore RUNPOD_API_KEY after the global conftest removes it."""
    if _REAL_API_KEY:
        monkeypatch.setenv("RUNPOD_API_KEY", _REAL_API_KEY)
    elif os.environ.get("CI"):
        pytest.fail(
            "RUNPOD_API_KEY secret not configured — set it in repository secrets"
        )
    else:
        pytest.skip("No credentials available — skipping E2E test")


@pytest.fixture
def api_key() -> str:
    """Return the RunPod API key for tests that need to pass it explicitly."""
    return _REAL_API_KEY  # type: ignore[return-value]  # guaranteed set by restore_real_credentials autouse
