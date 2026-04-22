"""Runpod service URLs (single source of truth).

Each host is overridable via env var so dev / staging / local-mock setups
can redirect independently. Do not conflate these hosts — they serve
different roles.

  - Control plane  (RUNPOD_API_BASE_URL,      default https://api.runpod.io)
      GraphQL mgmt: pods, endpoints, templates, auth.
      Exposed as Python constant ``RUNPOD_API_URL``.
  - Data plane     (RUNPOD_ENDPOINT_BASE_URL, default https://api.runpod.ai/v2)
      Endpoint invocations: /runsync, /run, /status, /health, /metrics.
      Sourced from runpod-python's ``endpoint_url_base``.
      Exposed as Python constant ``RUNPOD_ENDPOINT_URL``.
  - REST mgmt      (RUNPOD_REST_API_URL,      default https://rest.runpod.io/v1)
      REST subset of the control plane.
  - HAPI           (RUNPOD_HAPI_URL,          default https://hapi.runpod.net)
      Request-log aggregation service.
  - Console        (RUNPOD_CONSOLE_URL,       default https://console.runpod.io)
      User-facing web console. Accepts legacy ``CONSOLE_BASE_URL`` for
      backward compatibility (deprecated).

Data-plane URL is sourced via runpod-python (``runpod.endpoint_url_base``),
which reads ``RUNPOD_ENDPOINT_BASE_URL`` internally.

This module is intentionally a leaf: it does not import from
``runpod_flash.core.resources`` (or anything that transitively does), so
``core/api/runpod.py`` can import from it without triggering a circular
import through ``core/resources/__init__.py``.
"""

import os
import warnings
from urllib.parse import urlparse

import runpod


def _env_url(new: str, old: str | None, default: str) -> str:
    """Read a URL env var.

    Prefer the ``new`` name. Fall back to the ``old`` name (if provided) and
    emit a :class:`DeprecationWarning` so downstream users get a clear
    migration signal. Trailing slashes are stripped from whichever value is
    returned.
    """
    if new in os.environ:
        return os.environ[new].rstrip("/")
    if old and old in os.environ:
        warnings.warn(
            f"{old} is deprecated; use {new} instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return os.environ[old].rstrip("/")
    return default.rstrip("/")


RUNPOD_API_URL: str = _env_url("RUNPOD_API_BASE_URL", None, "https://api.runpod.io")
RUNPOD_ENDPOINT_URL: str = runpod.endpoint_url_base.rstrip("/")
RUNPOD_REST_API_URL: str = _env_url(
    "RUNPOD_REST_API_URL", None, "https://rest.runpod.io/v1"
)
RUNPOD_HAPI_URL: str = _env_url("RUNPOD_HAPI_URL", None, "https://hapi.runpod.net")
RUNPOD_CONSOLE_URL: str = _env_url(
    "RUNPOD_CONSOLE_URL", "CONSOLE_BASE_URL", "https://console.runpod.io"
)

GRAPHQL_URL: str = f"{RUNPOD_API_URL}/graphql"
CONSOLE_URL: str = f"{RUNPOD_CONSOLE_URL}/serverless/user/endpoint/%s"


def _endpoint_domain_from_base_url(base_url: str) -> str:
    if not base_url:
        return "api.runpod.ai"
    if "://" not in base_url:
        base_url = f"https://{base_url}"
    parsed = urlparse(base_url)
    return parsed.netloc or "api.runpod.ai"


ENDPOINT_DOMAIN: str = _endpoint_domain_from_base_url(RUNPOD_ENDPOINT_URL)

# ---------------------------------------------------------------------------
# Partial-override sanity warning
#
# If a user overrides some URLs but leaves others at their prod defaults, it
# is almost always a misconfiguration — they meant to target a non-prod
# environment but forgot a var. One RuntimeWarning at init; not fatal because
# legitimate mixed setups exist (e.g. dev control plane + prod HAPI).
# ---------------------------------------------------------------------------

_DEFAULTS = {
    "RUNPOD_API_BASE_URL": "https://api.runpod.io",
    "RUNPOD_ENDPOINT_BASE_URL": "https://api.runpod.ai/v2",
    "RUNPOD_REST_API_URL": "https://rest.runpod.io/v1",
    "RUNPOD_HAPI_URL": "https://hapi.runpod.net",
    "RUNPOD_CONSOLE_URL": "https://console.runpod.io",
}
_resolved = {
    "RUNPOD_API_BASE_URL": RUNPOD_API_URL,
    "RUNPOD_ENDPOINT_BASE_URL": RUNPOD_ENDPOINT_URL,
    "RUNPOD_REST_API_URL": RUNPOD_REST_API_URL,
    "RUNPOD_HAPI_URL": RUNPOD_HAPI_URL,
    "RUNPOD_CONSOLE_URL": RUNPOD_CONSOLE_URL,
}
_overridden = sorted(
    name for name, value in _resolved.items() if value != _DEFAULTS[name].rstrip("/")
)
_at_default = sorted(
    name for name, value in _resolved.items() if value == _DEFAULTS[name].rstrip("/")
)
if _overridden and _at_default:
    warnings.warn(
        "Partial Runpod URL override detected. "
        f"Overridden: {_overridden}. Still at default: {_at_default}. "
        "This is usually a misconfiguration — set all URLs for the target environment.",
        RuntimeWarning,
        stacklevel=2,
    )

del _DEFAULTS, _resolved, _overridden, _at_default
