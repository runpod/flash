import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from ..api.runpod import RunpodGraphQLClient

if TYPE_CHECKING:
    from .serverless import ServerlessResource


log = logging.getLogger(__name__)


GPU_STOCK_QUERY = """
query ServerlessGpuTypes($lowestPriceInput: GpuLowestPriceInput, $gpuTypesInput: GpuTypeFilter) {
  gpuTypes(input: $gpuTypesInput) {
    id
    displayName
    lowestPrice(input: $lowestPriceInput) {
      stockStatus
      __typename
    }
    __typename
  }
}
"""


CPU_STOCK_QUERY = """
query SecureCpuTypes($cpuFlavorInput: CpuFlavorInput, $specificsInput: SpecificsInput) {
  cpuFlavors(input: $cpuFlavorInput) {
    id
    specifics(input: $specificsInput) {
      stockStatus
      __typename
    }
    __typename
  }
}
"""


@dataclass
class WorkerAvailabilityResult:
    message: str
    has_availability: Optional[bool]
    reason: str


class WorkerAvailabilityDiagnostic:
    async def diagnose(
        self,
        resource: "ServerlessResource",
        worker_metrics: Optional[Dict[str, int]] = None,
    ) -> WorkerAvailabilityResult:
        if (resource.workersMax or 0) == 0:
            return WorkerAvailabilityResult(
                message="No compute available for your chosen configuration: your max workers are currently set to 0.",
                has_availability=False,
                reason="workers_max_zero",
            )

        compute_kind, compute_choice = self._selected_compute(resource)
        if not compute_choice:
            return WorkerAvailabilityResult(
                message="No compute available for your chosen configuration.",
                has_availability=None,
                reason="no_compute_selected",
            )

        throttled_workers = (worker_metrics or {}).get("throttled", 0)
        if throttled_workers > 0:
            return WorkerAvailabilityResult(
                message=(
                    f"Workers are currently throttled on endpoint for selected {compute_kind} {compute_choice}. "
                    "Consider raising max workers or changing gpu type."
                ),
                has_availability=True,
                reason="workers_throttled",
            )

        locations = self._selected_locations(resource)

        if compute_kind == "gpu":
            availability_by_location = await self._gpu_availability(
                gpu_id=compute_choice,
                gpu_count=resource.gpuCount or 1,
                locations=locations,
            )
            return self._build_message(
                compute_kind="gpu",
                compute_choice=compute_choice,
                locations=locations,
                availability_by_location=availability_by_location,
                include_available_signal=True,
            )

        if compute_kind == "cpu":
            availability_by_location = await self._cpu_availability(
                instance_id=compute_choice,
                locations=locations,
            )
            return self._build_message(
                compute_kind="cpu",
                compute_choice=compute_choice,
                locations=locations,
                availability_by_location=availability_by_location,
                include_available_signal=False,
            )

        return WorkerAvailabilityResult(
            message="No compute available for your chosen configuration.",
            has_availability=None,
            reason="unknown",
        )

    def _build_message(
        self,
        compute_kind: str,
        compute_choice: str,
        locations: List[str],
        availability_by_location: Dict[str, Optional[str]],
        include_available_signal: bool,
    ) -> WorkerAvailabilityResult:
        has_availability = any(status for status in availability_by_location.values())

        if not has_availability:
            selected_locations = ", ".join(locations) if locations else "all locations"
            return WorkerAvailabilityResult(
                message=(
                    f"No workers available on endpoint: no {compute_kind} availability for {compute_kind} type {compute_choice} "
                    f"in selected locations ({selected_locations})."
                ),
                has_availability=False,
                reason=f"no_{compute_kind}_availability",
            )

        if include_available_signal:
            signal = self._summarize_stock_signal(availability_by_location)
            return WorkerAvailabilityResult(
                message=(
                    f"No workers available right now. Current availability signal "
                    f"for selected gpu {compute_choice}: {signal}."
                ),
                has_availability=True,
                reason="gpu_has_availability",
            )

        return WorkerAvailabilityResult(
            message=(
                f"No workers available right now for selected {compute_kind} "
                f"{compute_choice}."
            ),
            has_availability=True,
            reason=f"{compute_kind}_has_availability",
        )

    async def _gpu_availability(
        self,
        gpu_id: str,
        gpu_count: int,
        locations: List[str],
    ) -> Dict[str, Optional[str]]:
        location_inputs = locations or [None]
        availability_by_location: Dict[str, Optional[str]] = {}

        async with RunpodGraphQLClient() as client:
            for location in location_inputs:
                variables = {
                    "gpuTypesInput": {"ids": [gpu_id]},
                    "lowestPriceInput": {
                        "dataCenterId": location,
                        "gpuCount": gpu_count,
                        "secureCloud": True,
                        "includeAiApi": True,
                        "allowedCudaVersions": [],
                        "compliance": [],
                    },
                }
                key = location or "global"
                try:
                    result = await client._execute_graphql(GPU_STOCK_QUERY, variables)
                    gpu_types = result.get("gpuTypes") or []
                    first = gpu_types[0] if gpu_types else {}
                    lowest = first.get("lowestPrice") if isinstance(first, dict) else {}
                    status = (
                        lowest.get("stockStatus") if isinstance(lowest, dict) else None
                    )
                    availability_by_location[key] = status
                except Exception as exc:
                    log.debug("GPU availability query failed for %s: %s", key, exc)
                    availability_by_location[key] = None

        return availability_by_location

    async def _cpu_availability(
        self,
        instance_id: str,
        locations: List[str],
    ) -> Dict[str, Optional[str]]:
        flavor_id = self._cpu_flavor_id(instance_id)
        if not flavor_id:
            return {loc: None for loc in (locations or ["global"])}

        location_inputs = locations or [""]
        availability_by_location: Dict[str, Optional[str]] = {}

        async with RunpodGraphQLClient() as client:
            for location in location_inputs:
                variables = {
                    "cpuFlavorInput": {"id": flavor_id},
                    "specificsInput": {
                        "dataCenterId": location,
                        "instanceId": instance_id,
                    },
                }
                key = location or "global"
                try:
                    result = await client._execute_graphql(CPU_STOCK_QUERY, variables)
                    cpu_flavors = result.get("cpuFlavors") or []
                    first = cpu_flavors[0] if cpu_flavors else {}
                    specifics = (
                        first.get("specifics") if isinstance(first, dict) else {}
                    )
                    status = (
                        specifics.get("stockStatus")
                        if isinstance(specifics, dict)
                        else None
                    )
                    availability_by_location[key] = status
                except Exception as exc:
                    log.debug("CPU availability query failed for %s: %s", key, exc)
                    availability_by_location[key] = None

        return availability_by_location

    @staticmethod
    def _selected_compute(resource: "ServerlessResource") -> Tuple[str, Optional[str]]:
        if resource.instanceIds:
            first_instance = resource.instanceIds[0]
            choice = (
                first_instance.value
                if hasattr(first_instance, "value")
                else str(first_instance)
            )
            return "cpu", choice

        gpu_ids = [
            part.strip() for part in (resource.gpuIds or "").split(",") if part.strip()
        ]
        if gpu_ids:
            return "gpu", gpu_ids[0]

        return "unknown", None

    @staticmethod
    def _selected_locations(resource: "ServerlessResource") -> List[str]:
        return [
            part.strip()
            for part in (resource.locations or "").split(",")
            if part.strip()
        ]

    @staticmethod
    def _cpu_flavor_id(instance_id: str) -> Optional[str]:
        if "-" not in instance_id:
            return None
        return instance_id.split("-", 1)[0]

    @staticmethod
    def _summarize_stock_signal(
        availability_by_location: Dict[str, Optional[str]],
    ) -> str:
        non_empty = [status for status in availability_by_location.values() if status]
        if not non_empty:
            return "unknown"

        priority = {"High": 3, "Medium": 2, "Low": 1}
        best = max(non_empty, key=lambda status: priority.get(status, 0))
        return best
