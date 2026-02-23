import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

import httpx

from runpod_flash.core.utils.http import get_authenticated_httpx_client

log = logging.getLogger(__name__)

API_BASE_URL = "https://api.runpod.ai"


def _format_log_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


@dataclass
class QBRequestLogBatch:
    worker_id: str
    lines: List[str]
    matched_by_request_id: bool


class QBRequestLogFetcher:
    def __init__(
        self,
        timeout_seconds: float = 4.0,
        max_lines: int = 25,
        fallback_tail_lines: int = 10,
        lookback_minutes: int = 10,
    ):
        self.timeout_seconds = timeout_seconds
        self.max_lines = max_lines
        self.fallback_tail_lines = fallback_tail_lines
        self.lookback_minutes = lookback_minutes

    async def fetch_for_request(
        self,
        endpoint_id: str,
        request_id: str,
        runpod_api_key: str,
        endpoint_ai_key: Optional[str],
    ) -> Optional[QBRequestLogBatch]:
        log.debug(
            "QB logs step 1/4: resolving worker for request %s on endpoint %s",
            request_id,
            endpoint_id,
        )
        worker_id = await self._fetch_worker_id(endpoint_id, request_id, runpod_api_key)
        if not worker_id:
            log.debug("QB logs step 1/4 failed: no workerId for request %s", request_id)
            return None

        log.debug(
            "QB logs step 1/4 success: request %s assigned to worker %s",
            request_id,
            worker_id,
        )

        if not endpoint_ai_key:
            log.debug("No aiKey available for endpoint %s", endpoint_id)
            return QBRequestLogBatch(
                worker_id=worker_id,
                lines=[],
                matched_by_request_id=False,
            )

        log.debug(
            "QB logs step 2/4: fetching endpoint logs for endpoint %s", endpoint_id
        )
        logs_payload = await self._fetch_endpoint_logs(endpoint_id, endpoint_ai_key)
        if not logs_payload:
            log.debug(
                "QB logs step 2/4 failed: no endpoint logs payload for endpoint %s",
                endpoint_id,
            )
            return QBRequestLogBatch(
                worker_id=worker_id,
                lines=[],
                matched_by_request_id=False,
            )

        log.debug("QB logs step 2/4 success: endpoint logs payload received")

        log.debug("QB logs step 3/4: extracting text lines from endpoint payload")
        lines = self._extract_lines(logs_payload)
        if not lines:
            log.debug("QB logs step 3/4 result: extracted 0 lines")
            return QBRequestLogBatch(
                worker_id=worker_id,
                lines=[],
                matched_by_request_id=False,
            )

        log.debug("QB logs step 3/4 success: extracted %d lines", len(lines))

        log.debug("QB logs step 4/4: filtering lines by request id %s", request_id)
        matching_lines = [line for line in lines if request_id in line]
        if matching_lines:
            log.debug(
                "QB logs step 4/4 success: found %d request-matching lines",
                len(matching_lines),
            )
            return QBRequestLogBatch(
                worker_id=worker_id,
                lines=matching_lines[-self.max_lines :],
                matched_by_request_id=True,
            )

        log.debug(
            "QB logs step 4/4 fallback: no request-matching lines, returning tail"
        )

        return QBRequestLogBatch(
            worker_id=worker_id,
            lines=lines[-self.fallback_tail_lines :],
            matched_by_request_id=False,
        )

    async def _fetch_worker_id(
        self,
        endpoint_id: str,
        request_id: str,
        runpod_api_key: str,
    ) -> Optional[str]:
        url = f"{API_BASE_URL}/v2/{endpoint_id}/status/{request_id}"
        log.debug("QB worker lookup request: GET %s", url)

        try:
            async with get_authenticated_httpx_client(
                timeout=self.timeout_seconds,
                api_key_override=runpod_api_key,
            ) as client:
                response = await client.get(url)
                log.debug(
                    "QB worker lookup response: status=%s endpoint=%s request=%s",
                    response.status_code,
                    endpoint_id,
                    request_id,
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.debug("Failed to fetch worker for request %s: %s", request_id, exc)
            return None

        worker_id = payload.get("workerId")
        if not worker_id:
            log.debug("No workerId found in status response for request %s", request_id)
            return None
        return str(worker_id)

    async def _fetch_endpoint_logs(
        self,
        endpoint_id: str,
        endpoint_ai_key: str,
    ) -> Optional[dict[str, Any]]:
        url = f"{API_BASE_URL}/v2/{endpoint_id}/logs"
        now_utc = datetime.now(timezone.utc)
        start_utc = now_utc - timedelta(minutes=self.lookback_minutes)
        params = {
            "from": _format_log_timestamp(start_utc),
            "to": _format_log_timestamp(now_utc),
            "page": 0,
            "pageSize": 200,
        }

        log.debug(
            "Endpoint logs request: GET %s params=%s",
            url,
            {
                "from": params["from"],
                "to": params["to"],
                "page": params["page"],
                "pageSize": params["pageSize"],
            },
        )

        try:
            async with get_authenticated_httpx_client(
                timeout=self.timeout_seconds,
                api_key_override=endpoint_ai_key,
            ) as client:
                response = await client.get(url, params=params)
                log.debug(
                    "Endpoint logs response: status=%s endpoint=%s",
                    response.status_code,
                    endpoint_id,
                )
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

    def _extract_lines(self, payload: dict[str, Any]) -> List[str]:
        records = payload.get("data")
        if not isinstance(records, list):
            return []

        lines: List[str] = []
        for record in records:
            if isinstance(record, str):
                if record.strip():
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
            if isinstance(line, str) and line.strip():
                lines.append(line)

        return lines
