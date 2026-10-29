"""Package-level deprecation notice for runpod-flash.

Flash has moved into the Runpod Python SDK 2.0. This module owns the notice
users see once the package is deprecated, shown once per process through
one of two channels:

- the ``flash`` CLI prints it to stderr on every invocation (stdout stays
  clean for scripts that parse ``flash --version`` and similar output)
- SDK users get a ``FutureWarning`` on first access to the public API
  (``runpod_flash.Endpoint`` etc.). ``FutureWarning`` is used instead of
  ``DeprecationWarning`` because Python hides the latter by default unless
  triggered from ``__main__``.

Deployed workers (``RUNPOD_ENDPOINT_ID`` / ``RUNPOD_POD_ID`` set) skip the
warning: it would repeat on every cold start in endpoint logs, where nobody
can act on it.

Set ``RUNPOD_FLASH_SILENCE_DEPRECATION=1`` to silence both channels (e.g. in CI).
"""

import os
import sys
import warnings

SUNSET_DATE = "October 29, 2026"
MIGRATION_GUIDE_URL = "https://docs.runpod.io/sdk/migrate-from-flash"

SUNSET_MESSAGE = (
    "Flash has moved into the Runpod Python SDK 2.0. runpod-flash was "
    f"deprecated on {SUNSET_DATE} and receives no fixes or updates. "
    f"Migration guide: {MIGRATION_GUIDE_URL}"
)

_WORKER_ENV_VARS = ("RUNPOD_ENDPOINT_ID", "RUNPOD_POD_ID")
_SILENCE_ENV_VAR = "RUNPOD_FLASH_SILENCE_DEPRECATION"
_TRUTHY = ("1", "true", "yes", "on")

# frames between warn_on_import() and the user's attribute access:
# warn_on_import -> runpod_flash.__getattr__ -> caller
_CALLER_STACKLEVEL = 3

_notice_shown = False


def _is_deployed_worker() -> bool:
    return any(os.getenv(var) for var in _WORKER_ENV_VARS)


def _is_silenced() -> bool:
    return os.getenv(_SILENCE_ENV_VAR, "").strip().lower() in _TRUTHY


def warn_on_import() -> None:
    """Emit the sunset FutureWarning once per process, attributed to the caller."""
    global _notice_shown
    if _notice_shown or _is_deployed_worker() or _is_silenced():
        return
    _notice_shown = True
    warnings.warn(SUNSET_MESSAGE, FutureWarning, stacklevel=_CALLER_STACKLEVEL)


def print_cli_notice() -> None:
    """Print the sunset notice to stderr and suppress the import warning."""
    global _notice_shown
    _notice_shown = True
    if _is_silenced():
        return
    # resolve sys.stderr at call time so CliRunner and redirected streams capture it
    from rich.console import Console

    Console(file=sys.stderr).print(
        f"[bold yellow]Deprecation notice:[/bold yellow] {SUNSET_MESSAGE}",
        highlight=False,
        soft_wrap=True,
    )
