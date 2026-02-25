"""tests for Endpoint client mode (id= and image= usage)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from runpod_flash.endpoint import Endpoint

# the http client and resource manager are imported lazily inside method bodies,
# so we patch at the source module rather than at the endpoint module.
_HTTP_CLIENT = "runpod_flash.core.utils.http.get_authenticated_httpx_client"
_RESOURCE_MANAGER = "runpod_flash.core.resources.ResourceManager"


def _mock_httpx_client(*, post_return=None, get_return=None, request_return=None):
    """build a mock async httpx client context manager."""
    client = AsyncMock()

    if post_return is not None:
        resp = MagicMock()
        resp.json.return_value = post_return
        resp.raise_for_status = MagicMock()
        client.post = AsyncMock(return_value=resp)

    if get_return is not None:
        resp = MagicMock()
        resp.json.return_value = get_return
        resp.raise_for_status = MagicMock()
        client.get = AsyncMock(return_value=resp)

    if request_return is not None:
        resp = MagicMock()
        resp.json.return_value = request_return
        resp.raise_for_status = MagicMock()
        client.request = AsyncMock(return_value=resp)

    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


class TestEnsureEndpointReadyIdMode:
    """_ensure_endpoint_ready with id= (pure client, no provisioning)."""

    @pytest.mark.asyncio
    async def test_resolves_url_from_id(self):
        ep = Endpoint(id="ep-abc123")
        with patch("runpod.endpoint_url_base", "https://api.runpod.ai/v2"):
            url = await ep._ensure_endpoint_ready()
        assert url == "https://api.runpod.ai/v2/ep-abc123"

    @pytest.mark.asyncio
    async def test_caches_resolved_url(self):
        ep = Endpoint(id="ep-abc123")
        with patch("runpod.endpoint_url_base", "https://api.runpod.ai/v2"):
            url1 = await ep._ensure_endpoint_ready()
            url2 = await ep._ensure_endpoint_ready()
        assert url1 is url2

    @pytest.mark.asyncio
    async def test_no_resource_manager_called(self):
        ep = Endpoint(id="ep-abc123")
        with patch("runpod.endpoint_url_base", "https://api.runpod.ai/v2"):
            with patch.object(ep, "_build_resource_config") as mock_build:
                await ep._ensure_endpoint_ready()
                mock_build.assert_not_called()


class TestEnsureEndpointReadyImageMode:
    """_ensure_endpoint_ready with image= (provision then client)."""

    @pytest.mark.asyncio
    async def test_provisions_and_resolves_url(self):
        ep = Endpoint(name="vllm", image="vllm:latest")

        mock_deployed = MagicMock()
        mock_deployed.endpoint_url = "https://api.runpod.ai/v2/ep-deployed"

        mock_rm = AsyncMock()
        mock_rm.get_or_deploy_resource = AsyncMock(return_value=mock_deployed)

        with patch(_RESOURCE_MANAGER, return_value=mock_rm):
            url = await ep._ensure_endpoint_ready()

        assert url == "https://api.runpod.ai/v2/ep-deployed"

    @pytest.mark.asyncio
    async def test_falls_back_to_id_when_no_url(self):
        ep = Endpoint(name="vllm", image="vllm:latest")

        mock_deployed = MagicMock()
        mock_deployed.endpoint_url = None
        mock_deployed.id = "ep-fallback"

        mock_rm = AsyncMock()
        mock_rm.get_or_deploy_resource = AsyncMock(return_value=mock_deployed)

        with patch(_RESOURCE_MANAGER, return_value=mock_rm):
            with patch("runpod.endpoint_url_base", "https://api.runpod.ai/v2"):
                url = await ep._ensure_endpoint_ready()

        assert url == "https://api.runpod.ai/v2/ep-fallback"

    @pytest.mark.asyncio
    async def test_raises_when_no_url_or_id(self):
        ep = Endpoint(name="vllm", image="vllm:latest")

        mock_deployed = MagicMock()
        mock_deployed.endpoint_url = None
        mock_deployed.id = None

        mock_rm = AsyncMock()
        mock_rm.get_or_deploy_resource = AsyncMock(return_value=mock_deployed)

        with patch(_RESOURCE_MANAGER, return_value=mock_rm):
            with pytest.raises(RuntimeError, match="no endpoint url or id"):
                await ep._ensure_endpoint_ready()

    @pytest.mark.asyncio
    async def test_caches_after_provisioning(self):
        ep = Endpoint(name="vllm", image="vllm:latest")

        mock_deployed = MagicMock()
        mock_deployed.endpoint_url = "https://api.runpod.ai/v2/ep-deployed"

        mock_rm = AsyncMock()
        mock_rm.get_or_deploy_resource = AsyncMock(return_value=mock_deployed)

        with patch(_RESOURCE_MANAGER, return_value=mock_rm):
            url1 = await ep._ensure_endpoint_ready()
            url2 = await ep._ensure_endpoint_ready()

        assert url1 == url2
        # should only provision once
        mock_rm.get_or_deploy_resource.assert_called_once()


class TestRunMethod:
    """endpoint.run() - async QB job submission."""

    @pytest.mark.asyncio
    async def test_run_posts_to_run_endpoint(self):
        ep = Endpoint(id="ep-123")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-123"

        client = _mock_httpx_client(post_return={"id": "job-1", "status": "IN_QUEUE"})

        with patch(_HTTP_CLIENT, return_value=client):
            result = await ep.run({"prompt": "hello"})

        assert result == {"id": "job-1", "status": "IN_QUEUE"}
        client.post.assert_called_once_with(
            "https://api.runpod.ai/v2/ep-123/run",
            json={"input": {"prompt": "hello"}},
        )


class TestRunsyncMethod:
    """endpoint.runsync() - synchronous QB job submission."""

    @pytest.mark.asyncio
    async def test_runsync_posts_to_runsync_endpoint(self):
        ep = Endpoint(id="ep-123")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-123"

        client = _mock_httpx_client(
            post_return={"id": "job-1", "status": "COMPLETED", "output": {"text": "world"}}
        )

        with patch(_HTTP_CLIENT, return_value=client):
            result = await ep.runsync({"prompt": "hello"})

        assert result["status"] == "COMPLETED"
        assert result["output"] == {"text": "world"}

    @pytest.mark.asyncio
    async def test_runsync_custom_timeout(self):
        ep = Endpoint(id="ep-123")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-123"

        client = _mock_httpx_client(post_return={"status": "COMPLETED"})

        with patch(_HTTP_CLIENT, return_value=client) as mock_factory:
            await ep.runsync({"prompt": "hello"}, timeout=120.0)
            mock_factory.assert_called_once_with(timeout=120.0)


class TestStatusMethod:
    """endpoint.status() - QB job status polling."""

    @pytest.mark.asyncio
    async def test_status_gets_job_status(self):
        ep = Endpoint(id="ep-123")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-123"

        client = _mock_httpx_client(get_return={"id": "job-1", "status": "COMPLETED"})

        with patch(_HTTP_CLIENT, return_value=client):
            result = await ep.status("job-1")

        assert result["status"] == "COMPLETED"
        client.get.assert_called_once_with(
            "https://api.runpod.ai/v2/ep-123/status/job-1"
        )


class TestClientRequest:
    """endpoint._client_request() / .get()/.post() in client mode."""

    @pytest.mark.asyncio
    async def test_post_sends_json_body(self):
        ep = Endpoint(id="ep-123")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-123"

        client = _mock_httpx_client(request_return={"text": "world"})

        with patch(_HTTP_CLIENT, return_value=client):
            result = await ep.post("/v1/completions", {"prompt": "hello"})

        assert result == {"text": "world"}
        client.request.assert_called_once_with(
            "POST",
            "https://api.runpod.ai/v2/ep-123/v1/completions",
            json={"prompt": "hello"},
        )

    @pytest.mark.asyncio
    async def test_get_sends_request(self):
        ep = Endpoint(id="ep-123")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-123"

        client = _mock_httpx_client(request_return={"models": ["llama-3"]})

        with patch(_HTTP_CLIENT, return_value=client):
            result = await ep.get("/v1/models")

        assert result == {"models": ["llama-3"]}
        client.request.assert_called_once_with(
            "GET",
            "https://api.runpod.ai/v2/ep-123/v1/models",
            json=None,
        )

    @pytest.mark.asyncio
    async def test_custom_timeout(self):
        ep = Endpoint(id="ep-123")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-123"

        client = _mock_httpx_client(request_return={})

        with patch(_HTTP_CLIENT, return_value=client) as mock_factory:
            await ep.post("/run", {}, timeout=120.0)
            mock_factory.assert_called_once_with(timeout=120.0)

    @pytest.mark.asyncio
    async def test_delete_sends_request(self):
        ep = Endpoint(id="ep-123")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-123"

        client = _mock_httpx_client(request_return={"deleted": True})

        with patch(_HTTP_CLIENT, return_value=client):
            result = await ep.delete("/v1/resource/123")

        assert result == {"deleted": True}

    @pytest.mark.asyncio
    async def test_put_sends_request(self):
        ep = Endpoint(id="ep-123")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-123"

        client = _mock_httpx_client(request_return={"updated": True})

        with patch(_HTTP_CLIENT, return_value=client):
            result = await ep.put("/v1/resource/123", {"field": "value"})

        assert result == {"updated": True}
        client.request.assert_called_once_with(
            "PUT",
            "https://api.runpod.ai/v2/ep-123/v1/resource/123",
            json={"field": "value"},
        )

    @pytest.mark.asyncio
    async def test_patch_sends_request(self):
        ep = Endpoint(id="ep-123")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-123"

        client = _mock_httpx_client(request_return={"patched": True})

        with patch(_HTTP_CLIENT, return_value=client):
            result = await ep.patch("/v1/resource/123", {"field": "new"})

        assert result == {"patched": True}


class TestEndToEndFlow:
    """test the full flow: id= endpoint -> run/runsync/status."""

    @pytest.mark.asyncio
    async def test_id_mode_run_then_status(self):
        ep = Endpoint(id="ep-999")

        client_run = _mock_httpx_client(post_return={"id": "job-42", "status": "IN_QUEUE"})
        client_status = _mock_httpx_client(
            get_return={"id": "job-42", "status": "COMPLETED", "output": "done"}
        )

        with patch("runpod.endpoint_url_base", "https://api.runpod.ai/v2"):
            with patch(_HTTP_CLIENT, return_value=client_run):
                run_result = await ep.run({"prompt": "hello"})
                assert run_result["id"] == "job-42"

            with patch(_HTTP_CLIENT, return_value=client_status):
                status_result = await ep.status("job-42")
                assert status_result["status"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_image_mode_provisions_then_calls(self):
        ep = Endpoint(name="vllm", image="vllm:latest")

        mock_deployed = MagicMock()
        mock_deployed.endpoint_url = "https://api.runpod.ai/v2/ep-deployed"

        mock_rm = AsyncMock()
        mock_rm.get_or_deploy_resource = AsyncMock(return_value=mock_deployed)

        client = _mock_httpx_client(request_return={"text": "world"})

        with patch(_RESOURCE_MANAGER, return_value=mock_rm):
            with patch(_HTTP_CLIENT, return_value=client):
                result = await ep.post("/v1/completions", {"prompt": "hello"})

        assert result == {"text": "world"}
        mock_rm.get_or_deploy_resource.assert_called_once()
