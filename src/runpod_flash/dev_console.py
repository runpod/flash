"""console output for flash dev runtime.

G1a format: timestamp + name prefix + colored phase labels.

    17:43:01 POST /gpu_worker/runsync
    17:43:01 gpu_worker │ waiting no gpu availability for ADA_24
    17:43:10 gpu_worker │ pulling flash-gpu:py3.12-latest
    17:43:55 gpu_worker │ ready xk29fjal
    17:43:56 gpu_worker │ hello from gpu worker
    17:43:57 ✓ gpu_worker 0.1s  queued 55.1s
"""

import time
from datetime import datetime

from rich.console import Console

console = Console(highlight=False)

_LIVE_PREFIX = "live-"


def _name(name: str) -> str:
    """strip internal 'live-' prefix from endpoint names for display."""
    if name.startswith(_LIVE_PREFIX):
        return name[len(_LIVE_PREFIX) :]
    return name


def _ts() -> str:
    """current wall-clock time as HH:MM:SS, dim."""
    return f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim]"


def _pipe(name: str) -> str:
    """name │ prefix for worker log lines."""
    return f"{name} [dim]│[/dim]"


# -- request lifecycle --


def print_dispatch(name: str, method: str = "POST", path: str | None = None) -> None:
    """print the incoming request line."""
    name = _name(name)
    route = path or f"/{name}/runsync"
    console.print(f"{_ts()} [white]{method}[/white] {route}")


def print_diagnostic(name: str, message: str) -> None:
    """print a waiting/diagnostic message (yellow label)."""
    name = _name(name)
    console.print(f"{_ts()} {_pipe(name)} [yellow]waiting[/yellow] [dim]{message}[/dim]")


def print_pulling(name: str, image: str, worker_id: str | None = None) -> "PullProgress":
    """print pulling message and return a handle to finalize."""
    name = _name(name)
    return PullProgress(name, image, worker_id)


def print_worker_ready(name: str, worker_id: str) -> None:
    """print when a worker is ready to execute."""
    name = _name(name)
    short_id = worker_id[:8] if len(worker_id) > 8 else worker_id
    console.print(f"{_ts()} {_pipe(name)} [green]ready[/green] [dim]{short_id}[/dim]")


def print_worker_log(name: str, line: str) -> None:
    """print a user log line from the worker."""
    name = _name(name)
    console.print(f"{_ts()} {_pipe(name)} {line}")


def print_completed(name: str, elapsed_ms: int | None, delay_ms: int | None) -> None:
    name = _name(name)
    timing = _format_timing(elapsed_ms, delay_ms)
    console.print(f"{_ts()} [green]✓[/green] {name} {timing}")


def print_failed(
    name: str,
    elapsed_ms: int | None,
    delay_ms: int | None,
    error: str | None = None,
) -> None:
    name = _name(name)
    timing = _format_timing(elapsed_ms, delay_ms)
    console.print(f"{_ts()} [red]✗[/red] {name} {timing}")
    if error:
        console.print(f"         [dim]{error}[/dim]")


def print_cancelled(name: str, elapsed_ms: int | None, delay_ms: int | None) -> None:
    name = _name(name)
    timing = _format_timing(elapsed_ms, delay_ms)
    console.print(f"{_ts()} [yellow]–[/yellow] {name} [dim]cancelled[/dim] {timing}")


# -- load balancer requests --


def print_lb_request(name: str, method: str, path: str) -> None:
    name = _name(name)
    console.print(f"{_ts()} [white]{method}[/white] {path}")


def print_lb_completed(name: str, elapsed_s: float) -> None:
    name = _name(name)
    console.print(f"{_ts()} [green]✓[/green] {name} [dim]{elapsed_s:.1f}s[/dim]")


def print_lb_failed(name: str, error: str) -> None:
    name = _name(name)
    console.print(f"{_ts()} [red]✗[/red] {name}")
    console.print(f"         [dim]{error}[/dim]")


# -- helpers --


def _format_timing(elapsed_ms: int | None, delay_ms: int | None) -> str:
    if elapsed_ms is None:
        return ""
    exec_s = elapsed_ms / 1000
    if delay_ms and delay_ms > 1000:
        queue_s = delay_ms / 1000
        return f"[dim]{exec_s:.1f}s  queued {queue_s:.1f}s[/dim]"
    return f"[dim]{exec_s:.1f}s[/dim]"


def _short_image(image: str) -> str:
    """shorten a docker image name for display.

    'runpod/flash-cpu:py3.12-latest' -> 'flash-cpu:py3.12-latest'
    """
    if "/" in image:
        return image.split("/", 1)[1]
    return image


class PullProgress:
    """tracks elapsed time for an image pull."""

    def __init__(self, name: str, image: str, worker_id: str | None = None):
        self.name = name
        self.image = image
        self.worker_id = worker_id
        self._start = time.monotonic()
        short = _short_image(image)
        console.print(f"{_ts()} {_pipe(name)} [blue]pulling[/blue] {short}")

    def update(self) -> None:
        pass

    def done(self) -> None:
        elapsed = int(time.monotonic() - self._start)
        short = _short_image(self.image)
        console.print(
            f"{_ts()} {_pipe(self.name)} [blue]pulled[/blue] {short} [dim]{elapsed}s[/dim]"
        )
