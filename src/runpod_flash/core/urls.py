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
which reads ``RUNPOD_ENDPOINT_BASE_URL`` and caches the result at package
import. Set the env var BEFORE Python imports the ``runpod`` package or the
override will be silently ignored (no warning can detect this case).

Empty or whitespace-only env values are treated as unset. Values that are
not syntactically http/https URLs raise ``ValueError`` at import.

Two diagnostic warnings fire at import when misconfig is likely:

  - ``RuntimeWarning`` when some URL envs are overridden but others stay at
    prod defaults (partial override — usually a forgotten var).
  - ``RuntimeWarning`` when ``RUNPOD_ENV`` is set to a non-prod value but no
    URL envs are overridden (a dev shell without explicit URL redirects
    routes to prod).

Silence both with ``RUNPOD_URL_MIXED_OK=1`` for legitimate mixed setups
(e.g. dev control plane + prod HAPI).

Naming convention:

  - Primary env-sourced URLs follow ``RUNPOD_*_URL`` (one per service).
  - Derived constants (``GRAPHQL_URL`` = ``RUNPOD_API_URL`` + ``/graphql``;
    ``CONSOLE_URL`` = ``RUNPOD_CONSOLE_URL`` + a ``%s`` endpoint-ID
    template) are intentionally unprefixed — they are not env vars, and
    prefixing them would falsely imply a ``RUNPOD_GRAPHQL_URL`` env exists.

For test authors: all URL constants are captured at module import time. A
test that sets a URL env var via ``monkeypatch.setenv`` will **not** affect
the already-imported constants. To test override behavior, delete
``runpod_flash.core.urls`` from ``sys.modules`` and re-import — see
``tests/unit/core/test_urls.py::_reload_urls_module``.

This module is intentionally a leaf: it must not import from
``runpod_flash.*``. A self-import would risk circular imports through
``core/resources/__init__.py``. Keep ``runpod`` plus stdlib only.
"""

import os
import warnings
from typing import Optional
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

DEFAULT_API_URL = "https://api.runpod.io"
DEFAULT_ENDPOINT_URL = "https://api.runpod.ai/v2"
DEFAULT_REST_API_URL = "https://rest.runpod.io/v1"
DEFAULT_HAPI_URL = "https://hapi.runpod.net"
DEFAULT_CONSOLE_URL = "https://console.runpod.io"

_VALID_SCHEMES = ("http", "https")


def _validate_url(value: str, env_name: str) -> str:
    """Strip trailing slash and assert http/https scheme + non-empty netloc.

    Also rejects a non-numeric port (``parsed.port`` raises ``ValueError`` on
    malformed values — a typo like ``:8o80`` is loud, not silently lost).
    """
    stripped = value.rstrip("/")
    parsed = urlparse(stripped)
    if parsed.scheme not in _VALID_SCHEMES or not parsed.netloc:
        raise ValueError(
            f"{env_name}={value!r} is not a valid http/https URL "
            f"(scheme={parsed.scheme!r}, netloc={parsed.netloc!r})"
        )
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{env_name}={value!r} has a malformed port: {exc}") from exc
    return stripped


def _env_url(new: str, old: Optional[str], default: str) -> str:
    """Read a URL env var.

    Prefer the ``new`` name. Fall back to the ``old`` name (if provided) with a
    ``DeprecationWarning``. Empty/whitespace values are treated as unset.
    Returned value has its trailing slash stripped and is validated.
    """
    new_val = os.environ.get(new, "").strip()
    if new_val:
        return _validate_url(new_val, new)
    if old:
        old_val = os.environ.get(old, "").strip()
        if old_val:
            warnings.warn(
                f"{old} is deprecated; use {new} instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            return _validate_url(old_val, old)
    return default.rstrip("/")


RUNPOD_API_URL: str = _env_url("RUNPOD_API_BASE_URL", None, DEFAULT_API_URL)
RUNPOD_ENDPOINT_URL: str = runpod.endpoint_url_base.rstrip("/")
RUNPOD_REST_API_URL: str = _env_url("RUNPOD_REST_API_URL", None, DEFAULT_REST_API_URL)
RUNPOD_HAPI_URL: str = _env_url("RUNPOD_HAPI_URL", None, DEFAULT_HAPI_URL)
RUNPOD_CONSOLE_URL: str = _env_url(
    "RUNPOD_CONSOLE_URL", "CONSOLE_BASE_URL", DEFAULT_CONSOLE_URL
)

GRAPHQL_URL: str = f"{RUNPOD_API_URL}/graphql"
CONSOLE_URL: str = f"{RUNPOD_CONSOLE_URL}/serverless/user/endpoint/%s"


def _endpoint_domain_from_base_url(base_url: str) -> str:
    """Extract the host portion of a base URL.

    Empty input falls back to the prod default. A non-empty input that fails
    to parse into a netloc raises ``ValueError`` — a typo should be loud, not
    silently route to production.
    """

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
    if not parsed.netloc:
        raise ValueError(
            f"cannot extract endpoint domain from {base_url!r}: empty netloc"
        )
    return parsed.netloc


ENDPOINT_DOMAIN: str = _endpoint_domain_from_base_url(RUNPOD_ENDPOINT_URL)


_URL_ENV_VARS = (
    "RUNPOD_API_BASE_URL",
    "RUNPOD_ENDPOINT_BASE_URL",
    "RUNPOD_REST_API_URL",
    "RUNPOD_HAPI_URL",
    "RUNPOD_CONSOLE_URL",
    "CONSOLE_BASE_URL",
)
_TRUTHY = ("1", "true", "yes", "on")

# Pairs each env-var name with its resolved-at-import constant and its prod
# default. One tuple per row keeps the three columns aligned so a future
# contributor cannot update one and forget the others.
_URL_PROFILE = (
    ("RUNPOD_API_BASE_URL", lambda: RUNPOD_API_URL, DEFAULT_API_URL),
    ("RUNPOD_ENDPOINT_BASE_URL", lambda: RUNPOD_ENDPOINT_URL, DEFAULT_ENDPOINT_URL),
    ("RUNPOD_REST_API_URL", lambda: RUNPOD_REST_API_URL, DEFAULT_REST_API_URL),
    ("RUNPOD_HAPI_URL", lambda: RUNPOD_HAPI_URL, DEFAULT_HAPI_URL),
    ("RUNPOD_CONSOLE_URL", lambda: RUNPOD_CONSOLE_URL, DEFAULT_CONSOLE_URL),
)


def _is_opted_out() -> bool:
    return os.environ.get("RUNPOD_URL_MIXED_OK", "").strip().lower() in _TRUTHY


def _check_partial_override() -> None:
    """Warn when some URL envs are overridden but others stay at prod default.

    A partial override is almost always a misconfiguration — the user meant to
    target a non-prod environment but forgot a var. Legitimate mixed setups
    (e.g. dev control plane + prod HAPI) can set ``RUNPOD_URL_MIXED_OK=1`` to
    silence.
    """
    if _is_opted_out():
        return
    overridden = sorted(
        name
        for name, resolver, default in _URL_PROFILE
        if resolver() != default.rstrip("/")
    )
    at_default = sorted(
        name
        for name, resolver, default in _URL_PROFILE
        if resolver() == default.rstrip("/")
    )
    if overridden and at_default:
        warnings.warn(
            "Partial Runpod URL override detected. "
            f"Overridden: {overridden}. Still at default: {at_default}. "
            "This is usually a misconfiguration — set all URLs for the target "
            "environment, or set RUNPOD_URL_MIXED_OK=1 to silence.",
            RuntimeWarning,
            stacklevel=2,
        )


def _check_runpod_env_without_overrides() -> None:
    """Warn when RUNPOD_ENV suggests non-prod but no URL envs are overridden.

    Previously ``request_logs.py`` branched HAPI host off ``RUNPOD_ENV=dev``.
    That branch was removed in favor of explicit ``RUNPOD_HAPI_URL``. This
    check catches the regression: users who relied on ``RUNPOD_ENV`` alone
    would silently hit prod without this warning.
    """
    if _is_opted_out():
        return
    runpod_env = os.environ.get("RUNPOD_ENV", "").strip().lower()
    if not runpod_env or runpod_env == "prod":
        return
    any_override = any(os.environ.get(name, "").strip() for name in _URL_ENV_VARS)
    if any_override:
        return
    warnings.warn(
        f"RUNPOD_ENV={runpod_env!r} is set but no Runpod URL env vars are "
        "overridden — flash will silently route to production hosts. Set "
        "the URL env vars explicitly for your target environment, or set "
        "RUNPOD_URL_MIXED_OK=1 to silence.",
        RuntimeWarning,
        stacklevel=3,
    )


_check_partial_override()
_check_runpod_env_without_overrides()
    return parsed.netloc or "api.runpod.ai"


ENDPOINT_DOMAIN: str = _endpoint_domain_from_base_url(RUNPOD_ENDPOINT_URL)
