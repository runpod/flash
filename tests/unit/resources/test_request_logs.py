from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from runpod_flash.core.resources.request_logs import (
    QBRequestLogBatch,
    QBRequestLogFetcher,
)


def _make_async_client(mock_client: MagicMock) -> MagicMock:
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


@pytest.mark.asyncio
async def test_fetch_logs_returns_batch_with_chronological_unique_lines():
    fetcher = QBRequestLogFetcher(
        max_lines=5,
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    logs_response = MagicMock()
    logs_response.raise_for_status = MagicMock()
    logs_response.json.return_value = {
        "data": [
            {"message": "line two", "dt": "2026-01-01T00:00:02Z"},
            {"message": "line one", "dt": "2026-01-01T00:00:01Z"},
            {"message": "line two", "dt": "2026-01-01T00:00:02Z"},
        ]
    }

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=logs_response)

    with patch(
        "runpod_flash.core.resources.request_logs.get_authenticated_httpx_client",
        return_value=_make_async_client(mock_client),
    ):
        batch = await fetcher.fetch_logs(
            endpoint_id="endpoint-1",
            endpoint_ai_key="ai-key",
        )

    assert isinstance(batch, QBRequestLogBatch)
    assert batch is not None
    assert batch.matched_by_request_id is False
    assert batch.worker_id is None
    assert batch.lines == ["line one", "line two"]


@pytest.mark.asyncio
async def test_fetch_logs_dedupes_seen_lines_across_calls():
    fetcher = QBRequestLogFetcher(
        max_lines=5,
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    first_logs_response = MagicMock()
    first_logs_response.raise_for_status = MagicMock()
    first_logs_response.json.return_value = {
        "data": [
            {"message": "line two"},
            {"message": "line one"},
        ]
    }

    second_logs_response = MagicMock()
    second_logs_response.raise_for_status = MagicMock()
    second_logs_response.json.return_value = {
        "data": [
            {"message": "line three"},
            {"message": "line two"},
        ]
    }

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=[first_logs_response, second_logs_response])

    with patch(
        "runpod_flash.core.resources.request_logs.get_authenticated_httpx_client",
        return_value=_make_async_client(mock_client),
    ):
        first_batch = await fetcher.fetch_logs("endpoint-1", "ai-key")
        second_batch = await fetcher.fetch_logs("endpoint-1", "ai-key")

    assert first_batch is not None
    assert first_batch.lines == ["line one", "line two"]
    assert second_batch is not None
    assert second_batch.lines == ["line three"]


@pytest.mark.asyncio
async def test_fetch_logs_returns_none_on_http_error():
    fetcher = QBRequestLogFetcher()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=httpx.ReadTimeout("timed out"))

    with patch(
        "runpod_flash.core.resources.request_logs.get_authenticated_httpx_client",
        return_value=_make_async_client(mock_client),
    ):
        batch = await fetcher.fetch_logs(
            endpoint_id="endpoint-1",
            endpoint_ai_key="ai-key",
        )

    assert batch is None


@pytest.mark.asyncio
async def test_endpoint_log_fetch_uses_v2_with_aikey_bearer_auth():
    fetcher = QBRequestLogFetcher()

    logs_response = MagicMock()
    logs_response.raise_for_status = MagicMock()
    logs_response.json.return_value = {"data": []}

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=logs_response)

    with patch(
        "runpod_flash.core.resources.request_logs.get_authenticated_httpx_client",
        return_value=_make_async_client(mock_client),
    ) as mock_client_factory:
        await fetcher.fetch_logs(
            endpoint_id="endpoint-1",
            endpoint_ai_key="ai-key-123",
        )

    log_call = mock_client.get.await_args_list[0]
    assert log_call.args[0] == "https://api.runpod.ai/v2/endpoint-1/logs"
    assert "from" in log_call.kwargs["params"]
    assert "to" in log_call.kwargs["params"]
    assert "aikey" not in log_call.kwargs["params"]
    assert mock_client_factory.call_args.kwargs["api_key_override"] == "ai-key-123"
