import pytest

from runpod_flash.facade import flags


def test_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("FLASH_USE_APPS_DISPATCH", raising=False)
    assert flags.use_apps_dispatch() is False


@pytest.mark.parametrize(
    "val,expected", [("true", True), ("TRUE", True), ("false", False), ("", False)]
)
def test_flag_reads_env(monkeypatch, val, expected):
    monkeypatch.setenv("FLASH_USE_APPS_DISPATCH", val)
    assert flags.use_apps_dispatch() is expected


@pytest.mark.asyncio
async def test_endpoint_run_uses_facade_client_when_flag_on(monkeypatch):
    import runpod_flash.endpoint as ep_mod

    monkeypatch.setenv("FLASH_USE_APPS_DISPATCH", "true")

    class FakeQC:
        async def run(self, payload):
            return {"id": "j9", "status": "IN_QUEUE"}

    monkeypatch.setattr(
        "runpod_flash.facade.client.apps_qb_client", lambda eid: FakeQC()
    )

    ep = ep_mod.Endpoint(id="ep-xyz")
    job = await ep.run({"prompt": "hi"})

    assert job.id == "j9"
    assert type(job).__name__ == "AppsEndpointJob"


def _spec_queue_client(**returns):
    """a QueueClient double bound to the real apps signatures.

    autospec makes calls to methods apps does not have (e.g. the pre-merge
    `runsync`) fail the way they would against a live endpoint.
    """
    from unittest.mock import create_autospec

    from runpod.apps.targets import QueueClient

    qc = create_autospec(QueueClient, instance=True)
    for name, value in returns.items():
        getattr(qc, name).return_value = value
    return qc


@pytest.mark.asyncio
async def test_endpoint_runsync_uses_apps_invoke_when_flag_on(monkeypatch):
    import runpod_flash.endpoint as ep_mod

    monkeypatch.setenv("FLASH_USE_APPS_DISPATCH", "true")
    qc = _spec_queue_client(
        invoke={"id": "j1", "status": "COMPLETED", "output": {"echo": "hi"}}
    )
    monkeypatch.setattr("runpod_flash.facade.client.apps_qb_client", lambda eid: qc)

    ep = ep_mod.Endpoint(id="ep-xyz")
    job = await ep.runsync({"prompt": "hi"}, timeout=42.0)

    assert job.output == {"echo": "hi"}
    assert job.done is True
    qc.invoke.assert_awaited_once_with({"input": {"prompt": "hi"}}, timeout=42.0)


@pytest.mark.asyncio
async def test_endpoint_runsync_failed_job_surfaces_error_when_flag_on(monkeypatch):
    """matches the legacy path: a FAILED job is returned, not raised."""
    import runpod_flash.endpoint as ep_mod

    monkeypatch.setenv("FLASH_USE_APPS_DISPATCH", "true")
    qc = _spec_queue_client(invoke={"id": "j1", "status": "FAILED", "error": "boom"})
    monkeypatch.setattr("runpod_flash.facade.client.apps_qb_client", lambda eid: qc)

    job = await ep_mod.Endpoint(id="ep-xyz").runsync({"prompt": "hi"})

    assert job.error == "boom"
    assert job.done is True


@pytest.mark.asyncio
async def test_endpoint_cancel_uses_apps_cancel_when_flag_on(monkeypatch):
    import runpod_flash.endpoint as ep_mod

    monkeypatch.setenv("FLASH_USE_APPS_DISPATCH", "true")
    qc = _spec_queue_client(cancel={"id": "j1", "status": "CANCELLED"})
    monkeypatch.setattr("runpod_flash.facade.client.apps_qb_client", lambda eid: qc)

    job = await ep_mod.Endpoint(id="ep-xyz").cancel("j1")

    assert job.done is True
    qc.cancel.assert_awaited_once_with("j1")
