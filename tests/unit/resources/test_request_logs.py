from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from runpod_flash.core.resources.request_logs import (
    QBRequestLogFetcher,
    QBRequestLogPhase,
)


def _make_async_client(mock_client: MagicMock) -> MagicMock:
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


@pytest.mark.asyncio
async def test_waiting_for_workers_when_none_running_or_initializing():
    fetcher = QBRequestLogFetcher(start_time=datetime(2026, 1, 1, tzinfo=timezone.utc))

    status_response = MagicMock()
    status_response.raise_for_status = MagicMock()
    status_response.json.return_value = {"status": "IN_QUEUE"}

    metrics_response = MagicMock()
    metrics_response.raise_for_status = MagicMock()
    metrics_response.json.return_value = {
        "workers": {"initializing": 0},
        "readyWorkers": [],
    }

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=[status_response, metrics_response])

    with patch(
        "runpod_flash.core.resources.request_logs.get_authenticated_httpx_client",
        return_value=_make_async_client(mock_client),
    ):
        batch = await fetcher.fetch_logs(
            endpoint_id="endpoint-1",
            request_id="request-1",
            status_api_key="status-key",
            pod_logs_api_key="runpod-key",
        )

    assert batch.phase == QBRequestLogPhase.WAITING_FOR_WORKER
    assert batch.worker_id is None
    assert batch.lines == []


@pytest.mark.asyncio
async def test_waiting_for_worker_initialization_when_workers_initializing():
    fetcher = QBRequestLogFetcher()

    status_response = MagicMock()
    status_response.raise_for_status = MagicMock()
    status_response.json.return_value = {"status": "IN_QUEUE"}

    metrics_response = MagicMock()
    metrics_response.raise_for_status = MagicMock()
    metrics_response.json.return_value = {
        "workers": {"initializing": 1},
        "readyWorkers": [],
    }

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=[status_response, metrics_response])

    with patch(
        "runpod_flash.core.resources.request_logs.get_authenticated_httpx_client",
        return_value=_make_async_client(mock_client),
    ):
        batch = await fetcher.fetch_logs(
            endpoint_id="endpoint-1",
            request_id="request-1",
            status_api_key="status-key",
            pod_logs_api_key="runpod-key",
        )

    assert batch.phase == QBRequestLogPhase.WAITING_FOR_WORKER_INITIALIZATION
    assert batch.worker_id is None
    assert batch.lines == []


@pytest.mark.asyncio
async def test_primes_existing_worker_logs_then_streams_new_lines():
    fetcher = QBRequestLogFetcher(
        start_time=datetime(2026, 4, 2, 17, 14, 7, tzinfo=timezone.utc),
        lookback_seconds=20,
    )

    status_1 = MagicMock()
    status_1.raise_for_status = MagicMock()
    status_1.json.return_value = {"status": "IN_QUEUE"}

    metrics_1 = MagicMock()
    metrics_1.raise_for_status = MagicMock()
    metrics_1.json.return_value = {
        "workers": {"initializing": 0, "running": 1},
        "readyWorkers": ["worker-running-1"],
    }

    old_logs = MagicMock()
    old_logs.raise_for_status = MagicMock()
    old_logs.json.return_value = {
        "container": ["2026-04-02T17:14:05Z create container"],
        "system": [
            "2026-04-02T16:38:18Z very old line",
            '{"requestId": "request-1", "message": "Started.", "level": "INFO"}',
            "ae1225 smoke: worker started",
        ],
    }

    status_2 = MagicMock()
    status_2.raise_for_status = MagicMock()
    status_2.json.return_value = {"status": "IN_QUEUE"}

    metrics_2 = MagicMock()
    metrics_2.raise_for_status = MagicMock()
    metrics_2.json.return_value = {
        "workers": {"initializing": 0, "running": 1},
        "readyWorkers": ["worker-running-1"],
    }

    new_logs = MagicMock()
    new_logs.raise_for_status = MagicMock()
    new_logs.json.return_value = {
        "container": ["2026-04-02T17:14:08Z start container"],
        "system": ["2026-04-02T17:14:05Z create container"],
    }

    mock_client = MagicMock()
    mock_client.get = AsyncMock(
        side_effect=[status_1, metrics_1, old_logs, status_2, metrics_2, new_logs]
    )

    with patch(
        "runpod_flash.core.resources.request_logs.get_authenticated_httpx_client",
        return_value=_make_async_client(mock_client),
    ):
        first_batch = await fetcher.fetch_logs(
            endpoint_id="endpoint-1",
            request_id="request-1",
            status_api_key="endpoint-ai-key",
            pod_logs_api_key="runpod-key",
        )
        second_batch = await fetcher.fetch_logs(
            endpoint_id="endpoint-1",
            request_id="request-1",
            status_api_key="endpoint-ai-key",
            pod_logs_api_key="runpod-key",
        )

    assert first_batch.worker_id == "worker-running-1"
    assert first_batch.phase == QBRequestLogPhase.STREAMING
    assert first_batch.lines == [
        '{"requestId": "request-1", "message": "Started.", "level": "INFO"}',
        "2026-04-02T17:14:05Z create container",
    ]

    assert second_batch.worker_id == "worker-running-1"
    assert second_batch.phase == QBRequestLogPhase.STREAMING
    assert second_batch.lines == ["2026-04-02T17:14:08Z start container"]
    assert second_batch.matched_by_request_id is False


@pytest.mark.asyncio
async def test_status_uses_fallback_key_on_401():
    fetcher = QBRequestLogFetcher()

    unauthorized = httpx.Response(
        status_code=401,
        request=httpx.Request(
            "GET", "https://api.runpod.ai/v2/endpoint-1/status/request-1"
        ),
    )

    status_response = MagicMock()
    status_response.raise_for_status = MagicMock()
    status_response.json.return_value = {"workerId": "worker-123"}

    metrics_response = MagicMock()
    metrics_response.raise_for_status = MagicMock()
    metrics_response.json.return_value = {
        "workers": {"initializing": 0, "running": 1},
        "readyWorkers": ["worker-123"],
    }

    pod_logs_response = MagicMock()
    pod_logs_response.raise_for_status = MagicMock()
    pod_logs_response.json.return_value = {"container": ["old"], "system": []}

    status_response_2 = MagicMock()
    status_response_2.raise_for_status = MagicMock()
    status_response_2.json.return_value = {"workerId": "worker-123"}

    metrics_response_2 = MagicMock()
    metrics_response_2.raise_for_status = MagicMock()
    metrics_response_2.json.return_value = {
        "workers": {"initializing": 0, "running": 1},
        "readyWorkers": ["worker-123"],
    }

    pod_logs_response_2 = MagicMock()
    pod_logs_response_2.raise_for_status = MagicMock()
    pod_logs_response_2.json.return_value = {"container": ["new"], "system": []}

    mock_client = MagicMock()
    mock_client.get = AsyncMock(
        side_effect=[
            httpx.HTTPStatusError(
                "unauthorized", request=unauthorized.request, response=unauthorized
            ),
            status_response,
            metrics_response,
            pod_logs_response,
            status_response_2,
            metrics_response_2,
            pod_logs_response_2,
        ]
    )

    with patch(
        "runpod_flash.core.resources.request_logs.get_authenticated_httpx_client",
        return_value=_make_async_client(mock_client),
    ):
        await fetcher.fetch_logs(
            endpoint_id="endpoint-1",
            request_id="request-1",
            status_api_key="endpoint-ai-key",
            pod_logs_api_key="runpod-key",
            status_api_key_fallback="runpod-key",
        )
        second_batch = await fetcher.fetch_logs(
            endpoint_id="endpoint-1",
            request_id="request-1",
            status_api_key="endpoint-ai-key",
            pod_logs_api_key="runpod-key",
            status_api_key_fallback="runpod-key",
        )

    assert second_batch.worker_id == "worker-123"
    assert second_batch.phase == QBRequestLogPhase.STREAMING
    assert second_batch.lines == ["new"]
