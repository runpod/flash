import pytest

from runpod_flash.facade import dispatch


@pytest.mark.asyncio
async def test_lb_request_routes_through_sentinel(monkeypatch):
    captured = {}

    class FakeTarget:
        def __init__(self, app, env, resource):
            captured["init"] = (app, env, resource)

        async def request(self, method, path, body=None, *, timeout=300.0):
            captured["call"] = (method, path, body, timeout)
            return {"ok": True}

    monkeypatch.setattr(dispatch, "SentinelTarget", FakeTarget)

    result = await dispatch.apps_sentinel_lb_request(
        "my-app",
        "production",
        "live-api",
        "POST",
        "/generate",
        body={"prompt": "hi"},
        timeout=45.0,
    )

    assert result == {"ok": True}
    assert captured["init"] == ("my-app", "production", "api")  # normalized
    assert captured["call"] == ("POST", "/generate", {"prompt": "hi"}, 45.0)
