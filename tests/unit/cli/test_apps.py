"""Unit tests for apps CLI commands."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
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
        printed = " ".join(
            str(call.args[0])
            for call in patched_console.print.call_args_list
            if call.args
        )
        assert "demo-app" in printed
        assert "app-987" in printed

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
        printed = " ".join(
            str(call.args[0])
            for call in patched_console.print.call_args_list
            if call.args
        )
        assert "No Flash apps found" in printed

    @patch("runpod_flash.cli.commands.apps.FlashApp.list", new_callable=AsyncMock)
    def test_list_apps_with_data(
        self, mock_list, runner, mock_asyncio_run_coro, patched_console
    ):
        mock_list.return_value = [
            {
                "id": "app-1",
                "name": "demo",
                "flashEnvironments": [
                    {"id": "env-1", "name": "dev"},
                    {"id": "env-2", "name": "prod"},
                ],
                "flashBuilds": [{"id": "build-1"}],
            }
        ]

        with patch(
            "runpod_flash.cli.commands.apps.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["app", "list"])

        assert result.exit_code == 0
        printed = " ".join(
            str(call.args[0])
            for call in patched_console.print.call_args_list
            if call.args
        )
        assert "demo" in printed
        assert "dev" in printed
        assert "prod" in printed


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
        printed = " ".join(
            str(call.args[0])
            for call in patched_console.print.call_args_list
            if call.args
        )
        assert "demo" in printed
        assert "Environments" in printed
        assert "Builds" in printed

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
        printed = " ".join(
            str(call.args[0])
            for call in patched_console.print.call_args_list
            if call.args
        )
        assert "None yet" in printed
        assert "flash deploy" in printed


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
            result = runner.invoke(app, ["app", "delete", "demo"])

        assert result.exit_code == 0
        mock_delete.assert_awaited_once_with(app_name="demo")
        printed = " ".join(
            str(call.args[0])
            for call in patched_console.print.call_args_list
            if call.args
        )
        assert "Deleted" in printed
        assert "demo" in printed

    @patch("runpod_flash.cli.commands.apps.FlashApp.delete", new_callable=AsyncMock)
    def test_delete_app_failure_raises_exit(
        self, mock_delete, runner, mock_asyncio_run_coro, patched_console
    ):
        mock_delete.return_value = False

        with patch(
            "runpod_flash.cli.commands.apps.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["app", "delete", "demo"])

        assert result.exit_code == 1
        printed = " ".join(
            str(call.args[0])
            for call in patched_console.print.call_args_list
            if call.args
        )
        assert "Failed to delete" in printed

    def test_delete_app_missing_name_exits_with_error(self, runner):
        result = runner.invoke(app, ["app", "delete"])
        assert result.exit_code == 2
        assert "Missing argument" in result.output
