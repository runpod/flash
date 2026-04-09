import logging
import os
import re
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional

import httpx

from runpod_flash.core.utils.http import get_authenticated_httpx_client

log = logging.getLogger(__name__)

API_BASE_URL = os.getenv("RUNPOD_API_BASE_URL", "https://api.runpod.ai").rstrip("/")
DEV_API_BASE_URL = "https://dev-api.runpod.ai"
HAPI_BASE_URL = "https://hapi.runpod.net"
DEV_HAPI_BASE_URL = "https://dev-hapi.runpod.net"
LOG_PREFIX_TIMESTAMP_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)"
)


def _resolve_hapi_base_url() -> str:
    runpod_env = os.getenv("RUNPOD_ENV", "").lower()
    if runpod_env == "dev":
        return DEV_HAPI_BASE_URL

    api_base = os.getenv("RUNPOD_API_BASE_URL", "")
    if DEV_API_BASE_URL in api_base:
        return DEV_HAPI_BASE_URL

    return HAPI_BASE_URL


class QBRequestLogPhase(str, Enum):
    WAITING_FOR_WORKER = "WAITING_FOR_WORKER"
    WAITING_FOR_WORKER_INITIALIZATION = "WAITING_FOR_WORKER_INITIALIZATION"
    STREAMING = "STREAMING"


@dataclass
class QBRequestLogBatch:
    lines: List[str]
    matched_by_request_id: bool
    worker_id: Optional[str]
    phase: QBRequestLogPhase
    worker_metrics: dict[str, int] = field(default_factory=dict)
    ready_worker_ids: List[str] = field(default_factory=list)


class QBRequestLogFetcher:
    def __init__(
        self,
        timeout_seconds: float = 4.0,
        max_lines: int = 25,
        lookback_seconds: int = 20,
        start_time: Optional[datetime] = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.max_lines = max_lines
        self.lookback_seconds = lookback_seconds
        self.start_time = start_time or datetime.now(timezone.utc)
        self.seen = set()
        self.worker_id: Optional[str] = None
        self.has_streamed_logs = False
        self.has_primed_worker_logs = False

    async def fetch_logs(
        self,
        endpoint_id: str,
        request_id: str,
        status_api_key: str,
        pod_logs_api_key: str,
        status_api_key_fallback: Optional[str] = None,
    ):
        status_payload = await self._fetch_status_payload(
            endpoint_id=endpoint_id,
            request_id=request_id,
            status_api_key=status_api_key,
            status_api_key_fallback=status_api_key_fallback,
        )
        assigned_worker_id = self._worker_id_from_status_payload(status_payload)

        metrics_payload = await self._fetch_metrics_payload(
            endpoint_id=endpoint_id,
            status_api_key=status_api_key,
            status_api_key_fallback=status_api_key_fallback,
        )
        running_worker_ids = self._ready_worker_ids_from_metrics(metrics_payload)
        initializing_workers = self._initializing_worker_count(metrics_payload)
        worker_metrics = self._worker_metrics_snapshot(metrics_payload)
        ready_worker_ids = self._ready_worker_ids_from_metrics(metrics_payload)

        matched_by_request_id = False
        if assigned_worker_id:
            self._set_worker_id(assigned_worker_id)
            matched_by_request_id = True
        elif not self.worker_id and running_worker_ids:
            self._set_worker_id(running_worker_ids[0])

        if not self.worker_id:
            phase = (
                QBRequestLogPhase.WAITING_FOR_WORKER_INITIALIZATION
                if initializing_workers > 0
                else QBRequestLogPhase.WAITING_FOR_WORKER
            )
            return QBRequestLogBatch(
                lines=[],
                matched_by_request_id=False,
                worker_id=None,
                phase=phase,
                worker_metrics=worker_metrics,
                ready_worker_ids=ready_worker_ids,
            )

        logs_payload = await self._fetch_pod_logs(
            worker_id=self.worker_id,
            runpod_api_key=pod_logs_api_key,
        )
        if not logs_payload:
            return QBRequestLogBatch(
                lines=[],
                matched_by_request_id=matched_by_request_id,
                worker_id=self.worker_id,
                phase=QBRequestLogPhase.WAITING_FOR_WORKER_INITIALIZATION,
                worker_metrics=worker_metrics,
                ready_worker_ids=ready_worker_ids,
            )

        if not self.has_primed_worker_logs:
            lines = self._extract_initial_lines(logs_payload, request_id=request_id)
            self.has_primed_worker_logs = True
            if lines:
                self.has_streamed_logs = True
            return QBRequestLogBatch(
                lines=lines[-self.max_lines :],
                matched_by_request_id=matched_by_request_id,
                worker_id=self.worker_id,
                phase=(
                    QBRequestLogPhase.STREAMING
                    if self.has_streamed_logs
                    else QBRequestLogPhase.WAITING_FOR_WORKER_INITIALIZATION
                ),
                worker_metrics=worker_metrics,
                ready_worker_ids=ready_worker_ids,
            )

        lines = self._extract_lines(logs_payload)
        if lines:
            self.has_streamed_logs = True
        phase = (
            QBRequestLogPhase.STREAMING
            if self.has_streamed_logs
            else QBRequestLogPhase.WAITING_FOR_WORKER_INITIALIZATION
        )
        return QBRequestLogBatch(
            lines=lines[-self.max_lines :],
            matched_by_request_id=matched_by_request_id,
            worker_id=self.worker_id,
            phase=phase,
            worker_metrics=worker_metrics,
            ready_worker_ids=ready_worker_ids,
        )

    async def _fetch_status_payload(
        self,
        endpoint_id: str,
        request_id: str,
        status_api_key: str,
        status_api_key_fallback: Optional[str],
    ) -> Optional[dict[str, Any]]:
        url = f"{API_BASE_URL}/v2/{endpoint_id}/status/{request_id}"
        auth_keys = self._auth_candidates(status_api_key, status_api_key_fallback)

        for auth_key in auth_keys:
            try:
                async with get_authenticated_httpx_client(
                    timeout=self.timeout_seconds,
                    api_key_override=auth_key,
                ) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    return response.json()
            except httpx.HTTPStatusError as exc:
                if exc.response is not None and exc.response.status_code == 401:
                    continue
                log.debug(
                    "Failed to fetch worker for request %s: %s",
                    request_id,
                    exc,
                )
                return None
            except (httpx.HTTPError, ValueError) as exc:
                log.debug("Failed to fetch worker for request %s: %s", request_id, exc)
                return None

        return None

    async def _fetch_metrics_payload(
        self,
        endpoint_id: str,
        status_api_key: str,
        status_api_key_fallback: Optional[str],
    ) -> Optional[dict[str, Any]]:
        auth_keys = self._auth_candidates(status_api_key, status_api_key_fallback)
        url = f"{API_BASE_URL}/v2/{endpoint_id}/metrics"

        for auth_key in auth_keys:
            try:
                async with get_authenticated_httpx_client(
                    timeout=self.timeout_seconds,
                    api_key_override=auth_key,
                ) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    return response.json()
            except httpx.HTTPStatusError as exc:
                if exc.response is not None and exc.response.status_code == 401:
                    continue
                log.debug(
                    "Failed to fetch endpoint metrics for %s via %s: %s",
                    endpoint_id,
                    url,
                    exc,
                )
                return None
            except (httpx.HTTPError, ValueError) as exc:
                log.debug(
                    "Failed to fetch endpoint metrics for %s via %s: %s",
                    endpoint_id,
                    url,
                    exc,
                )
                return None

        return None

    @staticmethod
    def _worker_id_from_status_payload(
        payload: Optional[dict[str, Any]],
    ) -> Optional[str]:
        if not payload:
            return None
        worker_id = payload.get("workerId")
        if not worker_id:
            return None
        return str(worker_id)

    @staticmethod
    def _ready_worker_ids_from_metrics(payload: Optional[dict[str, Any]]) -> List[str]:
        if not payload:
            return []
        ready_workers = payload.get("readyWorkers")
        if not isinstance(ready_workers, list):
            return []
        return [str(worker) for worker in ready_workers if worker]

    @staticmethod
    def _worker_metrics_snapshot(payload: Optional[dict[str, Any]]) -> dict[str, int]:
        base = {
            "ready": 0,
            "running": 0,
            "idle": 0,
            "initializing": 0,
            "throttled": 0,
            "unhealthy": 0,
        }
        if not payload:
            return base
        workers = payload.get("workers")
        if not isinstance(workers, dict):
            return base
        for key in base:
            value = workers.get(key)
            if isinstance(value, int):
                base[key] = value
        return base

    @staticmethod
    def _initializing_worker_count(payload: Optional[dict[str, Any]]) -> int:
        if not payload:
            return 0
        workers = payload.get("workers")
        if not isinstance(workers, dict):
            return 0
        initializing = workers.get("initializing", 0)
        if isinstance(initializing, int):
            return initializing
        return 0

    @staticmethod
    def _auth_candidates(
        primary_key: str,
        fallback_key: Optional[str],
    ) -> List[str]:
        keys = [primary_key]
        if fallback_key and fallback_key != primary_key:
            keys.append(fallback_key)
        return keys

    async def _fetch_pod_logs(
        self,
        worker_id: str,
        runpod_api_key: str,
    ) -> Optional[dict[str, Any]]:
        url = f"{_resolve_hapi_base_url()}/v1/pod/{worker_id}/logs"

        try:
            async with get_authenticated_httpx_client(
                timeout=self.timeout_seconds,
                api_key_override=runpod_api_key,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            body_preview = ""
            if exc.response is not None:
                body_preview = (exc.response.text or "")[:500]
            log.debug(
                "Failed to fetch pod logs for %s: %s | response_body=%s",
                worker_id,
                exc,
                body_preview,
            )
            return None
        except (httpx.HTTPError, ValueError) as exc:
            log.debug("Failed to fetch pod logs for %s: %s", worker_id, exc)
            return None

    def _extract_lines(self, payload: dict[str, Any]) -> List[str]:
        records = self._collect_records(payload)
        if not records:
            return []

        lines: List[str] = []

        for record in records:
            if not isinstance(record, str):
                continue

            stripped = record.strip().replace("\\n", "")
            if not stripped or stripped in self.seen:
                continue
            self.seen.add(stripped)
            lines.append(stripped)

        return lines

    def _extract_initial_lines(
        self, payload: dict[str, Any], request_id: str
    ) -> List[str]:
        records = self._collect_records(payload)
        if not records:
            return []

        cutoff = self.start_time.timestamp() - self.lookback_seconds
        lines: List[str] = []
        saw_recent_window_line = False

        for record in records:
            if not isinstance(record, str):
                continue

            stripped = record.strip().replace("\\n", "")
            if not stripped:
                continue

            if stripped in self.seen:
                continue
            self.seen.add(stripped)

            timestamp = self._parse_prefix_timestamp(stripped)
            if timestamp is not None and timestamp.timestamp() < cutoff:
                continue

            if timestamp is not None:
                saw_recent_window_line = True
                lines.append(stripped)
                continue

            if request_id and request_id in stripped:
                lines.append(stripped)
                continue

            if saw_recent_window_line:
                lines.append(stripped)
                continue

        return lines

    def _set_worker_id(self, worker_id: str) -> None:
        if self.worker_id == worker_id:
            return
        self.worker_id = worker_id
        self.seen = set()
        self.has_streamed_logs = False
        self.has_primed_worker_logs = False

    @staticmethod
    def _collect_records(payload: dict[str, Any]) -> List[Any]:
        container_records = payload.get("container")
        system_records = payload.get("system")

        records: list[Any] = []
        if isinstance(system_records, list):
            records.extend(system_records)
        if isinstance(container_records, list):
            records.extend(container_records)

        return records

    @staticmethod
    def _parse_prefix_timestamp(line: str) -> Optional[datetime]:
        match = LOG_PREFIX_TIMESTAMP_RE.match(line)
        if not match:
            return None

        timestamp_text = match.group("timestamp")
        normalized = timestamp_text.replace("Z", "+00:00")

        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None
