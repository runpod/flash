"""Pod API client for Runpod GraphQL pod CRUD operations.

Provides typed dataclasses for pod responses and an async client
for creating, querying, and managing pod lifecycle via GraphQL.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import aiohttp

from runpod_flash.core.exceptions import PodRequestError
from runpod_flash.core.resources.pod import Pod

log = logging.getLogger(__name__)

RUNPOD_API_BASE_URL = os.environ.get("RUNPOD_API_BASE_URL", "https://api.runpod.io")

POD_FIELDS = """
    id
    name
    desiredStatus
    imageName
    costPerHr
    uptimeSeconds
    machine {
        podHostId
        gpuDisplayName
    }
    runtime {
        ports {
            ip
            isIpPublic
            privatePort
            publicPort
            type
        }
    }
"""


@dataclass(frozen=True, slots=True)
class PortMapping:
    """A single port mapping from the pod runtime."""

    host_ip: str
    host_port: int
    protocol: str


@dataclass(frozen=True, slots=True)
class PodApiResponse:
    """Normalized response from a Runpod pod GraphQL query."""

    pod_id: str
    name: str
    desired_status: str
    image_name: str
    gpu_display_name: str | None
    public_ip: str | None
    ports: dict[str, PortMapping] | None
    cost_per_hr: float
    uptime_seconds: int
    machine_id: str | None


class PodApiClient:
    """Async GraphQL client for Runpod pod CRUD operations.

    Uses aiohttp to POST GraphQL queries/mutations to the Runpod API.
    All methods raise PodRequestError on HTTP or GraphQL-level failures.

    Args:
        api_key: Runpod API key for Bearer authentication.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._graphql_url = (
            os.environ.get("RUNPOD_API_BASE_URL", "https://api.runpod.io") + "/graphql"
        )

    async def create(self, pod: Pod) -> PodApiResponse:
        """Create a pod via the appropriate GraphQL mutation.

        GPU pods use ``podFindAndDeployOnDemand``, CPU pods (gpu is None)
        use ``deployCpuPod``.

        Args:
            pod: Pod definition with name, image, gpu, env, and config.

        Returns:
            Parsed PodApiResponse from the API.
        """
        env_list = [{"key": k, "value": v} for k, v in pod.env.items()]
        ports_str = pod.config.ports_str

        if pod.gpu is not None:
            mutation = f"""
            mutation {{
                podFindAndDeployOnDemand(input: {{
                    name: "{pod.name}"
                    imageName: "{pod.image}"
                    gpuTypeId: "{pod.gpu}"
                    gpuCount: {pod.config.gpu_count}
                    cloudType: {pod.config.cloud_type}
                    containerDiskInGb: {pod.config.container_disk_in_gb}
                    volumeInGb: {pod.config.volume_in_gb}
                    volumeMountPath: "{pod.config.volume_mount_path}"
                    startSsh: {str(pod.config.start_ssh).lower()}
                    supportPublicIp: {str(pod.config.support_public_ip).lower()}
                    minVcpuCount: {pod.config.min_vcpu_count}
                    minMemoryInGb: {pod.config.min_memory_in_gb}
                    dockerArgs: "{pod.config.docker_args}"
                    {f'ports: "{ports_str}"' if ports_str else ""}
                    env: {self._format_env(env_list)}
                }}) {{
                    {POD_FIELDS}
                }}
            }}
            """
            data = await self._execute_graphql(mutation)
            return self._parse_pod_response(data["podFindAndDeployOnDemand"])
        else:
            mutation = f"""
            mutation {{
                deployCpuPod(input: {{
                    name: "{pod.name}"
                    imageName: "{pod.image}"
                    containerDiskInGb: {pod.config.container_disk_in_gb}
                    volumeInGb: {pod.config.volume_in_gb}
                    volumeMountPath: "{pod.config.volume_mount_path}"
                    startSsh: {str(pod.config.start_ssh).lower()}
                    supportPublicIp: {str(pod.config.support_public_ip).lower()}
                    minVcpuCount: {pod.config.min_vcpu_count}
                    minMemoryInGb: {pod.config.min_memory_in_gb}
                    dockerArgs: "{pod.config.docker_args}"
                    {f'ports: "{ports_str}"' if ports_str else ""}
                    env: {self._format_env(env_list)}
                }}) {{
                    {POD_FIELDS}
                }}
            }}
            """
            data = await self._execute_graphql(mutation)
            return self._parse_pod_response(data["deployCpuPod"])

    async def get(self, pod_id: str) -> PodApiResponse:
        """Fetch a single pod by ID.

        Args:
            pod_id: The Runpod pod identifier.

        Returns:
            Parsed PodApiResponse.
        """
        query = f"""
        query {{
            pod(input: {{ podId: "{pod_id}" }}) {{
                {POD_FIELDS}
            }}
        }}
        """
        data = await self._execute_graphql(query)
        return self._parse_pod_response(data["pod"])

    async def list_pods(self) -> list[PodApiResponse]:
        """List all pods for the authenticated user.

        Returns:
            List of PodApiResponse objects.
        """
        query = f"""
        query {{
            myself {{
                pods {{
                    {POD_FIELDS}
                }}
            }}
        }}
        """
        data = await self._execute_graphql(query)
        raw_pods = data.get("myself", {}).get("pods", [])
        return [self._parse_pod_response(p) for p in raw_pods]

    async def stop(self, pod_id: str) -> None:
        """Stop a running pod.

        Args:
            pod_id: The pod to stop.
        """
        mutation = f"""
        mutation {{
            podStop(input: {{ podId: "{pod_id}" }})
        }}
        """
        await self._execute_graphql(mutation)

    async def resume(self, pod_id: str, gpu_count: int) -> PodApiResponse:
        """Resume a stopped pod.

        Args:
            pod_id: The pod to resume.
            gpu_count: Number of GPUs to allocate on resume.

        Returns:
            Parsed PodApiResponse after resume.
        """
        mutation = f"""
        mutation {{
            podResume(input: {{ podId: "{pod_id}", gpuCount: {gpu_count} }}) {{
                {POD_FIELDS}
            }}
        }}
        """
        data = await self._execute_graphql(mutation)
        return self._parse_pod_response(data["podResume"])

    async def terminate(self, pod_id: str) -> None:
        """Terminate (permanently delete) a pod.

        Args:
            pod_id: The pod to terminate.
        """
        mutation = f"""
        mutation {{
            podTerminate(input: {{ podId: "{pod_id}" }})
        }}
        """
        await self._execute_graphql(mutation)

    async def _execute_graphql(self, query: str) -> dict[str, Any]:
        """Execute a GraphQL request against the Runpod API.

        Args:
            query: The GraphQL query or mutation string.

        Returns:
            The ``data`` portion of the GraphQL response.

        Raises:
            PodRequestError: On HTTP errors (status >= 400) or GraphQL errors.
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {"query": query}

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self._graphql_url, json=payload, headers=headers
            ) as response:
                if response.status >= 400:
                    body = await response.read()
                    raise PodRequestError(response.status, body)

                result = await response.json()

                if "errors" in result:
                    error_msg = "; ".join(
                        e.get("message", str(e)) for e in result["errors"]
                    )
                    raise PodRequestError(400, error_msg.encode())

                return result.get("data", {})

    def _parse_pod_response(self, data: dict[str, Any]) -> PodApiResponse:
        """Normalize a raw GraphQL pod response into PodApiResponse.

        Args:
            data: Raw pod dict from GraphQL response.

        Returns:
            Typed PodApiResponse dataclass.
        """
        machine = data.get("machine") or {}
        runtime = data.get("runtime") or {}
        raw_ports = runtime.get("ports") or []

        ports: dict[str, PortMapping] | None = None
        public_ip: str | None = None

        if raw_ports:
            ports = {}
            for port_entry in raw_ports:
                private_port = str(port_entry.get("privatePort", ""))
                ip = port_entry.get("ip", "")
                public_port = port_entry.get("publicPort", 0)
                protocol = port_entry.get("type", "tcp")
                is_public = port_entry.get("isIpPublic", False)

                ports[private_port] = PortMapping(
                    host_ip=ip,
                    host_port=int(public_port),
                    protocol=protocol,
                )

                if is_public and ip:
                    public_ip = ip

        return PodApiResponse(
            pod_id=data.get("id", ""),
            name=data.get("name", ""),
            desired_status=data.get("desiredStatus", ""),
            image_name=data.get("imageName", ""),
            gpu_display_name=machine.get("gpuDisplayName"),
            public_ip=public_ip,
            ports=ports,
            cost_per_hr=float(data.get("costPerHr", 0.0)),
            uptime_seconds=int(data.get("uptimeSeconds", 0)),
            machine_id=machine.get("podHostId"),
        )

    @staticmethod
    def _format_env(env_list: list[dict[str, str]]) -> str:
        """Format environment variables for inline GraphQL.

        Args:
            env_list: List of {key, value} dicts.

        Returns:
            GraphQL-compatible array string.
        """
        if not env_list:
            return "[]"
        items = ", ".join(
            f'{{ key: "{e["key"]}", value: "{e["value"]}" }}' for e in env_list
        )
        return f"[{items}]"
