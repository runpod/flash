"""Tests for Pod HTTP client: PodResponse and Pod.get/post/put/delete."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runpod_flash.core.exceptions import PodRequestError
from runpod_flash.core.resources.pod import Pod, PodResponse


# ---------------------------------------------------------------------------
# PodResponse
# ---------------------------------------------------------------------------


class TestPodResponse:
    """Tests for the PodResponse dataclass."""

    def test_ok_for_2xx(self) -> None:
        for code in (200, 201, 204, 299):
            resp = PodResponse(status_code=code, headers={}, body=b"", json_data=None)
            assert resp.ok is True

    def test_not_ok_for_non_2xx(self) -> None:
        for code in (400, 404, 500, 503):
            resp = PodResponse(
                status_code=code, headers={}, body=b"error", json_data=None
            )
            assert resp.ok is False

    def test_raise_for_status_on_error(self) -> None:
        resp = PodResponse(
            status_code=500, headers={}, body=b"server error", json_data=None
        )
        with pytest.raises(PodRequestError) as exc_info:
            resp.raise_for_status()
        assert exc_info.value.status_code == 500

    def test_raise_for_status_ok(self) -> None:
        resp = PodResponse(
            status_code=200, headers={}, body=b"ok", json_data={"result": 1}
        )
        resp.raise_for_status()  # should not raise


# ---------------------------------------------------------------------------
# Pod HTTP Client
# ---------------------------------------------------------------------------


def _make_mock_httpx_response(
    status_code: int = 200,
    headers: dict[str, str] | None = None,
    content: bytes = b'{"ok": true}',
    content_type: str = "application/json",
) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"content-type": content_type, **(headers or {})}
    resp.content = content
    resp.json.return_value = {"ok": True}
    return resp


def _make_pod_with_registry(
    resolve_url: str = "http://10.0.0.1:8080",
) -> tuple[Pod, AsyncMock]:
    """Create a Pod with a mocked registry."""
    pod = Pod(name="gpu-worker", image="pytorch:latest", gpu="A100")
    registry = AsyncMock()
    registry.resolve = AsyncMock(return_value=resolve_url)
    pod._bind_registry(registry)
    return pod, registry


class TestPodHttpClient:
    """Tests for Pod HTTP convenience methods."""

    @pytest.mark.asyncio
    async def test_get_request(self) -> None:
        pod, registry = _make_pod_with_registry("http://10.0.0.1:8080")
        mock_response = _make_mock_httpx_response()

        with patch(
            "runpod_flash.core.resources.pod.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await pod.get("/health")

        registry.resolve.assert_awaited_once_with("gpu-worker")
        mock_client.request.assert_awaited_once_with(
            "GET", "http://10.0.0.1:8080/health"
        )
        assert isinstance(result, PodResponse)
        assert result.status_code == 200
        assert result.ok is True
        assert result.json_data == {"ok": True}

    @pytest.mark.asyncio
    async def test_post_request(self) -> None:
        pod, registry = _make_pod_with_registry("http://10.0.0.1:8080")
        mock_response = _make_mock_httpx_response(status_code=201)

        with patch(
            "runpod_flash.core.resources.pod.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await pod.post("/predict", json={"input": "data"})

        mock_client.request.assert_awaited_once_with(
            "POST",
            "http://10.0.0.1:8080/predict",
            json={"input": "data"},
        )
        assert result.status_code == 201
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_put_request(self) -> None:
        pod, registry = _make_pod_with_registry("http://10.0.0.1:8080/")
        mock_response = _make_mock_httpx_response()

        with patch(
            "runpod_flash.core.resources.pod.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await pod.put("/config", json={"key": "value"})

        # Verify trailing slash on base_url and leading slash on path are normalized
        mock_client.request.assert_awaited_once_with(
            "PUT",
            "http://10.0.0.1:8080/config",
            json={"key": "value"},
        )
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_delete_request(self) -> None:
        pod, registry = _make_pod_with_registry()
        mock_response = _make_mock_httpx_response(status_code=204, content=b"")

        with patch(
            "runpod_flash.core.resources.pod.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await pod.delete("/resource/123")

        assert result.status_code == 204
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_no_registry_raises(self) -> None:
        pod = Pod(name="orphan", image="ubuntu:latest")
        with pytest.raises(RuntimeError, match="no registry bound"):
            await pod.get("/anything")

    @pytest.mark.asyncio
    async def test_non_json_response(self) -> None:
        pod, _ = _make_pod_with_registry()
        mock_response = _make_mock_httpx_response(
            content_type="text/plain", content=b"plain text"
        )

        with patch(
            "runpod_flash.core.resources.pod.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await pod.get("/logs")

        assert result.json_data is None
        assert result.body == b"plain text"
