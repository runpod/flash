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


def print_dispatch(name: str) -> None:
    console.print(f"{_L1}[white]→[/white] [bold]{name}[/bold]")


def print_pulling(image: str, worker_id: str | None = None) -> "PullProgress":
    """print pulling message. returns a handle to finalize with elapsed time."""
    return PullProgress(image, worker_id)


def print_worker_ready(worker_id: str) -> None:
    console.print(f"{_L2}[dim]worker {worker_id} ready[/dim]")


def print_diagnostic(message: str) -> None:
    console.print(f"{_L2}[dim]{message}[/dim]")


def print_worker_log(line: str) -> None:
    console.print(f"{_L2}{line}")


def print_completed(name: str, elapsed_ms: int | None, delay_ms: int | None) -> None:
    timing = _format_timing(elapsed_ms, delay_ms)
    console.print(f"{_L1}[green]✓[/green] [bold]{name}[/bold]  [dim]{timing}[/dim]")


def print_failed(
    name: str,
    elapsed_ms: int | None,
    delay_ms: int | None,
    error: str | None = None,
) -> None:
    timing = _format_timing(elapsed_ms, delay_ms)
    console.print(f"{_L1}[red]✗[/red] [bold]{name}[/bold]  [dim]{timing}[/dim]")
    if error:
        console.print(f"{_L2}[dim]{error}[/dim]")


def print_cancelled(name: str, elapsed_ms: int | None, delay_ms: int | None) -> None:
    timing = _format_timing(elapsed_ms, delay_ms)
    console.print(
        f"{_L1}[yellow]–[/yellow] [bold]{name}[/bold]  [dim]cancelled{timing}[/dim]"
    )


def print_lb_request(name: str, method: str, path: str) -> None:
    console.print(
        f"{_L1}[white]→[/white] [bold]{name}[/bold]  [dim]{method} {path}[/dim]"
    )


def print_lb_completed(name: str, elapsed_s: float) -> None:
    console.print(
        f"{_L1}[green]✓[/green] [bold]{name}[/bold]  [dim]{elapsed_s:.1f}s[/dim]"
    )


def print_lb_failed(name: str, error: str) -> None:
    console.print(f"{_L1}[red]✗[/red] [bold]{name}[/bold]")
    console.print(f"{_L2}[dim]{error}[/dim]")


def _format_timing(elapsed_ms: int | None, delay_ms: int | None) -> str:
    if elapsed_ms is None:
        return ""
    parts = [f"{elapsed_ms / 1000:.1f}s"]
    if delay_ms and delay_ms > 1000:
        parts.append(f"queued {delay_ms / 1000:.1f}s")
    return "  ".join(parts)


class PullProgress:
    """tracks elapsed time for an image pull.

    prints a one-time "pulling <image>" line on creation.
    call done() to print the final "pulled <image>  Ns" line.
    safe to use with multiple concurrent requests since it does
    not use Live/Status (which fight over the terminal).
    """

    def __init__(self, image: str, worker_id: str | None = None):
        self.image = image
        self.worker_id = worker_id
        self._start = time.monotonic()
        console.print(f"{_L2}[dim]pulling {self.image}[/dim]")

    def update(self) -> None:
        pass

    def done(self) -> None:
        elapsed = int(time.monotonic() - self._start)
        console.print(f"{_L2}[dim]pulled {self.image}  {elapsed}s[/dim]")
