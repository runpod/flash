"""console output for flash dev runtime.

provides a shared rich console and helper functions for printing
request lifecycle events (dispatch, pulling, worker ready, user
output, completion) during `flash dev`.
"""

import time

from rich.console import Console

console = Console(highlight=False)

# indentation: 2 spaces for top-level (→/✓/✗), 4 spaces for nested
_L1 = "  "
_L2 = "    "
# middle dot separator for structured info
_DOT = "[dim]·[/dim]"


def print_dispatch(name: str) -> None:
    console.print()
    console.print(f"{_L1}[bold white]→ {name}[/bold white]")


def print_pulling(image: str, worker_id: str | None = None) -> "PullProgress":
    """print pulling message. returns a handle to finalize with elapsed time."""
    return PullProgress(image, worker_id)


def print_worker_ready(worker_id: str) -> None:
    short_id = worker_id[:8] if len(worker_id) > 8 else worker_id
    console.print(f"{_L2}[green]●[/green] [dim]ready {_DOT} {short_id}[/dim]")


def print_diagnostic(message: str) -> None:
    console.print(f"{_L2}[yellow]○[/yellow] [dim]{message}[/dim]")


def print_worker_log(line: str) -> None:
    console.print(f"{_L2}{line}")


def print_completed(name: str, elapsed_ms: int | None, delay_ms: int | None) -> None:
    timing = _format_timing(elapsed_ms, delay_ms)
    console.print(f"{_L1}[green]✓ {name}[/green]  {timing}")


def print_failed(
    name: str,
    elapsed_ms: int | None,
    delay_ms: int | None,
    error: str | None = None,
) -> None:
    timing = _format_timing(elapsed_ms, delay_ms)
    console.print(f"{_L1}[red]✗ {name}[/red]  {timing}")
    if error:
        console.print(f"{_L2}[dim]{error}[/dim]")


def print_cancelled(name: str, elapsed_ms: int | None, delay_ms: int | None) -> None:
    timing = _format_timing(elapsed_ms, delay_ms)
    console.print(f"{_L1}[yellow]– {name}[/yellow]  [dim]cancelled[/dim]  {timing}")


def print_lb_request(name: str, method: str, path: str) -> None:
    console.print()
    console.print(
        f"{_L1}[bold white]→ {name}[/bold white]  [dim]{method} {path}[/dim]"
    )


def print_lb_completed(name: str, elapsed_s: float) -> None:
    console.print(f"{_L1}[green]✓ {name}[/green]  [dim]{elapsed_s:.1f}s[/dim]")


def print_lb_failed(name: str, error: str) -> None:
    console.print(f"{_L1}[red]✗ {name}[/red]")
    console.print(f"{_L2}[dim]{error}[/dim]")


def _format_timing(elapsed_ms: int | None, delay_ms: int | None) -> str:
    if elapsed_ms is None:
        return ""
    exec_s = elapsed_ms / 1000
    if delay_ms and delay_ms > 1000:
        queue_s = delay_ms / 1000
        return f"[dim]{exec_s:.1f}s[/dim] {_DOT} [dim]queued {queue_s:.1f}s[/dim]"
    return f"[dim]{exec_s:.1f}s[/dim]"


class PullProgress:
    """tracks elapsed time for an image pull.

    prints a one-time message on creation. call done() to print
    the finalized line with elapsed time. safe for concurrent
    requests (no Live/Status).
    """

    def __init__(self, image: str, worker_id: str | None = None):
        self.image = image
        self.worker_id = worker_id
        self._start = time.monotonic()
        short = _short_image(image)
        console.print(f"{_L2}[dim]◌ pulling {short}[/dim]")

    def update(self) -> None:
        pass

    def done(self) -> None:
        elapsed = int(time.monotonic() - self._start)
        short = _short_image(self.image)
        console.print(f"{_L2}[dim]● pulled {short}[/dim] {_DOT} [dim]{elapsed}s[/dim]")


def _short_image(image: str) -> str:
    """shorten a docker image name for display.

    'runpod/flash-cpu:py3.12-latest' -> 'flash-cpu:py3.12-latest'
    """
    if "/" in image:
        return image.split("/", 1)[1]
    return image
