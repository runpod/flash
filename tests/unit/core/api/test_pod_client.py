"""Tests for PodApiClient, PortMapping, and PodApiResponse."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from runpod_flash.core.api.pod_client import PodApiClient, PodApiResponse, PortMapping
from runpod_flash.core.exceptions import PodRequestError
from runpod_flash.core.resources.pod import Pod, PodConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_raw_pod(
    pod_id: str = "pod-abc123",
    name: str = "test-pod",
    desired_status: str = "RUNNING",
    image_name: str = "runpod/pytorch:latest",
    cost_per_hr: float = 0.39,
    uptime_seconds: int = 3600,
    gpu_display_name: str | None = "RTX 4090",
    machine_id: str | None = "machine-xyz",
    ports: list[dict] | None = None,
) -> dict:
    """Build a raw GraphQL pod response dict."""
    if ports is None:
        ports = [
            {
                "ip": "1.2.3.4",
                "isIpPublic": True,
                "privatePort": 8080,
                "publicPort": 18080,
                "type": "http",
            }
        ]
    return {
        "id": pod_id,
        "name": name,
        "desiredStatus": desired_status,
        "imageName": image_name,
        "costPerHr": cost_per_hr,
        "uptimeSeconds": uptime_seconds,
        "machine": {
            "podHostId": machine_id,
            "gpuDisplayName": gpu_display_name,
        },
        "runtime": {"ports": ports},
    }


@pytest.fixture()
def client() -> PodApiClient:
    return PodApiClient(api_key="test-api-key")


@pytest.fixture()
def gpu_pod() -> Pod:
    return Pod(
        name="my-gpu-pod",
        image="runpod/pytorch:latest",
        gpu="NVIDIA RTX 4090",
        env={"MODEL": "llama"},
        config=PodConfig(
            gpu_count=1,
            ports=["8080/http", "22/tcp"],
            container_disk_in_gb=20,
        ),
    )


@pytest.fixture()
def cpu_pod() -> Pod:
    return Pod(
        name="my-cpu-pod",
        image="runpod/base:latest",
        gpu=None,
        env={"MODE": "cpu"},
        config=PodConfig(
            ports=["8080/http"],
            container_disk_in_gb=10,
        ),
    )


# ---------------------------------------------------------------------------
# TestPortMapping
# ---------------------------------------------------------------------------


class TestPortMapping:
    def test_construction(self) -> None:
        pm = PortMapping(host_ip="10.0.0.1", host_port=8080, protocol="http")
        assert pm.host_ip == "10.0.0.1"
        assert pm.host_port == 8080
        assert pm.protocol == "http"

    def test_frozen(self) -> None:
        pm = PortMapping(host_ip="10.0.0.1", host_port=8080, protocol="tcp")
        with pytest.raises(AttributeError):
            pm.host_ip = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestPodApiResponse
# ---------------------------------------------------------------------------


class TestPodApiResponse:
    def test_construction(self) -> None:
        ports = {
            "8080": PortMapping(host_ip="1.2.3.4", host_port=18080, protocol="http")
        }
        resp = PodApiResponse(
            pod_id="pod-1",
            name="test",
            desired_status="RUNNING",
            image_name="img:latest",
            gpu_display_name="RTX 4090",
            public_ip="1.2.3.4",
            ports=ports,
            cost_per_hr=0.39,
            uptime_seconds=100,
            machine_id="m-1",
        )
        assert resp.pod_id == "pod-1"
        assert resp.cost_per_hr == 0.39
        assert resp.ports is not None
        assert resp.ports["8080"].host_port == 18080

    def test_optional_fields_none(self) -> None:
        resp = PodApiResponse(
            pod_id="pod-2",
            name="bare",
            desired_status="EXITED",
            image_name="img:v1",
            gpu_display_name=None,
            public_ip=None,
            ports=None,
            cost_per_hr=0.0,
            uptime_seconds=0,
            machine_id=None,
        )
        assert resp.gpu_display_name is None
        assert resp.public_ip is None
        assert resp.ports is None
        assert resp.machine_id is None


# ---------------------------------------------------------------------------
# TestPodApiClientCreate
# ---------------------------------------------------------------------------


class TestPodApiClientCreate:
    @pytest.mark.asyncio()
    async def test_gpu_pod_uses_correct_mutation(
        self, client: PodApiClient, gpu_pod: Pod
    ) -> None:
        raw = _make_raw_pod()
        mock_execute = AsyncMock(return_value={"podFindAndDeployOnDemand": raw})
        with patch.object(client, "_execute_graphql", mock_execute):
            result = await client.create(gpu_pod)

        assert result.pod_id == "pod-abc123"
        call_query = mock_execute.call_args[0][0]
        assert "podFindAndDeployOnDemand" in call_query
        assert "gpuTypeId" in call_query

    @pytest.mark.asyncio()
    async def test_cpu_pod_uses_correct_mutation(
        self, client: PodApiClient, cpu_pod: Pod
    ) -> None:
        raw = _make_raw_pod(gpu_display_name=None)
        mock_execute = AsyncMock(return_value={"deployCpuPod": raw})
        with patch.object(client, "_execute_graphql", mock_execute):
            result = await client.create(cpu_pod)

        assert result.pod_id == "pod-abc123"
        call_query = mock_execute.call_args[0][0]
        assert "deployCpuPod" in call_query
        assert "gpuTypeId" not in call_query

    @pytest.mark.asyncio()
    async def test_ports_converted_to_comma_string(
        self, client: PodApiClient, gpu_pod: Pod
    ) -> None:
        raw = _make_raw_pod()
        mock_execute = AsyncMock(return_value={"podFindAndDeployOnDemand": raw})
        with patch.object(client, "_execute_graphql", mock_execute):
            await client.create(gpu_pod)

        call_query = mock_execute.call_args[0][0]
        # ports_str joins with comma: "8080/http,22/tcp"
        assert "8080/http,22/tcp" in call_query


# ---------------------------------------------------------------------------
# TestPodApiClientLifecycle
# ---------------------------------------------------------------------------


class TestPodApiClientLifecycle:
    @pytest.mark.asyncio()
    async def test_get(self, client: PodApiClient) -> None:
        raw = _make_raw_pod(pod_id="pod-get-1")
        mock_execute = AsyncMock(return_value={"pod": raw})
        with patch.object(client, "_execute_graphql", mock_execute):
            result = await client.get("pod-get-1")

        assert result.pod_id == "pod-get-1"
        call_query = mock_execute.call_args[0][0]
        assert "pod-get-1" in call_query

    @pytest.mark.asyncio()
    async def test_list_pods(self, client: PodApiClient) -> None:
        raw_pods = [_make_raw_pod(pod_id="p1"), _make_raw_pod(pod_id="p2")]
        mock_execute = AsyncMock(return_value={"myself": {"pods": raw_pods}})
        with patch.object(client, "_execute_graphql", mock_execute):
            results = await client.list_pods()

        assert len(results) == 2
        assert results[0].pod_id == "p1"
        assert results[1].pod_id == "p2"

    @pytest.mark.asyncio()
    async def test_stop(self, client: PodApiClient) -> None:
        mock_execute = AsyncMock(return_value={"podStop": None})
        with patch.object(client, "_execute_graphql", mock_execute):
            await client.stop("pod-stop-1")

        call_query = mock_execute.call_args[0][0]
        assert "podStop" in call_query
        assert "pod-stop-1" in call_query

    @pytest.mark.asyncio()
    async def test_resume(self, client: PodApiClient) -> None:
        raw = _make_raw_pod(pod_id="pod-resume-1")
        mock_execute = AsyncMock(return_value={"podResume": raw})
        with patch.object(client, "_execute_graphql", mock_execute):
            result = await client.resume("pod-resume-1", gpu_count=2)

        assert result.pod_id == "pod-resume-1"
        call_query = mock_execute.call_args[0][0]
        assert "podResume" in call_query
        assert "gpuCount: 2" in call_query

    @pytest.mark.asyncio()
    async def test_terminate(self, client: PodApiClient) -> None:
        mock_execute = AsyncMock(return_value={"podTerminate": None})
        with patch.object(client, "_execute_graphql", mock_execute):
            await client.terminate("pod-term-1")

        call_query = mock_execute.call_args[0][0]
        assert "podTerminate" in call_query
        assert "pod-term-1" in call_query

    @pytest.mark.asyncio()
    async def test_execute_graphql_raises_on_errors(self, client: PodApiClient) -> None:
        """Verify _execute_graphql raises PodRequestError on GraphQL errors."""
        mock_execute = AsyncMock(
            side_effect=PodRequestError(400, b"GraphQL errors: something broke")
        )
        with patch.object(client, "_execute_graphql", mock_execute):
            with pytest.raises(PodRequestError):
                await client.get("bad-pod-id")


# ---------------------------------------------------------------------------
# TestParseResponse
# ---------------------------------------------------------------------------


class TestParsePodResponse:
    def test_parses_full_response(self, client: PodApiClient) -> None:
        raw = _make_raw_pod()
        result = client._parse_pod_response(raw)

        assert result.pod_id == "pod-abc123"
        assert result.name == "test-pod"
        assert result.desired_status == "RUNNING"
        assert result.image_name == "runpod/pytorch:latest"
        assert result.gpu_display_name == "RTX 4090"
        assert result.machine_id == "machine-xyz"
        assert result.cost_per_hr == 0.39
        assert result.uptime_seconds == 3600
        assert result.public_ip == "1.2.3.4"
        assert result.ports is not None
        assert "8080" in result.ports
        assert result.ports["8080"].host_port == 18080

    def test_parses_minimal_response(self, client: PodApiClient) -> None:
        raw = _make_raw_pod(
            gpu_display_name=None,
            machine_id=None,
            ports=[],
        )
        raw["machine"] = None
        result = client._parse_pod_response(raw)

        assert result.gpu_display_name is None
        assert result.machine_id is None
        assert result.ports is None
        assert result.public_ip is None

    def test_parses_missing_runtime(self, client: PodApiClient) -> None:
        raw = _make_raw_pod()
        raw["runtime"] = None
        result = client._parse_pod_response(raw)

        assert result.ports is None
        assert result.public_ip is None
