"""More focused apps CLI tests that validate asyncio + console wiring."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.panel import Panel
from rich.table import Table
from typer.testing import CliRunner

from runpod_flash.cli.main import app


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def patched_console():
    with patch("runpod_flash.cli.commands.apps.console") as mock_console:
        status_cm = MagicMock()
        status_cm.__enter__.return_value = None
        status_cm.__exit__.return_value = None
        mock_console.status.return_value = status_cm
        yield mock_console


class TestAppsGroup:
    def test_no_subcommand_shows_help(self, runner):
        result = runner.invoke(app, ["app"])
        assert result.exit_code == 0
        assert "Usage" in result.stdout


class TestAppsCreate:
    @patch("runpod_flash.cli.commands.apps.FlashApp.create", new_callable=AsyncMock)
    def test_create_app_success(
        self, mock_create, runner, mock_asyncio_run_coro, patched_console
    ):
        created = MagicMock()
        created.id = "app-987"
        mock_create.return_value = created

        with patch(
            "runpod_flash.cli.commands.apps.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["app", "create", "demo-app"])

        assert result.exit_code == 0
        mock_create.assert_awaited_once_with("demo-app")
        last_call = patched_console.print.call_args_list[-1]
        panel = last_call.args[0]
        assert isinstance(panel, Panel)
        assert "demo-app" in panel.renderable
        assert panel.title == "✅ App Created"

    @patch("runpod_flash.cli.commands.apps.FlashApp.create", new_callable=AsyncMock)
    def test_create_app_failure_bubbles_error(
        self, mock_create, runner, mock_asyncio_run_coro
    ):
        mock_create.side_effect = RuntimeError("boom")

        with patch(
            "runpod_flash.cli.commands.apps.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["app", "create", "demo-app"])

        assert result.exit_code == 1
        assert isinstance(result.exception, RuntimeError)


class TestAppsList:
    @patch("runpod_flash.cli.commands.apps.FlashApp.list", new_callable=AsyncMock)
    def test_list_apps_empty(
        self, mock_list, runner, mock_asyncio_run_coro, patched_console
    ):
        mock_list.return_value = []

        with patch(
            "runpod_flash.cli.commands.apps.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["app", "list"])

        assert result.exit_code == 0
        patched_console.print.assert_called_with("No Flash apps found.")

    @patch("runpod_flash.cli.commands.apps.FlashApp.list", new_callable=AsyncMock)
    def test_list_apps_with_data(
        self, mock_list, runner, mock_asyncio_run_coro, patched_console
    ):
        # Matches actual GraphQL flashApp response structure
        mock_list.return_value = [
            {
                "id": "app-1",
                "name": "demo",
                "flashEnvironments": [
                    {
                        "id": "env-1",
                        "name": "dev",
                        "state": "ACTIVE",
                        "activeBuildId": None,
                        "createdAt": "2024-01-01T00:00:00Z",
                    },
                    {
                        "id": "env-2",
                        "name": "prod",
                        "state": "ACTIVE",
                        "activeBuildId": "build-1",
                        "createdAt": "2024-01-02T00:00:00Z",
                    },
                ],
                "flashBuilds": [
                    {
                        "id": "build-1",
                        "objectKey": "builds/app-1/build-1.tar.gz",
                        "createdAt": "2024-01-01T00:00:00Z",
                    }
                ],
            }
        ]

        with patch(
            "runpod_flash.cli.commands.apps.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["app", "list"])

        assert result.exit_code == 0
        table = patched_console.print.call_args_list[-1].args[0]
        assert isinstance(table, Table)
        columns = table.columns
        assert "demo" in columns[0]._cells[0]
        assert "dev, prod" in columns[2]._cells[0]
        assert "build-1" in columns[3]._cells[0]


class TestAppsGet:
    @patch("runpod_flash.cli.commands.apps.FlashApp.from_name", new_callable=AsyncMock)
    def test_get_app_details(
        self, mock_from_name, runner, mock_asyncio_run_coro, patched_console
    ):
        flash_app = MagicMock()
        flash_app.name = "demo"
        flash_app.id = "app-1"
        flash_app.list_environments = AsyncMock(
            return_value=[
                {
                    "name": "dev",
                    "id": "env-1",
                    "state": "ACTIVE",
                    "activeBuildId": "build-1",
                    "createdAt": "yesterday",
                }
            ]
        )
        flash_app.list_builds = AsyncMock(
            return_value=[{"id": "build-1", "objectKey": "obj", "createdAt": "today"}]
        )
        mock_from_name.return_value = flash_app

        with patch(
            "runpod_flash.cli.commands.apps.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["app", "get", "demo"])

        assert result.exit_code == 0
        mock_from_name.assert_awaited_once_with("demo")
        flash_app.list_environments.assert_awaited_once()
        flash_app.list_builds.assert_awaited_once()
        panel = patched_console.print.call_args_list[0].args[0]
        assert isinstance(panel, Panel)
        assert "Name: demo" in panel.renderable
        env_table = patched_console.print.call_args_list[1].args[0]
        build_table = patched_console.print.call_args_list[2].args[0]
        assert isinstance(env_table, Table)
        assert isinstance(build_table, Table)

    @patch("runpod_flash.cli.commands.apps.FlashApp.from_name", new_callable=AsyncMock)
    def test_get_app_without_related_data(
        self, mock_from_name, runner, mock_asyncio_run_coro, patched_console
    ):
        flash_app = MagicMock()
        flash_app.name = "demo"
        flash_app.id = "app-1"
        flash_app.list_environments = AsyncMock(return_value=[])
        flash_app.list_builds = AsyncMock(return_value=[])
        mock_from_name.return_value = flash_app

        with patch(
            "runpod_flash.cli.commands.apps.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["app", "get", "demo"])

        assert result.exit_code == 0
        assert len(patched_console.print.call_args_list) == 1
        panel = patched_console.print.call_args.args[0]
        assert isinstance(panel, Panel)


class TestAppsDelete:
    @patch("runpod_flash.cli.commands.apps.FlashApp.delete", new_callable=AsyncMock)
    def test_delete_app_success(
        self, mock_delete, runner, mock_asyncio_run_coro, patched_console
    ):
        mock_delete.return_value = True

        with patch(
            "runpod_flash.cli.commands.apps.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["app", "delete", "--app", "demo"])

        assert result.exit_code == 0
        mock_delete.assert_awaited_once_with(app_name="demo")
        patched_console.print.assert_called_with(
            "✅ Flash app 'demo' deleted successfully"
        )

    @patch("runpod_flash.cli.commands.apps.FlashApp.delete", new_callable=AsyncMock)
    def test_delete_app_failure_raises_exit(
        self, mock_delete, runner, mock_asyncio_run_coro, patched_console
    ):
        mock_delete.return_value = False

        with patch(
            "runpod_flash.cli.commands.apps.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["app", "delete", "--app", "demo"])

        assert result.exit_code == 1
        patched_console.print.assert_called_with("❌ Failed to delete flash app 'demo'")

    @patch("runpod_flash.cli.commands.apps.discover_flash_project")
    @patch("runpod_flash.cli.commands.apps.FlashApp.delete", new_callable=AsyncMock)
    def test_delete_app_uses_discovered_name(
        self,
        mock_delete,
        mock_discover,
        runner,
        mock_asyncio_run_coro,
        patched_console,
    ):
        mock_delete.return_value = True
        mock_discover.return_value = ("/tmp/flash", "derived")

        with patch(
            "runpod_flash.cli.commands.apps.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["app", "delete", "--app", ""])

        assert result.exit_code == 0
        mock_discover.assert_called_once()
        mock_delete.assert_awaited_once_with(app_name="derived")
