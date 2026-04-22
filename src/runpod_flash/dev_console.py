"""console output for flash dev runtime.

provides a shared rich console and helper functions for printing
request lifecycle events (dispatch, pulling, worker ready, user
output, completion) during `flash dev`.
"""

import time

from rich.console import Console
from rich.text import Text

console = Console(highlight=False)

# indentation: 2 spaces for top-level (→/✓/✗), 4 spaces for nested
_L1 = "  "
_L2 = "    "


def print_dispatch(name: str) -> None:
    """print the request dispatch line."""
    console.print(f"{_L1}[white]→[/white] [bold]{name}[/bold]")


def print_pulling(image: str, worker_id: str | None = None) -> "PullProgress":
    """start an in-place pulling spinner. returns a handle to stop it."""
    return PullProgress(image, worker_id)


def print_worker_ready(worker_id: str) -> None:
    console.print(f"{_L2}[dim]worker {worker_id} ready[/dim]")


def print_diagnostic(message: str) -> None:
    console.print(f"{_L2}[dim]{message}[/dim]")


def print_worker_log(line: str) -> None:
    """print a user log line from the worker."""
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
    console.print(f"{_L1}[white]→[/white] [bold]{name}[/bold]  [dim]{method} {path}[/dim]")


def print_lb_completed(name: str, elapsed_s: float) -> None:
    console.print(f"{_L1}[green]✓[/green] [bold]{name}[/bold]  [dim]{elapsed_s:.1f}s[/dim]")


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
    """in-place spinner for image pulling.

    the spinner character occupies ~2 columns, so the message is
    indented by 2 fewer spaces to keep the text aligned with other
    L2-indented lines.
    """

    def __init__(self, image: str, worker_id: str | None = None):
        self.image = image
        self.worker_id = worker_id
        self._start = time.monotonic()
        self._status = console.status(
            self._render(),
            spinner="dots",
            spinner_style="dim",
        )
        self._status.start()

    def _render(self) -> Text:
        elapsed = int(time.monotonic() - self._start)
        # 2 leading spaces (spinner adds ~2 chars to reach L2 alignment)
        return Text.from_markup(f"  [dim]pulling {self.image}  {elapsed}s[/dim]")

    def update(self) -> None:
        self._status.update(self._render())

    def done(self) -> None:
        self._status.stop()
        elapsed = int(time.monotonic() - self._start)
        console.print(f"{_L2}[dim]pulled {self.image}  {elapsed}s[/dim]")
