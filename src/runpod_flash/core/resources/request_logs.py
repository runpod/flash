import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import dateutil
from typing import Any, List, Optional

import httpx

from runpod_flash.core.utils.http import get_authenticated_httpx_client

log = logging.getLogger(__name__)

API_BASE_URL = "https://api.runpod.ai"


def _format_log_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


@dataclass
class QBRequestLogBatch:
    lines: List[str]
    matched_by_request_id: bool
    worker_id: Optional[str]

class QBRequestLogFetcher:
    def __init__(
        self,
        timeout_seconds: float = 4.0,
        max_lines: int = 25,
        fallback_tail_lines: int = 10,
        lookback_seconds: int = 5,
        start_time: datetime = datetime.now(timezone.utc)
    ):
        self.timeout_seconds = timeout_seconds
        self.max_lines = max_lines
        self.fallback_tail_lines = fallback_tail_lines
        self.lookback_seconds = lookback_seconds
        self.start_time = start_time
        self.fetched_until: datetime | None = None
        self.seen = set()

    async def fetch_logs(
        self,
        endpoint_id: str,
        endpoint_ai_key: str,
    ):
        if self.fetched_until:
            self.start_time = self.fetched_until
        fetch_until = datetime.now(timezone.utc)
        logs_payload = await self._fetch_endpoint_logs(endpoint_id, endpoint_ai_key, fetch_until)
        if not logs_payload:
            return

        lines = self._extract_lines(logs_payload, fetch_until)
        return QBRequestLogBatch(
                lines = lines,
                matched_by_request_id = False,
                worker_id = None
                )

    async def _fetch_worker_id(
        self,
        endpoint_id: str,
        request_id: str,
        runpod_api_key: str,
    ) -> Optional[str]:
        url = f"{API_BASE_URL}/v2/{endpoint_id}/status/{request_id}"

        try:
            async with get_authenticated_httpx_client(
                timeout=self.timeout_seconds,
                api_key_override=runpod_api_key,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.debug("Failed to fetch worker for request %s: %s", request_id, exc)
            return None

        worker_id = payload.get("workerId")
        if not worker_id:
            return None
        return str(worker_id)

    async def _fetch_endpoint_logs(
        self,
        endpoint_id: str,
        endpoint_ai_key: str,
        end_utc: datetime,
        start_utc: Optional[datetime] = None
    ) -> Optional[dict[str, Any]]:
        """
        fetch endpoint logs for a given time range, defaulting to the fetcher
        configured start time
        updates start utc when we successfully fetch logs
        """
        url = f"{API_BASE_URL}/v2/{endpoint_id}/logs"
        if not start_utc:
            start_utc = self.start_time

        log.debug(f"fetching logs for time range: {start_utc} to {end_utc}")
        params = {
            "from": _format_log_timestamp(start_utc),
            "to": _format_log_timestamp(end_utc),
            "page": 0,
            "pageSize": 200,
        }

        try:
            async with get_authenticated_httpx_client(
                timeout=self.timeout_seconds,
                api_key_override=endpoint_ai_key,
            ) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            body_preview = ""
            if exc.response is not None:
                body_preview = (exc.response.text or "")[:500]
            log.debug(
                "Failed to fetch endpoint logs for %s: %s | response_body=%s",
                endpoint_id,
                exc,
                body_preview,
            )
            return None
        except (httpx.HTTPError, ValueError) as exc:
            log.debug("Failed to fetch endpoint logs for %s: %s", endpoint_id, exc)
            return None

    def _extract_lines(self, payload: dict[str, Any], end_time: datetime) -> List[str]:
        """
        extract lines from a response payload from sls endpoint response
        deduplicates based on already seen lines
        """
        records = payload.get("data")
        if not isinstance(records, list):
            return []

        max_seen_dt = self.start_time
        lines: List[str] = []

        for record in records:
            if isinstance(record, str):
                stripped = record.strip()
                if stripped and stripped not in self.seen:
                    self.seen.add(stripped)
                    lines.append(record)
                continue

            if not isinstance(record, dict):
                continue

            line = (
                record.get("message")
                or record.get("log")
                or record.get("text")
                or record.get("raw")
            )

            dt = record.get("dt")

            if dt:
                parsed = dateutil.parser.parse(dt)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)   # treat naive as UTC
                else:
                    parsed = parsed.astimezone(timezone.utc)
                max_seen_dt = max(parsed, max_seen_dt)

            if isinstance(line, str):
                stripped = line.strip()
                if stripped and stripped not in self.seen:
                    stripped = stripped.replace("\\n", "")
                    self.seen.add(stripped)
                    lines.append(stripped)
        if lines:
            # lines are returned in time descending order
            lines.reverse()
            if max_seen_dt > self.start_time:
                self.fetched_until = max_seen_dt
            else:
                # not all logs have a timestamp, assume we should refetch
                self.fetched_until = self.start_time

        return lines
