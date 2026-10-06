"""behavior identity: each dispatch call site returns the same output with
the apps facade off (FLASH_USE_APPS_DISPATCH unset) and on.

requires real deployed flash endpoints, so every test is skipped unless the
FLASH_PARITY_* variables are set. deploy a QB endpoint whose function takes
an ``echo`` kwarg and an LB endpoint with a ``POST`` echo route, then run:

    FLASH_PARITY_APP=<app> FLASH_PARITY_ENV=<env> \\
    FLASH_PARITY_QB_NAME=<qb-resource> FLASH_PARITY_QB_ID=<qb-endpoint-id> \\
    FLASH_PARITY_LB_NAME=<lb-resource> FLASH_PARITY_LB_ID=<lb-endpoint-id> \\
    FLASH_PARITY_LB_PATH=/echo \\
    uv run pytest tests/integration/facade -v -m integration --no-cov --timeout=600

the --timeout override matters: the project default (30s) is shorter than a
cold start from workersMin=0, so make test-integration-serial times out.

the flag is read at call time, so toggling it with monkeypatch between two
calls in the same process exercises both paths.
"""

import os
from typing import Any, Awaitable, Callable

import pytest

from runpod_flash import Endpoint

FLAG = "FLASH_USE_APPS_DISPATCH"
REQUIRED_VARS = (
    "FLASH_PARITY_APP",
    "FLASH_PARITY_ENV",
    "FLASH_PARITY_QB_NAME",
    "FLASH_PARITY_QB_ID",
    "FLASH_PARITY_LB_NAME",
    "FLASH_PARITY_LB_ID",
    "FLASH_PARITY_LB_PATH",
)
# generous enough to absorb a cold start from workersMin=0
CALL_TIMEOUT = 300.0  # seconds
PAYLOAD = {"echo": "parity"}
# captured at import: the root conftest's autouse isolate_credentials_file
# deletes RUNPOD_API_KEY before every test, but these tests hit real endpoints
_REAL_API_KEY = os.getenv("RUNPOD_API_KEY")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _REAL_API_KEY or any(not os.getenv(var) for var in REQUIRED_VARS),
        reason=f"set RUNPOD_API_KEY, {', '.join(REQUIRED_VARS)} to run dispatch parity",
    ),
]


async def _off_vs_on(
    monkeypatch: pytest.MonkeyPatch, call: Callable[[], Awaitable[Any]]
) -> tuple[Any, Any]:
    """run the same call with the facade flag off, then on."""
    monkeypatch.delenv(FLAG, raising=False)
    legacy = await call()
    monkeypatch.setenv(FLAG, "true")
    facade = await call()
    return legacy, facade


@pytest.fixture(autouse=True)
def real_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """restore the real api key removed by the root conftest isolation."""
    assert _REAL_API_KEY is not None  # guaranteed by the module skipif
    monkeypatch.setenv("RUNPOD_API_KEY", _REAL_API_KEY)


@pytest.fixture
def sentinel_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """point flash sentinel resolution at the parity app/env."""
    monkeypatch.delenv("FLASH_IS_LIVE_PROVISIONING", raising=False)
    monkeypatch.setenv("FLASH_APP", os.environ["FLASH_PARITY_APP"])
    monkeypatch.setenv("FLASH_ENV", os.environ["FLASH_PARITY_ENV"])
    monkeypatch.setenv("FLASH_SENTINEL_TIMEOUT", str(CALL_TIMEOUT))


async def test_qb_raw_id_runsync_identical(monkeypatch: pytest.MonkeyPatch):
    ep = Endpoint(id=os.environ["FLASH_PARITY_QB_ID"])

    async def call() -> Any:
        job = await ep.runsync(PAYLOAD, timeout=CALL_TIMEOUT)
        return job.output

    legacy, facade = await _off_vs_on(monkeypatch, call)

    assert legacy == facade


async def test_qb_raw_id_run_wait_identical(monkeypatch: pytest.MonkeyPatch):
    ep = Endpoint(id=os.environ["FLASH_PARITY_QB_ID"])

    async def call() -> Any:
        job = await ep.run(PAYLOAD)
        await job.wait(timeout=CALL_TIMEOUT)
        return job.output

    legacy, facade = await _off_vs_on(monkeypatch, call)

    assert legacy == facade


async def test_qb_sentinel_identical(
    monkeypatch: pytest.MonkeyPatch, sentinel_context: None
):
    """the path a deployed worker takes for a cross-endpoint QB call."""

    @Endpoint(name=os.environ["FLASH_PARITY_QB_NAME"], cpu="cpu3c-1-2")
    async def echo_fn(echo: str = "") -> dict:
        raise NotImplementedError("stub: runs on the deployed endpoint")

    legacy, facade = await _off_vs_on(monkeypatch, lambda: echo_fn(**PAYLOAD))

    assert legacy == facade


async def test_lb_sentinel_identical(
    monkeypatch: pytest.MonkeyPatch, sentinel_context: None
):
    """the path a deployed worker takes for a cross-endpoint LB call."""
    ep = Endpoint(
        name=os.environ["FLASH_PARITY_LB_NAME"], id=os.environ["FLASH_PARITY_LB_ID"]
    )
    path = os.environ["FLASH_PARITY_LB_PATH"]

    legacy, facade = await _off_vs_on(
        monkeypatch, lambda: ep.post(path, PAYLOAD, timeout=CALL_TIMEOUT)
    )

    assert legacy == facade
