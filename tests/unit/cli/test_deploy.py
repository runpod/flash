"""Unit tests for flash deploy CLI command."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from runpod_flash.cli.main import app


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def patched_console():
    with patch("runpod_flash.cli.commands.deploy.console") as mock_console:
        status_cm = MagicMock()
        status_cm.__enter__.return_value = None
        status_cm.__exit__.return_value = None
        mock_console.status.return_value = status_cm
        yield mock_console


def _make_flash_app(**kwargs):
    """Create a MagicMock flash app with common async methods."""
    flash_app = MagicMock()
    flash_app.upload_build = AsyncMock(return_value={"id": "build-123"})
    flash_app.get_environment_by_name = AsyncMock()
    for key, value in kwargs.items():
        setattr(flash_app, key, value)
    return flash_app


class TestDeployCommand:
    @patch(
        "runpod_flash.cli.commands.deploy.deploy_from_uploaded_build",
        new_callable=AsyncMock,
    )
    @patch(
        "runpod_flash.cli.commands.deploy.validate_local_manifest",
        return_value={"resources": {}},
    )
    @patch(
        "runpod_flash.cli.commands.deploy.FlashApp.from_name", new_callable=AsyncMock
    )
    @patch("runpod_flash.cli.commands.deploy.run_build")
    @patch("runpod_flash.cli.commands.deploy.discover_flash_project")
    def test_deploy_single_env_auto_selects(
        self,
        mock_discover,
        mock_build,
        mock_from_name,
        mock_validate,
        mock_deploy,
        runner,
        mock_asyncio_run_coro,
        patched_console,
    ):
        mock_discover.return_value = (Path("/tmp/project"), "my-app")
        mock_build.return_value = Path("/tmp/project/.flash/artifact.tar.gz")
        mock_deploy.return_value = {"success": True}

        flash_app = _make_flash_app(
            list_environments=AsyncMock(
                return_value=[{"name": "production", "id": "env-1"}]
            ),
        )
        mock_from_name.return_value = flash_app

        with (
            patch(
                "runpod_flash.cli.commands.deploy.asyncio.run",
                side_effect=mock_asyncio_run_coro,
            ),
            patch("runpod_flash.cli.commands.deploy.shutil"),
        ):
            result = runner.invoke(app, ["deploy"])

        assert result.exit_code == 0
        mock_build.assert_called_once()
        mock_deploy.assert_awaited_once()

    @patch(
        "runpod_flash.cli.commands.deploy.deploy_from_uploaded_build",
        new_callable=AsyncMock,
    )
    @patch(
        "runpod_flash.cli.commands.deploy.validate_local_manifest",
        return_value={"resources": {}},
    )
    @patch(
        "runpod_flash.cli.commands.deploy.FlashApp.from_name", new_callable=AsyncMock
    )
    @patch("runpod_flash.cli.commands.deploy.run_build")
    @patch("runpod_flash.cli.commands.deploy.discover_flash_project")
    def test_deploy_with_explicit_env(
        self,
        mock_discover,
        mock_build,
        mock_from_name,
        mock_validate,
        mock_deploy,
        runner,
        mock_asyncio_run_coro,
        patched_console,
    ):
        mock_discover.return_value = (Path("/tmp/project"), "my-app")
        mock_build.return_value = Path("/tmp/project/.flash/artifact.tar.gz")
        mock_deploy.return_value = {"success": True}

        flash_app = _make_flash_app(
            list_environments=AsyncMock(
                return_value=[
                    {"name": "staging", "id": "env-1"},
                    {"name": "production", "id": "env-2"},
                ]
            ),
        )
        mock_from_name.return_value = flash_app

        with (
            patch(
                "runpod_flash.cli.commands.deploy.asyncio.run",
                side_effect=mock_asyncio_run_coro,
            ),
            patch("runpod_flash.cli.commands.deploy.shutil"),
        ):
            result = runner.invoke(app, ["deploy", "--env", "staging"])

        assert result.exit_code == 0
        mock_deploy.assert_awaited_once()
        call_args = mock_deploy.call_args
        assert call_args[0][2] == "staging"  # env_name

    @patch(
        "runpod_flash.cli.commands.deploy.FlashApp.from_name", new_callable=AsyncMock
    )
    @patch("runpod_flash.cli.commands.deploy.run_build")
    @patch("runpod_flash.cli.commands.deploy.discover_flash_project")
    def test_deploy_multiple_envs_no_flag_errors(
        self,
        mock_discover,
        mock_build,
        mock_from_name,
        runner,
        mock_asyncio_run_coro,
        patched_console,
    ):
        mock_discover.return_value = (Path("/tmp/project"), "my-app")
        mock_build.return_value = Path("/tmp/project/.flash/artifact.tar.gz")

        flash_app = _make_flash_app(
            list_environments=AsyncMock(
                return_value=[
                    {"name": "staging", "id": "env-1"},
                    {"name": "production", "id": "env-2"},
                ]
            ),
        )
        mock_from_name.return_value = flash_app

        with patch(
            "runpod_flash.cli.commands.deploy.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["deploy"])

        assert result.exit_code == 1

    @patch(
        "runpod_flash.cli.commands.deploy.FlashApp.create_environment_and_app",
        new_callable=AsyncMock,
    )
    @patch(
        "runpod_flash.cli.commands.deploy.FlashApp.from_name", new_callable=AsyncMock
    )
    @patch(
        "runpod_flash.cli.commands.deploy.deploy_from_uploaded_build",
        new_callable=AsyncMock,
    )
    @patch(
        "runpod_flash.cli.commands.deploy.validate_local_manifest",
        return_value={"resources": {}},
    )
    @patch("runpod_flash.cli.commands.deploy.run_build")
    @patch("runpod_flash.cli.commands.deploy.discover_flash_project")
    def test_deploy_no_app_creates_app_and_env(
        self,
        mock_discover,
        mock_build,
        mock_validate,
        mock_deploy,
        mock_from_name,
        mock_create,
        runner,
        mock_asyncio_run_coro,
        patched_console,
    ):
        mock_discover.return_value = (Path("/tmp/project"), "my-app")
        mock_build.return_value = Path("/tmp/project/.flash/artifact.tar.gz")
        mock_deploy.return_value = {"success": True}
        mock_from_name.side_effect = Exception("GraphQL errors: app not found")

        created_app = _make_flash_app()
        mock_create.return_value = (created_app, {"id": "env-1", "name": "production"})

        with (
            patch(
                "runpod_flash.cli.commands.deploy.asyncio.run",
                side_effect=mock_asyncio_run_coro,
            ),
            patch("runpod_flash.cli.commands.deploy.shutil"),
        ):
            result = runner.invoke(app, ["deploy"])

        assert result.exit_code == 0
        mock_create.assert_awaited_once_with("my-app", "production")

    @patch(
        "runpod_flash.cli.commands.deploy.FlashApp.from_name", new_callable=AsyncMock
    )
    @patch("runpod_flash.cli.commands.deploy.run_build")
    @patch("runpod_flash.cli.commands.deploy.discover_flash_project")
    def test_deploy_non_app_error_propagates(
        self,
        mock_discover,
        mock_build,
        mock_from_name,
        runner,
        mock_asyncio_run_coro,
        patched_console,
    ):
        """Non 'app not found' errors should propagate, not trigger auto-create."""
        mock_discover.return_value = (Path("/tmp/project"), "my-app")
        mock_build.return_value = Path("/tmp/project/.flash/artifact.tar.gz")
        mock_from_name.side_effect = Exception("GraphQL errors: authentication failed")

        with patch(
            "runpod_flash.cli.commands.deploy.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            result = runner.invoke(app, ["deploy"])

        assert result.exit_code == 1

    @patch(
        "runpod_flash.cli.commands.deploy.deploy_from_uploaded_build",
        new_callable=AsyncMock,
    )
    @patch(
        "runpod_flash.cli.commands.deploy.validate_local_manifest",
        return_value={"resources": {}},
    )
    @patch(
        "runpod_flash.cli.commands.deploy.FlashApp.from_name", new_callable=AsyncMock
    )
    @patch("runpod_flash.cli.commands.deploy.run_build")
    @patch("runpod_flash.cli.commands.deploy.discover_flash_project")
    def test_deploy_auto_creates_nonexistent_env(
        self,
        mock_discover,
        mock_build,
        mock_from_name,
        mock_validate,
        mock_deploy,
        runner,
        mock_asyncio_run_coro,
        patched_console,
    ):
        mock_discover.return_value = (Path("/tmp/project"), "my-app")
        mock_build.return_value = Path("/tmp/project/.flash/artifact.tar.gz")
        mock_deploy.return_value = {"success": True}

        flash_app = _make_flash_app(
            list_environments=AsyncMock(
                return_value=[{"name": "production", "id": "env-1"}]
            ),
            create_environment=AsyncMock(),
        )
        mock_from_name.return_value = flash_app

        with (
            patch(
                "runpod_flash.cli.commands.deploy.asyncio.run",
                side_effect=mock_asyncio_run_coro,
            ),
            patch("runpod_flash.cli.commands.deploy.shutil"),
        ):
            result = runner.invoke(app, ["deploy", "--env", "staging"])

        assert result.exit_code == 0
        flash_app.create_environment.assert_awaited_once_with("staging")

    @patch(
        "runpod_flash.cli.commands.deploy.deploy_from_uploaded_build",
        new_callable=AsyncMock,
    )
    @patch(
        "runpod_flash.cli.commands.deploy.validate_local_manifest",
        return_value={"resources": {}},
    )
    @patch(
        "runpod_flash.cli.commands.deploy.FlashApp.from_name", new_callable=AsyncMock
    )
    @patch("runpod_flash.cli.commands.deploy.run_build")
    @patch("runpod_flash.cli.commands.deploy.discover_flash_project")
    def test_deploy_zero_envs_creates_production(
        self,
        mock_discover,
        mock_build,
        mock_from_name,
        mock_validate,
        mock_deploy,
        runner,
        mock_asyncio_run_coro,
        patched_console,
    ):
        mock_discover.return_value = (Path("/tmp/project"), "my-app")
        mock_build.return_value = Path("/tmp/project/.flash/artifact.tar.gz")
        mock_deploy.return_value = {"success": True}

        flash_app = _make_flash_app(
            list_environments=AsyncMock(return_value=[]),
            create_environment=AsyncMock(),
        )
        mock_from_name.return_value = flash_app

        with (
            patch(
                "runpod_flash.cli.commands.deploy.asyncio.run",
                side_effect=mock_asyncio_run_coro,
            ),
            patch("runpod_flash.cli.commands.deploy.shutil"),
        ):
            result = runner.invoke(app, ["deploy"])

        assert result.exit_code == 0
        flash_app.create_environment.assert_awaited_once_with("production")

    @patch(
        "runpod_flash.cli.commands.deploy.deploy_from_uploaded_build",
        new_callable=AsyncMock,
    )
    @patch(
        "runpod_flash.cli.commands.deploy.validate_local_manifest",
        return_value={"resources": {}},
    )
    @patch(
        "runpod_flash.cli.commands.deploy.FlashApp.from_name", new_callable=AsyncMock
    )
    @patch("runpod_flash.cli.commands.deploy.run_build")
    @patch("runpod_flash.cli.commands.deploy.discover_flash_project")
    def test_deploy_shows_completion_panel(
        self,
        mock_discover,
        mock_build,
        mock_from_name,
        mock_validate,
        mock_deploy,
        runner,
        mock_asyncio_run_coro,
        patched_console,
    ):
        mock_discover.return_value = (Path("/tmp/project"), "my-app")
        mock_build.return_value = Path("/tmp/project/.flash/artifact.tar.gz")
        mock_deploy.return_value = {"success": True}

        flash_app = _make_flash_app(
            list_environments=AsyncMock(
                return_value=[{"name": "production", "id": "env-1"}]
            ),
        )
        mock_from_name.return_value = flash_app

        with (
            patch(
                "runpod_flash.cli.commands.deploy.asyncio.run",
                side_effect=mock_asyncio_run_coro,
            ),
            patch("runpod_flash.cli.commands.deploy.shutil"),
        ):
            result = runner.invoke(app, ["deploy"])

        assert result.exit_code == 0
        # Check that post-deployment guidance was displayed
        printed_output = [
            str(call.args[0]) if call.args else ""
            for call in patched_console.print.call_args_list
        ]
        guidance_text = " ".join(printed_output)
        assert "Useful commands:" in guidance_text

    @patch(
        "runpod_flash.cli.commands.deploy.deploy_from_uploaded_build",
        new_callable=AsyncMock,
    )
    @patch(
        "runpod_flash.cli.commands.deploy.validate_local_manifest",
        return_value={"resources": {}},
    )
    @patch(
        "runpod_flash.cli.commands.deploy.FlashApp.from_name", new_callable=AsyncMock
    )
    @patch("runpod_flash.cli.commands.deploy.run_build")
    @patch("runpod_flash.cli.commands.deploy.discover_flash_project")
    def test_deploy_uses_app_flag(
        self,
        mock_discover,
        mock_build,
        mock_from_name,
        mock_validate,
        mock_deploy,
        runner,
        mock_asyncio_run_coro,
        patched_console,
    ):
        mock_discover.return_value = (Path("/tmp/project"), "default-app")
        mock_build.return_value = Path("/tmp/project/.flash/artifact.tar.gz")
        mock_deploy.return_value = {"success": True}

        flash_app = _make_flash_app(
            list_environments=AsyncMock(
                return_value=[{"name": "production", "id": "env-1"}]
            ),
        )
        mock_from_name.return_value = flash_app

        with (
            patch(
                "runpod_flash.cli.commands.deploy.asyncio.run",
                side_effect=mock_asyncio_run_coro,
            ),
            patch("runpod_flash.cli.commands.deploy.shutil"),
        ):
            result = runner.invoke(app, ["deploy", "--app", "custom-app"])

        assert result.exit_code == 0
        mock_from_name.assert_awaited_once_with("custom-app")
