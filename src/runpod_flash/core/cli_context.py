"""CLI-invocation context for guarding lifecycle operations.

Endpoint/app lifecycle operations (deploy, undeploy, update, app/environment
management) are managed by the flash CLI, which orchestrates the build/manifest
pipeline and records local state. Calling those methods directly from the SDK
skips that orchestration and leaves state inconsistent.

This module provides a process-scoped flag, set once at the CLI entry point, and
a `cli_only` decorator that raises :class:`FlashUsageError` when a guarded method
is called outside that context. `allow_lifecycle_operations` is the sanctioned
escape hatch for first-party code (e.g. tests) that must drive lifecycle without
going through the CLI process.

Why a ContextVar and not an env var: it propagates automatically into the
asyncio task spawned by the CLI command (`asyncio.run` copies the current
context), needs no cleanup in a one-shot CLI process, and is trivially scoped in
tests via `allow_lifecycle_operations`.
"""

import functools
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TypeVar

from .exceptions import FlashUsageError

_invoked_by_cli: ContextVar[bool] = ContextVar("flash_invoked_by_cli", default=False)

_T = TypeVar("_T")


def mark_cli_invocation() -> None:
    """Mark the current context as a flash CLI invocation.

    Called once from the CLI entry point. Set-and-leave: a Typer callback returns
    before the command runs, so a context-manager scope cannot wrap the command.
    A plain set is correct for a one-shot CLI process and propagates into the
    command's ``asyncio.run()`` context.
    """
    _invoked_by_cli.set(True)


def is_cli_invocation() -> bool:
    """Return whether lifecycle operations are currently permitted."""
    return _invoked_by_cli.get()


@contextmanager
def allow_lifecycle_operations():
    """Permit guarded lifecycle operations within this block.

    Sanctioned escape hatch for first-party code that must drive resource
    lifecycle without going through the CLI process (notably tests). Restores the
    previous state on exit.

    Example:
        with allow_lifecycle_operations():
            await endpoint.deploy()
    """
    token = _invoked_by_cli.set(True)
    try:
        yield
    finally:
        _invoked_by_cli.reset(token)


def cli_only(
    cli_command: str,
) -> Callable[[Callable[..., Awaitable[_T]]], Callable[..., Awaitable[_T]]]:
    """Restrict an async lifecycle method to flash CLI invocation.

    Args:
        cli_command: The equivalent flash CLI command, surfaced in the error
            (e.g. ``"flash deploy"``).

    Raises:
        FlashUsageError: When the decorated method is called outside a CLI
            context or an :func:`allow_lifecycle_operations` block.
    """

    def decorator(func: Callable[..., Awaitable[_T]]) -> Callable[..., Awaitable[_T]]:
        @functools.wraps(func)
        async def wrapper(*args: object, **kwargs: object) -> _T:
            if not _invoked_by_cli.get():
                raise FlashUsageError(
                    f"{func.__qualname__}() is a CLI-managed operation and cannot "
                    f"be called directly from the SDK.\n\n"
                    f"    Use:  {cli_command}\n\n"
                    "Direct SDK calls bypass flash's build/manifest pipeline and "
                    "local state tracking, leaving deployments inconsistent."
                )
            return await func(*args, **kwargs)

        return wrapper

    return decorator
