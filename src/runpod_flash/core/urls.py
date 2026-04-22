"""Runpod service URLs (single source of truth).

Each host is overridable via env var so dev / staging / local-mock setups
can redirect independently. Do not conflate these hosts — they serve
different roles.

  - Control plane  (RUNPOD_API_BASE_URL,      default https://api.runpod.io)
      GraphQL mgmt: pods, endpoints, templates, auth.
  - Data plane     (RUNPOD_ENDPOINT_BASE_URL, default https://api.runpod.ai/v2)
      Endpoint invocations: /runsync, /run, /status, /health, /metrics.
  - REST mgmt      (RUNPOD_REST_API_URL,      default https://rest.runpod.io/v1)
      REST subset of the control plane.
  - HAPI           (RUNPOD_HAPI_BASE_URL,     default https://hapi.runpod.net)
      Request-log aggregation service.

Data-plane URL is sourced via runpod-python (``runpod.endpoint_url_base``),
which reads ``RUNPOD_ENDPOINT_BASE_URL`` internally.

This module is intentionally a leaf: it does not import from
``runpod_flash.core.resources`` (or anything that transitively does), so
``core/api/runpod.py`` can import from it without triggering a circular
import through ``core/resources/__init__.py``.
"""

import os
from urllib.parse import urlparse

import runpod

RUNPOD_API_BASE_URL: str = os.environ.get(
    "RUNPOD_API_BASE_URL", "https://api.runpod.io"
).rstrip("/")
RUNPOD_REST_API_URL: str = os.environ.get(
    "RUNPOD_REST_API_URL", "https://rest.runpod.io/v1"
).rstrip("/")
ENDPOINT_BASE_URL: str = runpod.endpoint_url_base.rstrip("/")
GRAPHQL_URL: str = f"{RUNPOD_API_BASE_URL}/graphql"
HAPI_BASE_URL: str = os.environ.get(
    "RUNPOD_HAPI_BASE_URL", "https://hapi.runpod.net"
).rstrip("/")


def _endpoint_domain_from_base_url(base_url: str) -> str:
    if not base_url:
        return "api.runpod.ai"
    if "://" not in base_url:
        base_url = f"https://{base_url}"
    parsed = urlparse(base_url)
    return parsed.netloc or "api.runpod.ai"


ENDPOINT_DOMAIN: str = _endpoint_domain_from_base_url(runpod.endpoint_url_base)
