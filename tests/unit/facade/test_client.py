import pytest

from runpod_flash.facade import client as facade_client


class FakeQueueClient:
    def __init__(self):
        self.calls = []

    async def status(self, job_id):
        self.calls.append(("status", job_id))
        return {"id": job_id, "status": "COMPLETED", "output": {"text": "done"}}

    async def cancel(self, job_id):
        self.calls.append(("cancel", job_id))
        return {"id": job_id, "status": "CANCELLED"}


@pytest.mark.asyncio
async def test_endpoint_job_status_updates_and_exposes_output():
    qc = FakeQueueClient()
    job = facade_client.AppsEndpointJob({"id": "j1", "status": "IN_QUEUE"}, qc)

    assert job.id == "j1"
    assert job.done is False

    status = await job.status()

    assert status == "COMPLETED"
    assert job.done is True
    assert job.output == {"text": "done"}


@pytest.mark.asyncio
async def test_endpoint_job_wait_returns_on_terminal():
    qc = FakeQueueClient()
    job = facade_client.AppsEndpointJob({"id": "j2", "status": "IN_QUEUE"}, qc)

    await job.wait(timeout=5.0)

    assert job.done is True
    assert job.output == {"text": "done"}


def test_apps_qb_client_builds_raw_id_client(monkeypatch):
    seen = {}

    class FakeQC:
        def __init__(self, endpoint_id, headers):
            seen["id"] = endpoint_id
            seen["headers"] = headers

    monkeypatch.setattr(facade_client, "QueueClient", FakeQC)
    monkeypatch.setattr(
        facade_client, "_headers", lambda: {"Authorization": "Bearer x"}
    )

    facade_client.apps_qb_client("ep-123")

    assert seen["id"] == "ep-123"
    assert seen["headers"]() == {"Authorization": "Bearer x"}
