import asyncio

import typer
from rich.console import Console

from runpod_flash.cli.utils.formatting import print_error
from runpod_flash.core.api.runpod import RunpodGraphQLClient
from runpod_flash.core.credentials import (
    check_and_migrate_legacy_credentials,
    save_api_key,
)
from runpod_flash.core.urls import RUNPOD_CONSOLE_URL

console = Console()


async def _login(open_browser: bool) -> None:
    async with RunpodGraphQLClient(require_api_key=False) as client:
        request = await client.create_flash_auth_request()
        request_id = request.get("id")
        if not request_id:
            raise RuntimeError("auth request failed to initialize")

        auth_url = f"{RUNPOD_CONSOLE_URL}/flash/login?request={request_id}"

        console.print()
        console.print("[bold]Authorize flash in your browser:[/bold]")
        console.print(f"  [link={auth_url}]{auth_url}[/link]")
        console.print()

        if open_browser:
            typer.launch(auth_url)

    api_key = console.input(
        "Paste the API key shown after authorization: "
    ).strip()

    if not api_key:
        raise RuntimeError("no api key provided")

    check_and_migrate_legacy_credentials()
    path = save_api_key(api_key)
    console.print(
        f"[green]Logged in.[/green] Credentials saved to [dim]{path}[/dim]"
    )
    console.print()


def login_command(
    no_open: bool = typer.Option(False, "--no-open", help="do not open the browser"),
):
    """Authenticate and save a Runpod API key for flash."""
    try:
        asyncio.run(_login(open_browser=not no_open))
    except RuntimeError as exc:
        print_error(console, str(exc))
        raise typer.Exit(code=1)
