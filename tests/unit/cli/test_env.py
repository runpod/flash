"""Unit tests for flash env CLI commands."""

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
    with patch("runpod_flash.cli.commands.env.console") as mock_console:
        status_cm = MagicMock()
        status_cm.__enter__.return_value = None
        status_cm.__exit__.return_value = None
        mock_console.status.return_value = status_cm
        yield mock_console


class TestEnvList:
    @patch("runpod_flash.cli.commands.env.FlashApp.from_name", new_callable=AsyncMock)
    def test_list_environments_empty(
        self, mock_from_name, runner, mock_asyncio_run_coro, patched_console
    ):
        flash_app = MagicMock()
        flash_app.list_environments = AsyncMock(return_value=[])
        mock_from_name.return_value = flash_app

        with patch(
            "runpod_flash.cli.commands.env.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["env", "list", "--app", "demo"])

        assert result.exit_code == 0
        patched_console.print.assert_called_with("No environments found for 'demo'.")
        mock_from_name.assert_awaited_once_with("demo")

    @patch("runpod_flash.cli.commands.env.FlashApp.from_name", new_callable=AsyncMock)
    def test_list_environments_with_data(
        self, mock_from_name, runner, mock_asyncio_run_coro, patched_console
    ):
        flash_app = MagicMock()
        flash_app.list_environments = AsyncMock(
            return_value=[
                {
                    "id": "env-1",
                    "name": "dev",
                    "activeBuildId": "build-1",
                    "createdAt": "2024-01-01",
                }
            ]
        )
        mock_from_name.return_value = flash_app

        with patch(
            "runpod_flash.cli.commands.env.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["env", "list", "--app", "demo"])

        assert result.exit_code == 0
        table = patched_console.print.call_args_list[-1].args[0]
        assert isinstance(table, Table)
        assert table.columns[0]._cells[0] == "dev"
        assert table.columns[2]._cells[0] == "build-1"

    @patch("runpod_flash.cli.commands.env.discover_flash_project")
    @patch("runpod_flash.cli.commands.env.FlashApp.from_name", new_callable=AsyncMock)
    def test_list_envs_uses_discovery(
        self,
        mock_from_name,
        mock_discover,
        runner,
        mock_asyncio_run_coro,
        patched_console,
    ):
        mock_discover.return_value = ("/tmp/project", "derived")
        flash_app = MagicMock()
        flash_app.list_environments = AsyncMock(return_value=[])
        mock_from_name.return_value = flash_app

        with patch(
            "runpod_flash.cli.commands.env.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["env", "list"])

        assert result.exit_code == 0
        mock_discover.assert_called_once()
        mock_from_name.assert_awaited_once_with("derived")


class TestEnvCreate:
    @patch(
        "runpod_flash.cli.commands.env.FlashApp.create_environment_and_app",
        new_callable=AsyncMock,
    )
    def test_create_environment_success(
        self, mock_create, runner, mock_asyncio_run_coro, patched_console
    ):
        mock_app = MagicMock()
        mock_app.id = "app-1"
        mock_env = {
            "id": "env-123",
            "name": "dev",
            "state": "PENDING",
            "createdAt": "now",
        }
        mock_create.return_value = (mock_app, mock_env)

        with patch(
            "runpod_flash.cli.commands.env.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["env", "create", "dev", "--app", "demo"])

        assert result.exit_code == 0
        mock_create.assert_awaited_once_with("demo", "dev")
        panel = patched_console.print.call_args_list[0].args[0]
        assert isinstance(panel, Panel)
        assert "[bold]dev[/bold]" in panel.renderable
        table = patched_console.print.call_args_list[1].args[0]
        assert isinstance(table, Table)


class TestEnvGet:
    @patch("runpod_flash.cli.commands.env.FlashApp.from_name", new_callable=AsyncMock)
    def test_get_includes_children(
        self, mock_from_name, runner, mock_asyncio_run_coro, patched_console
    ):
        flash_app = MagicMock()
        flash_app.get_environment_by_name = AsyncMock(
            return_value={
                "id": "env-1",
                "name": "dev",
                "state": "HEALTHY",
                "activeBuildId": "build-9",
                "createdAt": "today",
                "endpoints": [{"name": "http", "id": "ep-1"}],
                "networkVolumes": [{"name": "nv", "id": "nv-1"}],
            }
        )
        mock_from_name.return_value = flash_app

        with patch(
            "runpod_flash.cli.commands.env.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["env", "get", "dev", "--app", "demo"])

        assert result.exit_code == 0
        panel = patched_console.print.call_args_list[0].args[0]
        assert isinstance(panel, Panel)
        endpoint_table = patched_console.print.call_args_list[1].args[0]
        network_table = patched_console.print.call_args_list[2].args[0]
        assert isinstance(endpoint_table, Table)
        assert isinstance(network_table, Table)

    @patch("runpod_flash.cli.commands.env.FlashApp.from_name", new_callable=AsyncMock)
    def test_get_without_children(
        self, mock_from_name, runner, mock_asyncio_run_coro, patched_console
    ):
        flash_app = MagicMock()
        flash_app.get_environment_by_name = AsyncMock(
            return_value={
                "id": "env-1",
                "name": "dev",
                "state": "PENDING",
                "activeBuildId": None,
                "createdAt": None,
                "endpoints": [],
                "networkVolumes": [],
            }
        )
        mock_from_name.return_value = flash_app

        with patch(
            "runpod_flash.cli.commands.env.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["env", "get", "dev", "--app", "demo"])

        assert result.exit_code == 0
        # Only the panel should be printed when there are no child resources
        assert len(patched_console.print.call_args_list) == 1
        assert isinstance(patched_console.print.call_args.args[0], Panel)


class TestEnvDelete:
    @patch(
        "runpod_flash.cli.commands.env._fetch_environment_info",
        new_callable=AsyncMock,
    )
    @patch("runpod_flash.cli.commands.env.questionary")
    @patch("runpod_flash.cli.commands.env.FlashApp.from_name", new_callable=AsyncMock)
    def test_delete_environment_success(
        self,
        mock_from_name,
        mock_questionary,
        mock_fetch_env,
        runner,
        mock_asyncio_run_coro,
        patched_console,
    ):
        mock_fetch_env.return_value = {
            "id": "env-1",
            "name": "dev",
            "activeBuildId": "build-1",
        }

        flash_app = MagicMock()
        flash_app.get_environment_by_name = AsyncMock(
            return_value=mock_fetch_env.return_value
        )
        flash_app.delete_environment = AsyncMock(return_value=True)
        mock_from_name.return_value = flash_app

        confirm = MagicMock()
        confirm.ask.return_value = True
        mock_questionary.confirm.return_value = confirm

        with patch(
            "runpod_flash.cli.commands.env.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["env", "delete", "dev", "--app", "demo"])

        assert result.exit_code == 0
        mock_questionary.confirm.assert_called_once()
        flash_app.delete_environment.assert_awaited_once_with("dev")
        patched_console.print.assert_any_call("Environment 'dev' deleted successfully")

    @patch(
        "runpod_flash.cli.commands.env._fetch_environment_info",
        new_callable=AsyncMock,
    )
    @patch("runpod_flash.cli.commands.env.questionary")
    @patch("runpod_flash.cli.commands.env.FlashApp.from_name", new_callable=AsyncMock)
    def test_delete_environment_cancelled(
        self,
        mock_from_name,
        mock_questionary,
        mock_fetch_env,
        runner,
        mock_asyncio_run_coro,
        patched_console,
    ):
        mock_fetch_env.return_value = {
            "id": "env-1",
            "name": "dev",
            "activeBuildId": None,
        }

        flash_app = MagicMock()
        mock_from_name.return_value = flash_app

        confirm = MagicMock()
        confirm.ask.return_value = False
        mock_questionary.confirm.return_value = confirm

        with patch(
            "runpod_flash.cli.commands.env.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["env", "delete", "dev", "--app", "demo"])

        assert result.exit_code == 0
        mock_questionary.confirm.assert_called_once()
        flash_app.delete_environment.assert_not_called()
        patched_console.print.assert_any_call("Deletion cancelled")

    @patch(
        "runpod_flash.cli.commands.env._fetch_environment_info",
        new_callable=AsyncMock,
    )
    @patch("runpod_flash.cli.commands.env.questionary")
    @patch("runpod_flash.cli.commands.env.FlashApp.from_name", new_callable=AsyncMock)
    def test_delete_environment_failure(
        self,
        mock_from_name,
        mock_questionary,
        mock_fetch_env,
        runner,
        mock_asyncio_run_coro,
        patched_console,
    ):
        mock_fetch_env.return_value = {
            "id": "env-1",
            "name": "dev",
            "activeBuildId": None,
        }

        flash_app = MagicMock()
        flash_app.get_environment_by_name = AsyncMock(
            return_value=mock_fetch_env.return_value
        )
        flash_app.delete_environment = AsyncMock(return_value=False)
        mock_from_name.return_value = flash_app

        confirm = MagicMock()
        confirm.ask.return_value = True
        mock_questionary.confirm.return_value = confirm

        with patch(
            "runpod_flash.cli.commands.env.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["env", "delete", "dev", "--app", "demo"])

        assert result.exit_code == 1
        flash_app.delete_environment.assert_awaited_once_with("dev")
        patched_console.print.assert_any_call(
            "[red]Failed to delete environment 'dev'[/red]"
        )
