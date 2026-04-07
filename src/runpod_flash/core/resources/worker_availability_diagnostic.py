import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from ..api.runpod import RunpodGraphQLClient

if TYPE_CHECKING:
    from .serverless import ServerlessResource


log = logging.getLogger(__name__)
AVAILABLE_STOCK_STATUSES = {"LOW", "MEDIUM", "HIGH"}


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
            compute_label = "gpu type" if compute_kind == "gpu" else "cpu type"
            return WorkerAvailabilityResult(
                message=(
                    f"Workers are currently throttled on endpoint for selected {compute_kind} {compute_choice}. "
                    f"Consider raising max workers or changing {compute_label}."
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
        has_availability = any(
            self._is_available_stock_status(status)
            for status in availability_by_location.values()
        )

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
                key = location or "global"
                try:
                    status = await client.get_gpu_lowest_price_stock_status(
                        gpu_id=gpu_id,
                        gpu_count=gpu_count,
                        data_center_id=location,
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
                key = location or "global"
                try:
                    status = await client.get_cpu_specific_stock_status(
                        cpu_flavor_id=flavor_id,
                        instance_id=instance_id,
                        data_center_id=location,
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

        priority = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}

        def score(value: str) -> int:
            normalized = value.strip().upper().replace("-", "_").replace(" ", "_")
            return priority.get(normalized, 0)

        best = max(non_empty, key=score)
        return best

    @staticmethod
    def _is_available_stock_status(status: Optional[str]) -> bool:
        if not isinstance(status, str):
            return False
        normalized = status.strip().upper().replace("-", "_").replace(" ", "_")
        return normalized in AVAILABLE_STOCK_STATUSES
