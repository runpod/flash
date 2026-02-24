import asyncio
import datetime as dt
from typing import Optional

import typer
from rich.console import Console

from runpod_flash.core.api.runpod import RunpodGraphQLClient
from runpod_flash.core.credentials import save_api_key
from runpod_flash.core.resources.constants import CONSOLE_BASE_URL

console = Console()

POLL_INTERVAL_SECONDS = 2.0
DEFAULT_TIMEOUT_SECONDS = 600.0


def _parse_expires_at(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _login_async(open_browser: bool, timeout_seconds: float) -> None:
    async with RunpodGraphQLClient(require_api_key=False) as client:
        request = await client.create_flash_auth_request()
        request_id = request.get("id")
        if not request_id:
            raise RuntimeError("auth request failed to initialize")

        auth_url = f"{CONSOLE_BASE_URL}/flash/login?request={request_id}"

        console.print()
        console.print("[bold]Authorize flash in your browser:[/bold]")
        console.print(f"  [link={auth_url}]{auth_url}[/link]")
        console.print()

        if open_browser:
            typer.launch(auth_url)

        expires_at = _parse_expires_at(request.get("expiresAt"))
        deadline = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
            seconds=timeout_seconds
        )
        if expires_at and expires_at < deadline:
            deadline = expires_at

        with console.status("[dim]Waiting for authorization...[/dim]"):
            while True:
                status_payload = await client.get_flash_auth_request_status(request_id)
                status = status_payload.get("status")
                api_key = status_payload.get("apiKey")

                if api_key and status in {"APPROVED", "CONSUMED"}:
                    path = save_api_key(api_key)
                    console.print(
                        f"[green]Logged in.[/green] Credentials saved to [dim]{path}[/dim]"
                    )
                    console.print()
                    return

                if status in {"DENIED", "EXPIRED", "CONSUMED"}:
                    raise RuntimeError(f"login failed: {status.lower()}")

                if dt.datetime.now(dt.timezone.utc) >= deadline:
                    raise RuntimeError("login timed out")

                await asyncio.sleep(POLL_INTERVAL_SECONDS)


def login_command(
    no_open: bool = typer.Option(False, "--no-open", help="do not open the browser"),
    timeout: float = typer.Option(
        DEFAULT_TIMEOUT_SECONDS, "--timeout", help="max wait time in seconds"
    ),
):
    """Authenticate and save a Runpod API key for flash."""
    try:
        asyncio.run(_login_async(open_browser=not no_open, timeout_seconds=timeout))
    except RuntimeError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1)
