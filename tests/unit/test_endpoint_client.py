"""tests for Endpoint client mode and EndpointJob."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from runpod_flash.endpoint import Endpoint, EndpointJob

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


# -- EndpointJob --


class TestEndpointJob:
    def test_init_from_data(self):
        ep = Endpoint(id="ep-1")
        job = EndpointJob({"id": "j-1", "status": "IN_QUEUE"}, ep)
        assert job.id == "j-1"
        assert job._data["status"] == "IN_QUEUE"
        assert job.output is None
        assert job.error is None
        assert job.done is False

    def test_init_completed(self):
        ep = Endpoint(id="ep-1")
        job = EndpointJob(
            {"id": "j-1", "status": "COMPLETED", "output": {"text": "hi"}}, ep
        )
        assert job.done is True
        assert job.output == {"text": "hi"}

    def test_init_failed(self):
        ep = Endpoint(id="ep-1")
        job = EndpointJob({"id": "j-1", "status": "FAILED", "error": "oom"}, ep)
        assert job.done is True
        assert job.error == "oom"

    def test_repr(self):
        ep = Endpoint(id="ep-1")
        job = EndpointJob({"id": "j-1", "status": "IN_QUEUE"}, ep)
        assert repr(job) == "EndpointJob(id='j-1', status='IN_QUEUE')"

    def test_done_for_all_terminal_statuses(self):
        ep = Endpoint(id="ep-1")
        for s in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
            job = EndpointJob({"id": "j", "status": s}, ep)
            assert job.done is True, f"expected done=True for {s}"

    def test_not_done_for_active_statuses(self):
        ep = Endpoint(id="ep-1")
        for s in ("IN_QUEUE", "IN_PROGRESS", "UNKNOWN"):
            job = EndpointJob({"id": "j", "status": s}, ep)
            assert job.done is False, f"expected done=False for {s}"


class TestEndpointJobStatus:
    @pytest.mark.asyncio
    async def test_status_polls_and_returns_string(self):
        ep = Endpoint(id="ep-1")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-1"
        job = EndpointJob({"id": "j-1", "status": "IN_QUEUE"}, ep)

        client = _mock_httpx_client(
            get_return={"id": "j-1", "status": "COMPLETED", "output": {"r": 1}}
        )

        with patch(_HTTP_CLIENT, return_value=client):
            s = await job.status()

        assert s == "COMPLETED"
        assert job._data["status"] == "COMPLETED"
        assert job.output == {"r": 1}
        assert job.done is True

    @pytest.mark.asyncio
    async def test_status_updates_error(self):
        ep = Endpoint(id="ep-1")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-1"
        job = EndpointJob({"id": "j-1", "status": "IN_QUEUE"}, ep)

        client = _mock_httpx_client(
            get_return={"id": "j-1", "status": "FAILED", "error": "oom"}
        )

        with patch(_HTTP_CLIENT, return_value=client):
            s = await job.status()

        assert s == "FAILED"
        assert job.error == "oom"


class TestEndpointJobCancel:
    @pytest.mark.asyncio
    async def test_cancel_posts_and_updates(self):
        ep = Endpoint(id="ep-1")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-1"
        job = EndpointJob({"id": "j-1", "status": "IN_QUEUE"}, ep)

        client = _mock_httpx_client(post_return={"id": "j-1", "status": "CANCELLED"})

        with patch(_HTTP_CLIENT, return_value=client):
            result = await job.cancel()

        assert result is job
        assert job._data["status"] == "CANCELLED"
        assert job.done is True
        client.post.assert_called_once_with(
            "https://api.runpod.ai/v2/ep-1/cancel/j-1", json=None
        )


class TestEndpointJobWait:
    @pytest.mark.asyncio
    async def test_wait_polls_until_done(self):
        ep = Endpoint(id="ep-1")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-1"
        job = EndpointJob({"id": "j-1", "status": "IN_QUEUE"}, ep)

        responses = [
            {"id": "j-1", "status": "IN_PROGRESS"},
            {"id": "j-1", "status": "COMPLETED", "output": {"r": 1}},
        ]
        call_count = 0

        def make_response():
            nonlocal call_count
            resp = MagicMock()
            resp.json.return_value = responses[min(call_count, len(responses) - 1)]
            resp.raise_for_status = MagicMock()
            call_count += 1
            return resp

        client = AsyncMock()
        client.get = AsyncMock(side_effect=lambda *a, **kw: make_response())
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)

        with patch(_HTTP_CLIENT, return_value=client):
            result = await job.wait()

        assert result is job
        assert job._data["status"] == "COMPLETED"
        assert job.output == {"r": 1}
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_wait_returns_immediately_if_already_done(self):
        ep = Endpoint(id="ep-1")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-1"
        job = EndpointJob({"id": "j-1", "status": "COMPLETED", "output": 42}, ep)

        # no HTTP calls should happen
        result = await job.wait()
        assert result is job
        assert job.output == 42

    @pytest.mark.asyncio
    async def test_wait_timeout_raises(self):
        ep = Endpoint(id="ep-1")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-1"
        job = EndpointJob({"id": "j-1", "status": "IN_QUEUE"}, ep)

        # always return IN_QUEUE so it never finishes
        client = _mock_httpx_client(get_return={"id": "j-1", "status": "IN_QUEUE"})

        with patch(_HTTP_CLIENT, return_value=client):
            with pytest.raises(TimeoutError, match="did not complete within"):
                await job.wait(timeout=0.3)


# -- Endpoint.run / runsync / cancel --


class TestEndpointRun:
    @pytest.mark.asyncio
    async def test_run_returns_endpoint_job(self):
        ep = Endpoint(id="ep-123")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-123"

        client = _mock_httpx_client(post_return={"id": "job-1", "status": "IN_QUEUE"})

        with patch(_HTTP_CLIENT, return_value=client):
            job = await ep.run({"prompt": "hello"})

        assert isinstance(job, EndpointJob)
        assert job.id == "job-1"
        assert job._data["status"] == "IN_QUEUE"
        assert job.done is False

    @pytest.mark.asyncio
    async def test_run_with_webhook(self):
        ep = Endpoint(id="ep-123")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-123"

        client = _mock_httpx_client(post_return={"id": "job-1", "status": "IN_QUEUE"})

        with patch(_HTTP_CLIENT, return_value=client):
            await ep.run({"prompt": "hello"}, webhook="https://example.com/hook")

        client.post.assert_called_once_with(
            "https://api.runpod.ai/v2/ep-123/run",
            json={
                "input": {"prompt": "hello"},
                "webhook": "https://example.com/hook",
            },
        )

    @pytest.mark.asyncio
    async def test_run_posts_to_run_url(self):
        ep = Endpoint(id="ep-123")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-123"

        client = _mock_httpx_client(post_return={"id": "j", "status": "IN_QUEUE"})

        with patch(_HTTP_CLIENT, return_value=client):
            await ep.run({"x": 1})

        client.post.assert_called_once_with(
            "https://api.runpod.ai/v2/ep-123/run",
            json={"input": {"x": 1}},
        )


class TestEndpointRunsync:
    @pytest.mark.asyncio
    async def test_runsync_returns_endpoint_job(self):
        ep = Endpoint(id="ep-123")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-123"

        client = _mock_httpx_client(
            post_return={
                "id": "job-1",
                "status": "COMPLETED",
                "output": {"text": "world"},
            }
        )

        with patch(_HTTP_CLIENT, return_value=client):
            job = await ep.runsync({"prompt": "hello"})

        assert isinstance(job, EndpointJob)
        assert job._data["status"] == "COMPLETED"
        assert job.output == {"text": "world"}
        assert job.done is True

    @pytest.mark.asyncio
    async def test_runsync_custom_timeout(self):
        ep = Endpoint(id="ep-123")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-123"

        client = _mock_httpx_client(post_return={"id": "j", "status": "COMPLETED"})

        with patch(_HTTP_CLIENT, return_value=client) as mock_factory:
            await ep.runsync({"prompt": "hello"}, timeout=120.0)
            mock_factory.assert_called_once_with(timeout=120.0)


class TestEndpointCancel:
    @pytest.mark.asyncio
    async def test_cancel_returns_endpoint_job(self):
        ep = Endpoint(id="ep-123")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-123"

        client = _mock_httpx_client(post_return={"id": "job-1", "status": "CANCELLED"})

        with patch(_HTTP_CLIENT, return_value=client):
            job = await ep.cancel("job-1")

        assert isinstance(job, EndpointJob)
        assert job._data["status"] == "CANCELLED"
        assert job.done is True


# -- Endpoint._ensure_endpoint_ready --


class TestEnsureEndpointReadyIdMode:
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
        mock_rm.get_or_deploy_resource.assert_called_once()


# -- LB client requests --


class TestClientRequest:
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

    @pytest.mark.asyncio
    async def test_custom_timeout(self):
        ep = Endpoint(id="ep-123")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-123"

        client = _mock_httpx_client(request_return={})

        with patch(_HTTP_CLIENT, return_value=client) as mock_factory:
            await ep.post("/run", {}, timeout=120.0)
            mock_factory.assert_called_once_with(timeout=120.0)


# -- end-to-end flows --


class TestEndToEndFlow:
    @pytest.mark.asyncio
    async def test_run_then_wait(self):
        ep = Endpoint(id="ep-999")
        ep._endpoint_url = "https://api.runpod.ai/v2/ep-999"

        run_client = _mock_httpx_client(
            post_return={"id": "job-42", "status": "IN_QUEUE"}
        )

        poll_responses = [
            {"id": "job-42", "status": "IN_PROGRESS"},
            {"id": "job-42", "status": "COMPLETED", "output": "done"},
        ]
        poll_idx = 0

        def make_poll_response():
            nonlocal poll_idx
            resp = MagicMock()
            resp.json.return_value = poll_responses[
                min(poll_idx, len(poll_responses) - 1)
            ]
            resp.raise_for_status = MagicMock()
            poll_idx += 1
            return resp

        poll_client = AsyncMock()
        poll_client.get = AsyncMock(side_effect=lambda *a, **kw: make_poll_response())
        poll_client.__aenter__ = AsyncMock(return_value=poll_client)
        poll_client.__aexit__ = AsyncMock(return_value=None)

        with patch(_HTTP_CLIENT, return_value=run_client):
            job = await ep.run({"prompt": "hello"})

        with patch(_HTTP_CLIENT, return_value=poll_client):
            await job.wait()

        assert job._data["status"] == "COMPLETED"
        assert job.output == "done"

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


# -- public import --


class TestEndpointJobImport:
    def test_import_from_package(self):
        from runpod_flash import EndpointJob as EJ

        assert EJ.__name__ == "EndpointJob"

    def test_in_all(self):
        import runpod_flash

        assert "EndpointJob" in runpod_flash.__all__
