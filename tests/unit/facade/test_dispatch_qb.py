import pytest

from runpod_flash.facade import dispatch


@pytest.mark.asyncio
async def test_qb_execute_maps_args_and_unwraps(monkeypatch):
    captured = {}

    class FakeTarget:
        def __init__(self, app, env, resource):
            captured["init"] = (app, env, resource)

        async def invoke(self, payload, *, timeout=300.0):
            captured["payload"] = payload
            return {"text": "ok"}

    monkeypatch.setattr(dispatch, "SentinelTarget", FakeTarget)

    async def handler(prompt: str, steps: int = 1) -> dict:
        return {"prompt": prompt, "steps": steps}

    result = await dispatch.apps_sentinel_qb_execute(
        "my-app", "production", "live-worker-fb", handler, "hi", steps=3
    )

    assert result == {"text": "ok"}
    assert captured["init"] == ("my-app", "production", "worker")  # normalized
    assert captured["payload"] == {"input": {"prompt": "hi", "steps": 3}}


@pytest.mark.asyncio
async def test_qb_execute_empty_input_gets_sentinel_field(monkeypatch):
    seen = {}

    class FakeTarget:
        def __init__(self, *a):
            pass

        async def invoke(self, payload, *, timeout=300.0):
            seen["payload"] = payload
            return None

    monkeypatch.setattr(dispatch, "SentinelTarget", FakeTarget)

    async def handler() -> dict:
        return {}

    await dispatch.apps_sentinel_qb_execute("a", "e", "r", handler)
    assert seen["payload"] == {"input": {"__empty": True}}
