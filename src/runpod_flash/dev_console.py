"""console output for flash dev runtime."""

import time
from datetime import datetime

from rich.console import Console

console = Console(highlight=False)

_LIVE_PREFIX = "live-"

# set by the dev server at startup so all name columns align
_name_width: int = 0


def set_name_width(names: list[str]) -> None:
    """compute and store the max display name width for column alignment."""
    global _name_width
    _name_width = max((len(_strip_prefix(n)) for n in names), default=0)


def _strip_prefix(name: str) -> str:
    if name.startswith(_LIVE_PREFIX):
        return name[len(_LIVE_PREFIX) :]
    return name


def _name(name: str) -> str:
    """strip live- prefix."""
    return _strip_prefix(name)


def _padded(name: str) -> str:
    """strip live- prefix and pad to the shared column width."""
    n = _strip_prefix(name)
    if _name_width:
        return f"{n:<{_name_width}}"
    return n


def _ts() -> str:
    return f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim]"


def _pipe(raw_name: str) -> str:
    """padded name │ prefix. accepts raw name (with or without live- prefix)."""
    return f"{_padded(raw_name)} [dim]│[/dim]"


# -- request lifecycle --


def print_dispatch(name: str, method: str = "POST", path: str | None = None) -> None:
    """print the incoming request line."""
    name = _name(name)
    route = path or f"/{name}/runsync"
    console.print(f"{_ts()} [white]{method}[/white] {route}")


def print_diagnostic(name: str, message: str) -> None:
    console.print(f"{_ts()} {_pipe(name)} [yellow]waiting[/yellow] [dim]{message}[/dim]")


def print_pulling(name: str, image: str, worker_id: str | None = None) -> "PullProgress":
    return PullProgress(name, image, worker_id)


def print_worker_ready(name: str, worker_id: str) -> None:
    short_id = worker_id[:8] if len(worker_id) > 8 else worker_id
    console.print(f"{_ts()} {_pipe(name)} [green]ready[/green] [dim]{short_id}[/dim]")


def print_worker_log(name: str, line: str) -> None:
    console.print(f"{_ts()} {_pipe(name)} {line}")


def print_completed(name: str, elapsed_ms: int | None, delay_ms: int | None) -> None:
    timing = _format_timing(elapsed_ms, delay_ms)
    console.print(f"{_ts()} [green]✓[/green] {_padded(name)} {timing}")


def print_failed(
    name: str,
    elapsed_ms: int | None,
    delay_ms: int | None,
    error: str | None = None,
) -> None:
    timing = _format_timing(elapsed_ms, delay_ms)
    console.print(f"{_ts()} [red]✗[/red] {_padded(name)} {timing}")
    if error:
        console.print(f"         [dim]{error}[/dim]")


def print_cancelled(name: str, elapsed_ms: int | None, delay_ms: int | None) -> None:
    timing = _format_timing(elapsed_ms, delay_ms)
    console.print(f"{_ts()} [yellow]–[/yellow] {_padded(name)} [dim]cancelled[/dim] {timing}")


# -- load balancer requests --


def print_lb_request(name: str, method: str, path: str) -> None:
    console.print(f"{_ts()} [white]{method}[/white] {path}")


def print_lb_completed(name: str, elapsed_s: float) -> None:
    console.print(f"{_ts()} [green]✓[/green] {_padded(name)} [dim]{elapsed_s:.1f}s[/dim]")


def print_lb_failed(name: str, error: str) -> None:
    console.print(f"{_ts()} [red]✗[/red] {_padded(name)}")
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
