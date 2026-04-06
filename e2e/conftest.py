"""E2E test configuration.

Restores real credentials that the global conftest removes for unit test isolation.
E2E tests need real credentials to deploy, invoke, and undeploy live endpoints.
"""

import asyncio
import os
import pickle
from pathlib import Path

import pytest

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


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


def endpoint_id_from_state(project_dir: Path) -> str:
    """Read deployed endpoint ID from .flash/resources.pkl.

    The state file is a (resources_dict, config_hashes_dict) tuple.
    resources_dict keys are "ResourceType:name", values are resource objects with .id.
    """
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

    The e2e RUNPOD_API_KEY is dedicated to testing. Call this in every test's
    finally block to ensure quota is fully released regardless of whether the
    graceful undeploy succeeded.

    To restrict cleanup to smoke-test endpoints only, swap the list comprehension:
        endpoints = [ep for ep in endpoints if ep.get("name", "").startswith("flash-qa-smoke-")]
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


@pytest.fixture(autouse=True)
def restore_real_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore RUNPOD_API_KEY after the global conftest removes it."""
    if _REAL_API_KEY:
        monkeypatch.setenv("RUNPOD_API_KEY", _REAL_API_KEY)
    elif os.environ.get("CI"):
        pytest.fail("RUNPOD_API_KEY secret not configured — set it in repository secrets")
    else:
        pytest.skip("No credentials available — skipping E2E test")
