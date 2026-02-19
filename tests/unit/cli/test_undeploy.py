"""Unit tests for undeploy CLI command."""

import pytest
from unittest.mock import MagicMock, patch
from typer.testing import CliRunner

from runpod_flash.cli.main import app
from runpod_flash.core.resources.serverless import ServerlessResource
from runpod_flash.core.resources.network_volume import NetworkVolume
from runpod_flash.core.resources.resource_manager import ResourceManager


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset singleton state before each test."""
    ResourceManager._resources = {}
    ResourceManager._deployment_locks = {}
    ResourceManager._resources_initialized = False
    ResourceManager._lock_initialized = False
    yield
    ResourceManager._resources = {}
    ResourceManager._deployment_locks = {}
    ResourceManager._resources_initialized = False
    ResourceManager._lock_initialized = False


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture
def sample_resources():
    """Create sample resources for testing."""
    resource1 = ServerlessResource(
        name="test-api-1",
        gpuCount=1,
        workersMax=3,
        workersMin=0,
        flashboot=False,  # Disable to keep original name
    )
    resource1.id = "endpoint-id-1"

    resource2 = ServerlessResource(
        name="test-api-2",
        gpuCount=1,
        workersMax=3,
        workersMin=0,
        flashboot=False,  # Disable to keep original name
    )
    resource2.id = "endpoint-id-2"

    return {
        resource1.resource_id: resource1,
        resource2.resource_id: resource2,
    }


class TestUndeployList:
    """Test undeploy list command."""

    def test_list_no_endpoints(self, runner):
        """Test list command with no endpoints."""
        with patch(
            "runpod_flash.cli.commands.undeploy._get_resource_manager"
        ) as mock_get_rm:
            mock_manager = MagicMock()
            mock_manager.list_all_resources.return_value = {}
            mock_get_rm.return_value = mock_manager

            result = runner.invoke(app, ["undeploy", "list"])

            assert result.exit_code == 0
            assert "No endpoints found" in result.stdout

    def test_list_with_endpoints(self, runner):
        """Test list command with endpoints."""
        from runpod_flash.core.resources.serverless import ServerlessResource

        # Create mock resources that are instances of ServerlessResource
        mock_resource1 = MagicMock(spec=ServerlessResource)
        mock_resource1.name = "test-api-1"
        mock_resource1.id = "endpoint-id-1"
        mock_resource1.is_deployed.return_value = True

        mock_resource2 = MagicMock(spec=ServerlessResource)
        mock_resource2.name = "test-api-2"
        mock_resource2.id = "endpoint-id-2"
        mock_resource2.is_deployed.return_value = True

        mock_resources = {
            "resource-id-1": mock_resource1,
            "resource-id-2": mock_resource2,
        }

        with patch(
            "runpod_flash.cli.commands.undeploy._get_resource_manager"
        ) as mock_get_rm:
            mock_manager = MagicMock()
            mock_manager.list_all_resources.return_value = mock_resources
            mock_get_rm.return_value = mock_manager

            result = runner.invoke(app, ["undeploy", "list"])

            if result.exception:
                raise result.exception

            assert result.exit_code == 0
            assert "test-api-1" in result.stdout
            assert "test-api-2" in result.stdout
            assert "endpoint-id-1" in result.stdout
            assert "endpoint-id-2" in result.stdout

    def test_list_filters_non_serverless_resources(self, runner):
        """Test that list command filters out non-ServerlessResource types."""
        from runpod_flash.cli.commands.undeploy import _get_serverless_resources

        # Create mock ServerlessResource instances
        mock_serverless1 = MagicMock(spec=ServerlessResource)
        mock_serverless1.name = "serverless-api-1"
        mock_serverless1.id = "serverless-id-1"
        mock_serverless1.is_deployed.return_value = True

        mock_serverless2 = MagicMock(spec=ServerlessResource)
        mock_serverless2.name = "serverless-api-2"
        mock_serverless2.id = "serverless-id-2"
        mock_serverless2.is_deployed.return_value = True

        # Create mock NetworkVolume instance (should be filtered out)
        mock_network_volume = MagicMock(spec=NetworkVolume)
        mock_network_volume.name = "storage-volume"
        mock_network_volume.id = "volume-id"
        mock_network_volume.is_deployed.return_value = True

        # Mix of resource types
        mock_resources = {
            "resource-id-1": mock_serverless1,
            "resource-id-2": mock_serverless2,
            "volume-id-1": mock_network_volume,
        }

        # Test the filtering function directly
        filtered = _get_serverless_resources(mock_resources)

        # Should only include ServerlessResource instances
        assert len(filtered) == 2
        assert "resource-id-1" in filtered
        assert "resource-id-2" in filtered
        assert "volume-id-1" not in filtered

        # Verify filtered resources are correct instances
        assert isinstance(filtered["resource-id-1"], MagicMock)
        assert isinstance(filtered["resource-id-2"], MagicMock)


class TestUndeployCommand:
    """Test undeploy command."""

    def test_undeploy_no_args_shows_help(self, runner):
        """Test undeploy without arguments shows help/usage."""
        with patch(
            "runpod_flash.cli.commands.undeploy._get_resource_manager"
        ) as mock_get_rm:
            mock_manager = MagicMock()
            mock_manager.list_all_resources.return_value = {}
            mock_get_rm.return_value = mock_manager

            result = runner.invoke(app, ["undeploy"])

        # With no args, Typer shows help (exit_code 0) due to no_args_is_help
        assert result.exit_code == 0
        assert "Usage" in result.stdout or "undeploy" in result.stdout.lower()

    def test_undeploy_no_args_shows_usage_text(self, runner):
        """Ensure usage help is rendered when no args are provided."""
        with patch(
            "runpod_flash.cli.commands.undeploy._get_resource_manager"
        ) as mock_get_rm:
            mock_resource = MagicMock()
            mock_resource.name = "foo"
            mock_manager = MagicMock()
            mock_manager.list_all_resources.return_value = {"rid": mock_resource}
            mock_get_rm.return_value = mock_manager

            result = runner.invoke(app, ["undeploy"])

        assert "please specify a name" in result.stdout.lower()

    def test_undeploy_nonexistent_name(self, runner, sample_resources):
        """Test undeploy with nonexistent name."""
        with patch(
            "runpod_flash.cli.commands.undeploy._get_resource_manager"
        ) as mock_get_rm:
            mock_manager = MagicMock()
            mock_manager.list_all_resources.return_value = sample_resources
            mock_get_rm.return_value = mock_manager

            result = runner.invoke(app, ["undeploy", "nonexistent"])

            assert result.exit_code == 1
            assert "no endpoint found" in result.stdout.lower()

    def test_undeploy_by_name_cancelled(self, runner, sample_resources):
        """Test undeploy by name cancelled by user."""
        with (
            patch(
                "runpod_flash.cli.commands.undeploy._get_resource_manager"
            ) as mock_get_rm,
            patch("runpod_flash.cli.commands.undeploy.questionary") as mock_questionary,
        ):
            mock_manager = MagicMock()
            mock_manager.list_all_resources.return_value = sample_resources
            mock_get_rm.return_value = mock_manager

            # User cancels confirmation
            mock_confirm = MagicMock()
            mock_confirm.ask.return_value = False
            mock_questionary.confirm.return_value = mock_confirm

            result = runner.invoke(app, ["undeploy", "test-api-1"])

            assert result.exit_code == 0
            assert "cancelled" in result.stdout.lower()

    @patch("runpod_flash.cli.commands.undeploy.asyncio.run")
    def test_undeploy_by_name_success(
        self, mock_asyncio_run, runner, sample_resources, mock_asyncio_run_coro
    ):
        """Test successful undeploy by name."""
        with (
            patch(
                "runpod_flash.cli.commands.undeploy._get_resource_manager"
            ) as mock_get_rm,
            patch("runpod_flash.cli.commands.undeploy.questionary") as mock_questionary,
        ):
            mock_manager = MagicMock()
            mock_manager.list_all_resources.return_value = sample_resources

            # Mock undeploy_resource as async coroutine that returns success
            async def mock_undeploy(resource_id, name):
                return {
                    "success": True,
                    "name": name,
                    "endpoint_id": "endpoint-id-1",
                    "message": f"Successfully undeployed '{name}'",
                }

            mock_manager.undeploy_resource = mock_undeploy
            mock_get_rm.return_value = mock_manager

            # User confirms
            mock_confirm = MagicMock()
            mock_confirm.ask.return_value = True
            mock_questionary.confirm.return_value = mock_confirm

            mock_asyncio_run.side_effect = mock_asyncio_run_coro

            result = runner.invoke(app, ["undeploy", "test-api-1"])

            assert result.exit_code == 0
            assert "Deleted" in result.stdout

    @patch("runpod_flash.cli.commands.undeploy.asyncio.run")
    def test_undeploy_all_flag(
        self, mock_asyncio_run, runner, sample_resources, mock_asyncio_run_coro
    ):
        """Test undeploy --all flag."""
        with (
            patch(
                "runpod_flash.cli.commands.undeploy._get_resource_manager"
            ) as mock_get_rm,
            patch("runpod_flash.cli.commands.undeploy.questionary") as mock_questionary,
        ):
            mock_manager = MagicMock()
            mock_manager.list_all_resources.return_value = sample_resources

            # Mock undeploy_resource as async coroutine that returns success
            async def mock_undeploy(resource_id, name):
                return {
                    "success": True,
                    "name": name,
                    "endpoint_id": "endpoint-id",
                    "message": f"Successfully undeployed '{name}'",
                }

            mock_manager.undeploy_resource = mock_undeploy
            mock_get_rm.return_value = mock_manager

            # User confirms both prompts
            mock_confirm = MagicMock()
            mock_confirm.ask.return_value = True
            mock_text = MagicMock()
            mock_text.ask.return_value = "DELETE ALL"

            mock_questionary.confirm.return_value = mock_confirm
            mock_questionary.text.return_value = mock_text

            mock_asyncio_run.side_effect = mock_asyncio_run_coro

            result = runner.invoke(app, ["undeploy", "--all"])

            assert result.exit_code == 0
            assert "Deleted" in result.stdout

    def test_undeploy_all_wrong_confirmation(self, runner, sample_resources):
        """Test undeploy --all with wrong confirmation text."""
        with (
            patch(
                "runpod_flash.cli.commands.undeploy._get_resource_manager"
            ) as mock_get_rm,
            patch("runpod_flash.cli.commands.undeploy.questionary") as mock_questionary,
        ):
            mock_manager = MagicMock()
            mock_manager.list_all_resources.return_value = sample_resources
            mock_get_rm.return_value = mock_manager

            # User confirms first prompt but wrong text on second
            mock_confirm = MagicMock()
            mock_confirm.ask.return_value = True
            mock_text = MagicMock()
            mock_text.ask.return_value = "wrong text"

            mock_questionary.confirm.return_value = mock_confirm
            mock_questionary.text.return_value = mock_text

            result = runner.invoke(app, ["undeploy", "--all"])

            assert result.exit_code == 1
            assert "Confirmation failed" in result.stdout


class TestResourceStatusHelpers:
    """Test helper functions for resource status."""

    def test_get_resource_status_active(self):
        """Test _get_resource_status for active resource."""
        from runpod_flash.cli.commands.undeploy import _get_resource_status

        mock_resource = MagicMock()
        mock_resource.is_deployed.return_value = True

        color, text = _get_resource_status(mock_resource)

        assert color == "green"
        assert text == "active"

    def test_get_resource_status_inactive(self):
        """Test _get_resource_status for inactive resource."""
        from runpod_flash.cli.commands.undeploy import _get_resource_status

        mock_resource = MagicMock()
        mock_resource.is_deployed.return_value = False

        color, text = _get_resource_status(mock_resource)

        assert color == "red"
        assert text == "inactive"

    def test_get_resource_status_exception(self):
        """Test _get_resource_status when exception occurs."""
        from runpod_flash.cli.commands.undeploy import _get_resource_status

        mock_resource = MagicMock()
        mock_resource.is_deployed.side_effect = Exception("API Error")

        color, text = _get_resource_status(mock_resource)

        assert color == "yellow"
        assert text == "unknown"

    def test_get_resource_type(self, sample_resources):
        """Test _get_resource_type returns formatted type."""
        from runpod_flash.cli.commands.undeploy import _get_resource_type

        resource = list(sample_resources.values())[0]
        resource_type = _get_resource_type(resource)

        assert "Serverless" in resource_type
