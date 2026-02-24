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


class TestDisplayPostDeploymentGuidance:
    """Tests for _display_post_deployment_guidance output formatting."""

    def _collect_output(self, patched_console) -> str:
        return " ".join(
            str(call.args[0]) if call.args else ""
            for call in patched_console.print.call_args_list
        )

    def test_lb_endpoints_shown_with_routes(self, patched_console):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={"my_lb": "https://abc.api.runpod.ai"},
            resources={"my_lb": {"is_load_balanced": True}},
            routes={"my_lb": {"POST /transform": "module:func"}},
        )
        output = self._collect_output(patched_console)
        assert "Load-balanced endpoints:" in output
        assert "https://abc.api.runpod.ai" in output
        assert "my_lb" in output
        assert "POST" in output
        assert "/transform" in output

    def test_qb_endpoints_shown(self, patched_console):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={"my_qb": "https://def.api.runpod.ai"},
            resources={"my_qb": {"is_load_balanced": False}},
            routes={},
        )
        output = self._collect_output(patched_console)
        assert "Queue-based endpoints:" in output
        assert "https://def.api.runpod.ai" in output
        assert "my_qb" in output
        assert "/runsync" in output

    def test_routes_grouped_under_lb_endpoint(self, patched_console):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={
                "lb_gpu": "https://gpu.api.runpod.ai",
                "lb_cpu": "https://cpu.api.runpod.ai",
            },
            resources={
                "lb_gpu": {"is_load_balanced": True},
                "lb_cpu": {"is_load_balanced": True},
            },
            routes={
                "lb_gpu": {"POST /transform": "m:f", "POST /validate": "m:g"},
                "lb_cpu": {"GET /health": "m:h"},
            },
        )
        calls = [
            str(call.args[0]) if call.args else ""
            for call in patched_console.print.call_args_list
        ]
        # Find indices for each endpoint URL and verify routes follow their endpoint
        gpu_idx = next(i for i, c in enumerate(calls) if "gpu.api.runpod.ai" in c)
        cpu_idx = next(i for i, c in enumerate(calls) if "cpu.api.runpod.ai" in c)
        # Routes for gpu should appear between gpu and cpu entries
        route_calls_between = calls[gpu_idx + 1 : cpu_idx]
        route_text = " ".join(route_calls_between)
        assert "/transform" in route_text or "/validate" in route_text
        # Routes for cpu should appear after cpu entry
        route_calls_after = calls[cpu_idx + 1 :]
        after_text = " ".join(route_calls_after)
        assert "/health" in after_text

    def test_curl_example_uses_first_lb_post_route(self, patched_console):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        _display_post_deployment_guidance(
            env_name="staging",
            resources_endpoints={"my_lb": "https://abc.api.runpod.ai"},
            resources={"my_lb": {"is_load_balanced": True}},
            routes={"my_lb": {"POST /transform": "m:f", "GET /health": "m:h"}},
        )
        calls = [
            str(call.args[0]) if call.args else ""
            for call in patched_console.print.call_args_list
        ]
        output = " ".join(calls)
        assert "Try it:" in output
        assert "curl -X POST https://abc.api.runpod.ai/transform" in output
        # Curl must appear within LB section (before Useful commands)
        curl_idx = next(i for i, c in enumerate(calls) if "curl -X POST" in c)
        useful_idx = next(i for i, c in enumerate(calls) if "Useful commands:" in c)
        assert curl_idx < useful_idx

    def test_curl_example_falls_back_to_get_when_no_post(self, patched_console):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        _display_post_deployment_guidance(
            env_name="staging",
            resources_endpoints={"my_lb": "https://abc.api.runpod.ai"},
            resources={"my_lb": {"is_load_balanced": True}},
            routes={"my_lb": {"GET /images": "m:f", "GET /images/{file_name}": "m:g"}},
        )
        output = self._collect_output(patched_console)
        assert "Try it:" in output
        assert "curl -X GET https://abc.api.runpod.ai/images" in output

    def test_get_curl_omits_body_and_content_type(self, patched_console):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        _display_post_deployment_guidance(
            env_name="staging",
            resources_endpoints={"my_lb": "https://abc.api.runpod.ai"},
            resources={"my_lb": {"is_load_balanced": True}},
            routes={"my_lb": {"GET /images": "m:f"}},
        )
        output = self._collect_output(patched_console)
        assert "Authorization: Bearer $RUNPOD_API_KEY" in output
        assert "Content-Type" not in output
        assert '"input"' not in output

    def test_post_preferred_over_get_for_curl(self, patched_console):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        _display_post_deployment_guidance(
            env_name="staging",
            resources_endpoints={"my_lb": "https://abc.api.runpod.ai"},
            resources={"my_lb": {"is_load_balanced": True}},
            routes={
                "my_lb": {
                    "GET /health": "m:h",
                    "POST /transform": "m:f",
                }
            },
        )
        output = self._collect_output(patched_console)
        assert "curl -X POST" in output
        assert "curl -X GET" not in output

    def test_qb_curl_uses_runsync(self, patched_console):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={"my_qb": "https://def.api.runpod.ai"},
            resources={"my_qb": {"is_load_balanced": False}},
            routes={},
        )
        output = self._collect_output(patched_console)
        assert "Try it:" in output
        assert "curl -X POST https://def.api.runpod.ai/runsync" in output

    def test_docs_links_shown(self, patched_console):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={"my_lb": "https://abc.api.runpod.ai"},
            resources={"my_lb": {"is_load_balanced": True}},
            routes={"my_lb": {"POST /transform": "m:f"}},
        )
        calls = [
            str(call.args[0]) if call.args else ""
            for call in patched_console.print.call_args_list
        ]
        output = " ".join(calls)
        assert "https://console.runpod.io/serverless" in output
        assert "https://docs.runpod.io/serverless/endpoints/send-requests" in output
        assert "https://docs.runpod.io/serverless/load-balancing/overview" in output
        # Console link must appear after Useful commands
        console_idx = next(i for i, c in enumerate(calls) if "console.runpod.io" in c)
        useful_idx = next(i for i, c in enumerate(calls) if "Useful commands:" in c)
        assert console_idx > useful_idx

    def test_useful_commands_with_env_name(self, patched_console):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        _display_post_deployment_guidance(
            env_name="staging",
            resources_endpoints={},
            resources={},
            routes={},
        )
        output = self._collect_output(patched_console)
        assert "Useful commands:" in output
        assert "flash env get staging" in output
        assert "flash deploy --env staging" in output
        assert "flash env delete staging" in output

    def test_console_link_appears_last(self, patched_console):
        """Console/docs links appear after Useful commands as the final section."""
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={
                "my_lb": "https://abc.api.runpod.ai",
                "my_qb": "https://def.api.runpod.ai",
            },
            resources={
                "my_lb": {"is_load_balanced": True},
                "my_qb": {"is_load_balanced": False},
            },
            routes={"my_lb": {"POST /transform": "m:f"}},
        )
        calls = [
            str(call.args[0]) if call.args else ""
            for call in patched_console.print.call_args_list
        ]
        useful_idx = next(i for i, c in enumerate(calls) if "Useful commands:" in c)
        console_idx = next(i for i, c in enumerate(calls) if "console.runpod.io" in c)
        assert console_idx > useful_idx

    def test_empty_deployment(self, patched_console):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={},
            resources={},
            routes={},
        )
        output = self._collect_output(patched_console)
        assert "Useful commands:" in output
        assert "Load-balanced endpoints:" not in output
        assert "Queue-based endpoints:" not in output
