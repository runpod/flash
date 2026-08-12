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

    monkeypatch.setattr(ep_mod, "apps_qb_client", lambda eid: FakeQC(), raising=False)

    ep = ep_mod.Endpoint(id="ep-xyz")
    job = await ep.run({"prompt": "hi"})

    assert job.id == "j9"
    assert type(job).__name__ == "AppsEndpointJob"
