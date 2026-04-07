from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runpod_flash.core.resources.cpu import CpuInstanceType
from runpod_flash.core.resources.serverless import ServerlessResource
from runpod_flash.core.resources.worker_availability_diagnostic import (
    WorkerAvailabilityDiagnostic,
)


def _make_client_context(mock_client: MagicMock) -> MagicMock:
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


@pytest.mark.asyncio
async def test_diagnose_returns_workers_max_zero_message():
    resource = ServerlessResource(name="test", workersMax=0)

    diagnostic = WorkerAvailabilityDiagnostic()
    result = await diagnostic.diagnose(resource)

    assert result.has_availability is False
    assert "max workers are currently set to 0" in result.message
    assert result.reason == "workers_max_zero"


@pytest.mark.asyncio
async def test_diagnose_gpu_no_availability_includes_selected_locations():
    resource = ServerlessResource(name="test")
    resource.gpuIds = "NVIDIA GeForce RTX 4090"
    resource.locations = "EU-RO-1,US-GA-2"

    mock_client = MagicMock()
    mock_client.get_gpu_lowest_price_stock_status = AsyncMock(side_effect=[None, None])

    with patch(
        "runpod_flash.core.resources.worker_availability_diagnostic.RunpodGraphQLClient",
        return_value=_make_client_context(mock_client),
    ):
        result = await WorkerAvailabilityDiagnostic().diagnose(resource)

    assert result.has_availability is False
    assert (
        "No workers available on endpoint: no gpu availability for gpu type NVIDIA GeForce RTX 4090"
        in result.message
    )
    assert "EU-RO-1, US-GA-2" in result.message
    assert result.reason == "no_gpu_availability"


@pytest.mark.asyncio
async def test_diagnose_gpu_availability_shows_signal_without_locations():
    resource = ServerlessResource(name="test")
    resource.gpuIds = "NVIDIA GeForce RTX 4090"
    resource.locations = "EU-RO-1,US-GA-2"

    mock_client = MagicMock()
    mock_client.get_gpu_lowest_price_stock_status = AsyncMock(side_effect=[None, "Low"])

    with patch(
        "runpod_flash.core.resources.worker_availability_diagnostic.RunpodGraphQLClient",
        return_value=_make_client_context(mock_client),
    ):
        result = await WorkerAvailabilityDiagnostic().diagnose(resource)

    assert result.has_availability is True
    assert (
        "Current availability signal for selected gpu NVIDIA GeForce RTX 4090: Low"
        in result.message
    )
    assert "EU-RO-1" not in result.message
    assert "US-GA-2" not in result.message
    assert result.reason == "gpu_has_availability"


@pytest.mark.asyncio
async def test_diagnose_cpu_no_availability_message():
    resource = ServerlessResource(name="test")
    resource.instanceIds = [CpuInstanceType.CPU3G_2_8]
    resource.locations = "EU-RO-1,US-GA-2"

    mock_client = MagicMock()
    mock_client.get_cpu_specific_stock_status = AsyncMock(side_effect=[None, None])

    with patch(
        "runpod_flash.core.resources.worker_availability_diagnostic.RunpodGraphQLClient",
        return_value=_make_client_context(mock_client),
    ):
        result = await WorkerAvailabilityDiagnostic().diagnose(resource)

    assert result.has_availability is False
    assert (
        "No workers available on endpoint: no cpu availability for cpu type cpu3g-2-8"
        in result.message
    )
    assert "EU-RO-1, US-GA-2" in result.message
    assert result.reason == "no_cpu_availability"


@pytest.mark.asyncio
async def test_diagnose_prefers_throttled_reason_over_no_availability():
    resource = ServerlessResource(name="test")
    resource.gpuIds = "NVIDIA GeForce RTX 4090"

    result = await WorkerAvailabilityDiagnostic().diagnose(
        resource,
        worker_metrics={"throttled": 3},
    )

    assert result.has_availability is True
    assert result.reason == "workers_throttled"
    assert "Workers are currently throttled on endpoint" in result.message
    assert "Consider raising max workers or changing gpu type" in result.message


@pytest.mark.asyncio
async def test_diagnose_cpu_throttled_message_references_cpu_type():
    resource = ServerlessResource(name="test")
    resource.instanceIds = [CpuInstanceType.CPU3G_2_8]

    result = await WorkerAvailabilityDiagnostic().diagnose(
        resource,
        worker_metrics={"throttled": 2},
    )

    assert result.reason == "workers_throttled"
    assert "changing cpu type" in result.message


@pytest.mark.asyncio
async def test_diagnose_treats_out_of_stock_as_unavailable():
    resource = ServerlessResource(name="test")
    resource.gpuIds = "NVIDIA GeForce RTX 4090"

    mock_client = MagicMock()
    mock_client.get_gpu_lowest_price_stock_status = AsyncMock(
        side_effect=["OUT_OF_STOCK"]
    )

    with patch(
        "runpod_flash.core.resources.worker_availability_diagnostic.RunpodGraphQLClient",
        return_value=_make_client_context(mock_client),
    ):
        result = await WorkerAvailabilityDiagnostic().diagnose(resource)

    assert result.has_availability is False
    assert result.reason == "no_gpu_availability"
