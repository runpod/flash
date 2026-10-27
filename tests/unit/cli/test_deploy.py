"""Unit tests for flash deploy CLI command."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from runpod_flash.cli.main import app
from runpod_flash.core.exceptions import RunpodAPIKeyError


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
        return_value={"resources": {"my_resource": {}}},
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
        _archive = MagicMock(spec=Path)
        _archive.stat.return_value.st_size = 1024 * 1024
        mock_build.return_value = _archive
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
        return_value={"resources": {"my_resource": {}}},
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
        _archive = MagicMock(spec=Path)
        _archive.stat.return_value.st_size = 1024 * 1024
        mock_build.return_value = _archive
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
        _archive = MagicMock(spec=Path)
        _archive.stat.return_value.st_size = 1024 * 1024
        mock_build.return_value = _archive

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
        return_value={"resources": {"my_resource": {}}},
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
        _archive = MagicMock(spec=Path)
        _archive.stat.return_value.st_size = 1024 * 1024
        mock_build.return_value = _archive
        mock_deploy.return_value = {"success": True}
        from runpod_flash.core.resources.app import FlashAppNotFoundError

        mock_from_name.side_effect = FlashAppNotFoundError("my-app")

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
        _archive = MagicMock(spec=Path)
        _archive.stat.return_value.st_size = 1024 * 1024
        mock_build.return_value = _archive
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
        return_value={"resources": {"my_resource": {}}},
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
        _archive = MagicMock(spec=Path)
        _archive.stat.return_value.st_size = 1024 * 1024
        mock_build.return_value = _archive
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
        return_value={"resources": {"my_resource": {}}},
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
        _archive = MagicMock(spec=Path)
        _archive.stat.return_value.st_size = 1024 * 1024
        mock_build.return_value = _archive
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
        return_value={"resources": {"my_resource": {}}},
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
        _archive = MagicMock(spec=Path)
        _archive.stat.return_value.st_size = 1024 * 1024
        mock_build.return_value = _archive
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
        assert "Deployed" in guidance_text or "deployed" in guidance_text.lower()

    @patch(
        "runpod_flash.cli.commands.deploy.deploy_from_uploaded_build",
        new_callable=AsyncMock,
    )
    @patch(
        "runpod_flash.cli.commands.deploy.validate_local_manifest",
        return_value={"resources": {"my_resource": {}}},
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
        _archive = MagicMock(spec=Path)
        _archive.stat.return_value.st_size = 1024 * 1024
        mock_build.return_value = _archive
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


class TestDeployCommandEmptyResources:
    """flash deploy with an empty manifest resources map is not a deployment."""

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
    def test_deploy_empty_resources_reports_no_deployment(
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
        """A project with neither decorated resources nor client-mode
        endpoints produces an empty resources map; deploy must report that
        honestly instead of claiming success."""
        mock_discover.return_value = (Path("/tmp/project"), "my-app")
        _archive = MagicMock(spec=Path)
        _archive.stat.return_value.st_size = 1024 * 1024
        mock_build.return_value = _archive

        with (
            patch(
                "runpod_flash.cli.commands.deploy.asyncio.run",
                side_effect=mock_asyncio_run_coro,
            ),
            patch("runpod_flash.cli.commands.deploy.shutil"),
        ):
            result = runner.invoke(app, ["deploy"])

        assert result.exit_code == 0
        printed_output = " ".join(
            str(call.args[0]) if call.args else ""
            for call in patched_console.print.call_args_list
        )
        assert "No deployable resources found" in printed_output
        assert "deployed to" not in printed_output
        # Nothing should be uploaded or provisioned
        mock_from_name.assert_not_awaited()
        mock_deploy.assert_not_awaited()


class TestDeployCommandClientModeEndpoints:
    """Projects whose only endpoints are client-mode Endpoint(image=...)
    declarations ARE deployable: the build registers them in the manifest
    and the normal provisioning path creates the endpoints."""

    _CLIENT_MANIFEST = {
        "resources": {
            "vllm-server": {
                "resource_type": "LiveServerless",
                "client_mode": True,
                "imageName": "runpod/vllm-openai:stable",
                "functions": [],
                "is_load_balanced": False,
                "makes_remote_calls": False,
            }
        }
    }

    @patch(
        "runpod_flash.cli.commands.deploy.deploy_from_uploaded_build",
        new_callable=AsyncMock,
    )
    @patch(
        "runpod_flash.cli.commands.deploy.validate_local_manifest",
        return_value=_CLIENT_MANIFEST,
    )
    @patch(
        "runpod_flash.cli.commands.deploy.FlashApp.from_name", new_callable=AsyncMock
    )
    @patch("runpod_flash.cli.commands.deploy.run_build")
    @patch("runpod_flash.cli.commands.deploy.discover_flash_project")
    def test_deploy_provisions_client_mode_endpoints(
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
        _archive = MagicMock(spec=Path)
        _archive.stat.return_value.st_size = 1024 * 1024
        mock_build.return_value = _archive
        mock_deploy.return_value = {
            "success": True,
            "resources_endpoints": {"vllm-server": "https://vllm-xyz.api.runpod.ai"},
            "local_manifest": self._CLIENT_MANIFEST,
        }

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
        # the client-mode manifest flows into the provisioning path untouched
        mock_deploy.assert_awaited_once()
        passed_manifest = mock_deploy.call_args[0][3]
        assert passed_manifest["resources"]["vllm-server"]["client_mode"] is True

        printed_output = " ".join(
            str(call.args[0]) if call.args else ""
            for call in patched_console.print.call_args_list
        )
        assert "deployed to" in printed_output
        assert "No deployable resources found" not in printed_output
        # post-deploy guidance lists the provisioned endpoint
        assert "vllm-server" in printed_output
        assert "https://vllm-xyz.api.runpod.ai/runsync" in printed_output


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
        assert "my_lb" in output
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
        assert "my_qb" in output
        assert "https://def.api.runpod.ai" in output
        assert "my_qb" in output
        assert "/runsync" in output

    def test_lists_endpoints_that_receive_api_key(self, patched_console):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={
                "caller": "https://a.api.runpod.ai",
                "isolated": "https://b.api.runpod.ai",
            },
            resources={
                "caller": {"makes_remote_calls": True},
                "isolated": {"makes_remote_calls": False},
            },
            routes={},
        )
        output = self._collect_output(patched_console)
        assert (
            "RUNPOD_API_KEY set by Flash on endpoints that call other endpoints: caller"
            in (output)
        )
        assert "caller, isolated" not in output

    def test_api_key_line_skips_user_managed_key(self, patched_console):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={"caller": "https://a.api.runpod.ai"},
            resources={
                "caller": {
                    "makes_remote_calls": True,
                    "env": {"RUNPOD_API_KEY": ""},
                }
            },
            routes={},
        )
        assert "RUNPOD_API_KEY added" not in self._collect_output(patched_console)

    def test_no_api_key_line_when_no_endpoint_receives_it(self, patched_console):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={"isolated": "https://b.api.runpod.ai"},
            resources={"isolated": {"makes_remote_calls": False}},
            routes={},
        )
        assert "RUNPOD_API_KEY added" not in self._collect_output(patched_console)

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
        assert "curl" in output
        assert "curl -X POST https://abc.api.runpod.ai/transform" in output

    def test_curl_example_falls_back_to_get_when_no_post(self, patched_console):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        _display_post_deployment_guidance(
            env_name="staging",
            resources_endpoints={"my_lb": "https://abc.api.runpod.ai"},
            resources={"my_lb": {"is_load_balanced": True}},
            routes={"my_lb": {"GET /images": "m:f", "GET /images/{file_name}": "m:g"}},
        )
        output = self._collect_output(patched_console)
        assert "curl" in output
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
        assert "curl" in output
        assert "curl -X POST https://def.api.runpod.ai/runsync" in output

    def test_qb_curl_sends_required_params(self, patched_console, tmp_path):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        src = tmp_path / "gpu_demo.py"
        src.write_text(
            "async def gpu_matrix_multiply(size, *, scale, seed=0, verbose=False):\n"
            "    return size\n"
        )
        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={"my_qb": "https://api.runpod.ai/v2/abc123"},
            resources={
                "my_qb": {
                    "file_path": str(src),
                    "functions": [{"name": "gpu_matrix_multiply", "is_class": False}],
                }
            },
            routes={},
        )
        output = self._collect_output(patched_console)
        assert '{"input": {"size": "<size>", "scale": "<scale>"}}' in output
        assert '{"input": {}}' not in output

    def test_qb_curl_marks_empty_input_for_no_arg_function(
        self, patched_console, tmp_path
    ):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        src = tmp_path / "jobs.py"
        src.write_text("def ping(verbose=False):\n    return 'pong'\n")
        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={"my_qb": "https://api.runpod.ai/v2/abc123"},
            resources={
                "my_qb": {
                    "file_path": str(src),
                    "functions": [{"name": "ping", "is_class": False}],
                }
            },
            routes={},
        )
        output = self._collect_output(patched_console)
        assert '{"input": {"__empty": true}}' in output

    def test_qb_curl_never_sends_empty_input(self, patched_console):
        """runpod drops jobs with an empty input dict, so the example must not."""
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={"my_qb": "https://api.runpod.ai/v2/abc123"},
            resources={
                "my_qb": {
                    "file_path": "missing.py",
                    "functions": [{"name": "f", "is_class": False}],
                }
            },
            routes={},
        )
        output = self._collect_output(patched_console)
        assert '{"input": {"__empty": true}}' in output
        assert '{"input": {}}' not in output

    def _class_resource(self, src, methods):
        return {
            "my_qb": {
                "file_path": str(src),
                "functions": [
                    {"name": "Model", "is_class": True, "class_methods": methods}
                ],
            }
        }

    def test_qb_curl_for_single_method_class_omits_method(
        self, patched_console, tmp_path
    ):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        src = tmp_path / "model.py"
        src.write_text(
            "class Model:\n    def predict(self, image, k=1):\n        ...\n"
        )
        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={"my_qb": "https://api.runpod.ai/v2/abc123"},
            resources=self._class_resource(src, ["predict"]),
            routes={},
        )
        output = self._collect_output(patched_console)
        assert '{"input": {"image": "<image>"}}' in output

    def test_qb_curl_for_multi_method_class_names_real_method(
        self, patched_console, tmp_path
    ):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        src = tmp_path / "model.py"
        src.write_text(
            "class Model:\n"
            "    def predict(self, image):\n        ...\n"
            "    def embed(self, text):\n        ...\n"
        )
        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={"my_qb": "https://api.runpod.ai/v2/abc123"},
            resources=self._class_resource(src, ["predict", "embed"]),
            routes={},
        )
        output = self._collect_output(patched_console)
        assert '{"input": {"method": "predict", "image": "<image>"}}' in output

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            (
                "class Model:\n    def predict(this, image):\n        ...\n",
                '{"input": {"image": "<image>"}}',
            ),
            (
                "class Model:\n    @staticmethod\n"
                "    def predict(image):\n        ...\n",
                '{"input": {"image": "<image>"}}',
            ),
        ],
    )
    def test_qb_curl_drops_only_the_method_receiver(
        self, patched_console, tmp_path, source, expected
    ):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        src = tmp_path / "model.py"
        src.write_text(source)
        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={"my_qb": "https://api.runpod.ai/v2/abc123"},
            resources=self._class_resource(src, ["predict"]),
            routes={},
        )
        assert expected in self._collect_output(patched_console)

    def test_qb_curl_uses_last_definition_of_redefined_class(
        self, patched_console, tmp_path
    ):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        src = tmp_path / "model.py"
        src.write_text(
            "class Model:\n    def predict(self, text):\n        ...\n\n"
            "class Model:\n    def predict(self, image):\n        ...\n"
        )
        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={"my_qb": "https://api.runpod.ai/v2/abc123"},
            resources=self._class_resource(src, ["predict"]),
            routes={},
        )
        output = self._collect_output(patched_console)
        assert '{"input": {"image": "<image>"}}' in output

    def test_qb_curl_reads_top_level_function_not_nested_namesake(
        self, patched_console, tmp_path
    ):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        src = tmp_path / "jobs.py"
        src.write_text(
            "class Helper:\n    def predict(self, image):\n        ...\n\n"
            "def predict(prompt):\n    ...\n"
        )
        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={"my_qb": "https://api.runpod.ai/v2/abc123"},
            resources={
                "my_qb": {
                    "file_path": str(src),
                    "functions": [{"name": "predict", "is_class": False}],
                }
            },
            routes={},
        )
        output = self._collect_output(patched_console)
        assert '{"input": {"prompt": "<prompt>"}}' in output

    def test_qb_curl_keeps_self_param_on_plain_function(
        self, patched_console, tmp_path
    ):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        src = tmp_path / "jobs.py"
        src.write_text("def run(self):\n    ...\n")
        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={"my_qb": "https://api.runpod.ai/v2/abc123"},
            resources={
                "my_qb": {
                    "file_path": str(src),
                    "functions": [{"name": "run", "is_class": False}],
                }
            },
            routes={},
        )
        output = self._collect_output(patched_console)
        assert '{"input": {"self": "<self>"}}' in output

    def test_qb_curl_uses_last_definition_of_redefined_function(
        self, patched_console, tmp_path
    ):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        src = tmp_path / "jobs.py"
        src.write_text(
            "def predict(image):\n    ...\n\ndef predict(image, scale):\n    ...\n"
        )
        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={"my_qb": "https://api.runpod.ai/v2/abc123"},
            resources={
                "my_qb": {
                    "file_path": str(src),
                    "functions": [{"name": "predict", "is_class": False}],
                }
            },
            routes={},
        )
        output = self._collect_output(patched_console)
        assert '{"input": {"image": "<image>", "scale": "<scale>"}}' in output

    def test_lb_endpoint_shows_routes(self, patched_console):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={"my_lb": "https://abc.api.runpod.ai"},
            resources={"my_lb": {"is_load_balanced": True}},
            routes={"my_lb": {"POST /transform": "m:f"}},
        )
        output = self._collect_output(patched_console)
        assert "my_lb" in output
        assert "/transform" in output

    def test_qb_endpoint_shows_url(self, patched_console):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={"my_qb": "https://api.runpod.ai/v2/abc123"},
            resources={"my_qb": {}},
            routes={},
        )
        output = self._collect_output(patched_console)
        assert "my_qb" in output
        assert "https://api.runpod.ai/v2/abc123" in output

    def test_empty_deployment(self, patched_console):
        from runpod_flash.cli.commands.deploy import _display_post_deployment_guidance

        _display_post_deployment_guidance(
            env_name="production",
            resources_endpoints={},
            resources={},
            routes={},
        )
        output = self._collect_output(patched_console)
        assert "my_lb" not in output
        assert "my_qb" not in output


class TestDeployCommandApiKeyError:
    """Test deploy_command handles RunpodAPIKeyError cleanly."""

    @patch("runpod_flash.cli.commands.deploy.run_build")
    @patch("runpod_flash.cli.commands.deploy.discover_flash_project")
    def test_deploy_api_key_error_exits_cleanly(
        self,
        mock_discover,
        mock_build,
        runner,
        mock_asyncio_run_coro,
    ):
        """deploy_command should print clean error and exit 1 on RunpodAPIKeyError."""
        mock_discover.return_value = (Path("/tmp/project"), "my-app")
        _archive = MagicMock(spec=Path)
        _archive.stat.return_value.st_size = 1024 * 1024
        mock_build.return_value = _archive

        with patch(
            "runpod_flash.cli.commands.deploy.asyncio.run",
            side_effect=mock_asyncio_run_coro,
        ):
            with patch(
                "runpod_flash.cli.commands.deploy._resolve_and_deploy",
                new_callable=AsyncMock,
                side_effect=RunpodAPIKeyError(),
            ):
                result = runner.invoke(app, ["deploy"])

        assert result.exit_code == 1
        assert "No RunPod API key found" in result.output
        # Should NOT show "Deploy failed:" prefix (that's the generic handler)
        assert "Deploy failed:" not in result.output
