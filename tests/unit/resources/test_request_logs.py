from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runpod_flash.core.resources.request_logs import QBRequestLogFetcher


def _make_async_client(mock_client: MagicMock) -> MagicMock:
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


@pytest.mark.asyncio
async def test_fetch_for_request_matches_request_id_lines():
    fetcher = QBRequestLogFetcher(max_lines=5, fallback_tail_lines=3)

    status_response = MagicMock()
    status_response.raise_for_status = MagicMock()
    status_response.json.return_value = {"workerId": "pod-123"}

    logs_response = MagicMock()
    logs_response.raise_for_status = MagicMock()
    logs_response.json.return_value = {
        "data": [
            {"message": "line a"},
            {"message": "request-42 started"},
            {"message": "line c"},
            {"message": "request-42 done"},
        ]
    }

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=[status_response, logs_response])

    with patch(
        "runpod_flash.core.resources.request_logs.get_authenticated_httpx_client",
        return_value=_make_async_client(mock_client),
    ):
        batch = await fetcher.fetch_for_request(
            "endpoint-1",
            "request-42",
            runpod_api_key="rp-key",
            endpoint_ai_key="ai-key",
        )

    assert batch is not None
    assert batch.worker_id == "pod-123"
    assert batch.matched_by_request_id is True
    assert batch.lines == ["request-42 started", "request-42 done"]


@pytest.mark.asyncio
async def test_fetch_for_request_falls_back_to_tail_lines_when_no_match():
    fetcher = QBRequestLogFetcher(max_lines=5, fallback_tail_lines=2)

    status_response = MagicMock()
    status_response.raise_for_status = MagicMock()
    status_response.json.return_value = {"workerId": "pod-123"}

    logs_response = MagicMock()
    logs_response.raise_for_status = MagicMock()
    logs_response.json.return_value = {
        "data": [
            {"message": "one"},
            {"message": "two"},
            {"message": "three"},
            {"message": "four"},
        ]
    }

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=[status_response, logs_response])

    with patch(
        "runpod_flash.core.resources.request_logs.get_authenticated_httpx_client",
        return_value=_make_async_client(mock_client),
    ):
        batch = await fetcher.fetch_for_request(
            "endpoint-1",
            "request-42",
            runpod_api_key="rp-key",
            endpoint_ai_key="ai-key",
        )

    assert batch is not None
    assert batch.worker_id == "pod-123"
    assert batch.matched_by_request_id is False
    assert batch.lines == ["three", "four"]


@pytest.mark.asyncio
async def test_fetch_for_request_returns_none_when_worker_id_missing():
    fetcher = QBRequestLogFetcher()

    status_response = MagicMock()
    status_response.raise_for_status = MagicMock()
    status_response.json.return_value = {}

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=status_response)

    with patch(
        "runpod_flash.core.resources.request_logs.get_authenticated_httpx_client",
        return_value=_make_async_client(mock_client),
    ):
        batch = await fetcher.fetch_for_request(
            "endpoint-1",
            "request-42",
            runpod_api_key="rp-key",
            endpoint_ai_key="ai-key",
        )

    assert batch is None
    assert mock_client.get.await_count == 1


@pytest.mark.asyncio
async def test_fetch_for_request_returns_empty_lines_without_ai_key():
    fetcher = QBRequestLogFetcher()

    status_response = MagicMock()
    status_response.raise_for_status = MagicMock()
    status_response.json.return_value = {"workerId": "pod-123"}

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=status_response)

    with patch(
        "runpod_flash.core.resources.request_logs.get_authenticated_httpx_client",
        return_value=_make_async_client(mock_client),
    ):
        batch = await fetcher.fetch_for_request(
            "endpoint-1",
            "request-42",
            runpod_api_key="rp-key",
            endpoint_ai_key=None,
        )

    assert batch is not None
    assert batch.worker_id == "pod-123"
    assert batch.lines == []
    assert batch.matched_by_request_id is False
    assert mock_client.get.await_count == 1


@pytest.mark.asyncio
async def test_endpoint_log_fetch_uses_v2_with_aikey_bearer_auth():
    fetcher = QBRequestLogFetcher()

    status_response = MagicMock()
    status_response.raise_for_status = MagicMock()
    status_response.json.return_value = {"workerId": "pod-123"}

    logs_response = MagicMock()
    logs_response.raise_for_status = MagicMock()
    logs_response.json.return_value = {"data": []}

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=[status_response, logs_response])

    with patch(
        "runpod_flash.core.resources.request_logs.get_authenticated_httpx_client",
        return_value=_make_async_client(mock_client),
    ) as mock_client_factory:
        await fetcher.fetch_for_request(
            "endpoint-1",
            "request-42",
            runpod_api_key="rp-key",
            endpoint_ai_key="ai-key-123",
        )

    log_call = mock_client.get.await_args_list[1]
    assert log_call.args[0] == "https://api.runpod.ai/v2/endpoint-1/logs"
    assert "from" in log_call.kwargs["params"]
    assert "to" in log_call.kwargs["params"]
    assert "aikey" not in log_call.kwargs["params"]
    assert (
        mock_client_factory.call_args_list[1].kwargs["api_key_override"] == "ai-key-123"
    )
