"""Tests for resource management commands."""

from unittest.mock import MagicMock, patch

import pytest

from runpod_flash.cli.commands.resource import generate_resource_table, report_command


@pytest.fixture
def mock_resource_manager():
    """Provide mock resource manager."""
    manager = MagicMock()
    manager._resources = {}
    return manager


class TestGenerateResourceTableEmpty:
    """Tests for generate_resource_table with empty resources."""

    def test_empty_resources_returns_renderable(self, mock_resource_manager):
        """Test that empty resources returns a renderable."""
        result = generate_resource_table(mock_resource_manager)
        assert result is not None

    def test_empty_resources_no_error(self, mock_resource_manager):
        """Test that empty resources doesn't raise error."""
        try:
            generate_resource_table(mock_resource_manager)
        except Exception as e:
            pytest.fail(f"generate_resource_table raised {type(e).__name__}: {e}")


class TestGenerateResourceTableSingleResource:
    """Tests for generate_resource_table with single resource."""

    def test_single_active_resource_no_error(self, mock_resource_manager):
        """Test with single active resource doesn't error."""
        resource = MagicMock()
        resource.is_deployed.return_value = True
        resource.__class__.__name__ = "ServerlessEndpoint"
        resource.url = "https://example.com/endpoint-123"

        mock_resource_manager._resources = {"endpoint-001": resource}

        try:
            result = generate_resource_table(mock_resource_manager)
            assert result is not None
        except Exception as e:
            pytest.fail(f"generate_resource_table raised {type(e).__name__}: {e}")

    def test_single_inactive_resource_no_error(self, mock_resource_manager):
        """Test with single inactive resource doesn't error."""
        resource = MagicMock()
        resource.is_deployed.return_value = False
        resource.__class__.__name__ = "ServerlessEndpoint"
        resource.url = "https://example.com/endpoint-456"

        mock_resource_manager._resources = {"endpoint-002": resource}

        try:
            result = generate_resource_table(mock_resource_manager)
            assert result is not None
        except Exception as e:
            pytest.fail(f"generate_resource_table raised {type(e).__name__}: {e}")

    def test_resource_is_deployed_exception_handled(self, mock_resource_manager):
        """Test handles is_deployed exception."""
        resource = MagicMock()
        resource.is_deployed.side_effect = Exception("Connection failed")
        resource.__class__.__name__ = "ServerlessEndpoint"
        resource.url = "https://example.com/endpoint-789"

        mock_resource_manager._resources = {"endpoint-003": resource}

        try:
            result = generate_resource_table(mock_resource_manager)
            assert result is not None
        except Exception as e:
            pytest.fail(f"generate_resource_table raised {type(e).__name__}: {e}")

    def test_resource_without_url_attribute_handled(self, mock_resource_manager):
        """Test resource without url attribute is handled."""
        resource = MagicMock(spec=["is_deployed", "__class__"])
        resource.is_deployed.return_value = True
        resource.__class__.__name__ = "LoadBalancer"

        mock_resource_manager._resources = {"lb-001": resource}

        try:
            result = generate_resource_table(mock_resource_manager)
            assert result is not None
        except Exception as e:
            pytest.fail(f"generate_resource_table raised {type(e).__name__}: {e}")

    def test_resource_with_empty_url(self, mock_resource_manager):
        """Test resource with empty string URL."""
        resource = MagicMock()
        resource.is_deployed.return_value = True
        resource.__class__.__name__ = "ServerlessEndpoint"
        resource.url = ""

        mock_resource_manager._resources = {"endpoint-empty-url": resource}

        try:
            result = generate_resource_table(mock_resource_manager)
            assert result is not None
        except Exception as e:
            pytest.fail(f"generate_resource_table raised {type(e).__name__}: {e}")


class TestGenerateResourceTableMultipleResources:
    """Tests for generate_resource_table with multiple resources."""

    def test_multiple_resources_mixed_status_no_error(self, mock_resource_manager):
        """Test with mixed statuses doesn't error."""
        active_resource = MagicMock()
        active_resource.is_deployed.return_value = True
        active_resource.__class__.__name__ = "ServerlessEndpoint"
        active_resource.url = "https://api.example.com/active"

        inactive_resource = MagicMock()
        inactive_resource.is_deployed.return_value = False
        inactive_resource.__class__.__name__ = "ServerlessEndpoint"
        inactive_resource.url = "https://api.example.com/inactive"

        mock_resource_manager._resources = {
            "endpoint-001": active_resource,
            "endpoint-002": inactive_resource,
        }

        try:
            result = generate_resource_table(mock_resource_manager)
            assert result is not None
        except Exception as e:
            pytest.fail(f"generate_resource_table raised {type(e).__name__}: {e}")

    def test_multiple_resources_all_active_no_error(self, mock_resource_manager):
        """Test with all active resources doesn't error."""
        resources = {}
        for i in range(3):
            resource = MagicMock()
            resource.is_deployed.return_value = True
            resource.__class__.__name__ = "ServerlessEndpoint"
            resource.url = f"https://api.example.com/endpoint-{i}"
            resources[f"endpoint-{i}"] = resource

        mock_resource_manager._resources = resources

        try:
            result = generate_resource_table(mock_resource_manager)
            assert result is not None
        except Exception as e:
            pytest.fail(f"generate_resource_table raised {type(e).__name__}: {e}")

    def test_long_resource_id_handling(self, mock_resource_manager):
        """Test that long resource IDs are handled (truncated)."""
        resource = MagicMock()
        resource.is_deployed.return_value = True
        resource.__class__.__name__ = "ServerlessEndpoint"
        resource.url = "https://example.com"

        long_id = "a" * 30

        mock_resource_manager._resources = {long_id: resource}

        try:
            result = generate_resource_table(mock_resource_manager)
            assert result is not None
        except Exception as e:
            pytest.fail(f"generate_resource_table raised {type(e).__name__}: {e}")

    def test_short_resource_id_no_error(self, mock_resource_manager):
        """Test short resource IDs work."""
        resource = MagicMock()
        resource.is_deployed.return_value = True
        resource.__class__.__name__ = "ServerlessEndpoint"
        resource.url = "https://example.com"

        mock_resource_manager._resources = {"endpoint-123": resource}

        try:
            result = generate_resource_table(mock_resource_manager)
            assert result is not None
        except Exception as e:
            pytest.fail(f"generate_resource_table raised {type(e).__name__}: {e}")


class TestGenerateResourceTableSummary:
    """Tests for generate_resource_table summary calculation."""

    def test_summary_all_active_no_error(self, mock_resource_manager):
        """Test summary with all active resources."""
        resources = {}
        for i in range(5):
            resource = MagicMock()
            resource.is_deployed.return_value = True
            resource.__class__.__name__ = "ServerlessEndpoint"
            resource.url = f"https://example.com/{i}"
            resources[f"endpoint-{i}"] = resource

        mock_resource_manager._resources = resources

        try:
            result = generate_resource_table(mock_resource_manager)
            assert result is not None
        except Exception as e:
            pytest.fail(f"generate_resource_table raised {type(e).__name__}: {e}")

    def test_summary_mixed_status_no_error(self, mock_resource_manager):
        """Test summary with mixed status resources."""
        resources = {}

        for i in range(2):
            resource = MagicMock()
            resource.is_deployed.return_value = True
            resource.__class__.__name__ = "ServerlessEndpoint"
            resource.url = f"https://example.com/active-{i}"
            resources[f"endpoint-{i}"] = resource

        resource = MagicMock()
        resource.is_deployed.return_value = False
        resource.__class__.__name__ = "ServerlessEndpoint"
        resource.url = "https://example.com/inactive"
        resources["endpoint-2"] = resource

        for i in range(3, 5):
            resource = MagicMock()
            resource.is_deployed.side_effect = Exception("Error")
            resource.__class__.__name__ = "ServerlessEndpoint"
            resource.url = f"https://example.com/unknown-{i}"
            resources[f"endpoint-{i}"] = resource

        mock_resource_manager._resources = resources

        try:
            result = generate_resource_table(mock_resource_manager)
            assert result is not None
        except Exception as e:
            pytest.fail(f"generate_resource_table raised {type(e).__name__}: {e}")


class TestGenerateResourceTableResourceTypes:
    """Tests for different resource types."""

    def test_various_resource_types_no_error(self, mock_resource_manager):
        """Test displaying various resource types."""
        resource_types = [
            "ServerlessEndpoint",
            "LoadBalancer",
            "NetworkVolume",
            "CustomResource",
        ]

        resources = {}
        for i, res_type in enumerate(resource_types):
            resource = MagicMock()
            resource.is_deployed.return_value = True
            resource.__class__.__name__ = res_type
            resource.url = f"https://example.com/{res_type.lower()}-{i}"
            resources[f"res-{i}"] = resource

        mock_resource_manager._resources = resources

        try:
            result = generate_resource_table(mock_resource_manager)
            assert result is not None
        except Exception as e:
            pytest.fail(f"generate_resource_table raised {type(e).__name__}: {e}")


@patch("runpod_flash.cli.commands.resource.ResourceManager")
@patch("runpod_flash.cli.commands.resource.console")
def test_report_command_static_mode(mock_console, mock_resource_manager_class):
    """Test report_command in static (non-live) mode."""
    mock_manager_instance = MagicMock()
    mock_manager_instance._resources = {}
    mock_resource_manager_class.return_value = mock_manager_instance

    report_command(live=False)

    mock_resource_manager_class.assert_called_once()
    mock_console.print.assert_called_once()


@patch("runpod_flash.cli.commands.resource.time")
@patch("runpod_flash.cli.commands.resource.Live")
@patch("runpod_flash.cli.commands.resource.ResourceManager")
@patch("runpod_flash.cli.commands.resource.console")
def test_report_command_live_mode(
    mock_console, mock_resource_manager_class, mock_live_class, mock_time
):
    """Test report_command in live mode with keyboard interrupt."""
    mock_manager_instance = MagicMock()
    mock_manager_instance._resources = {}
    mock_resource_manager_class.return_value = mock_manager_instance

    mock_live_instance = MagicMock()
    mock_live_class.return_value.__enter__ = MagicMock(return_value=mock_live_instance)
    mock_live_class.return_value.__exit__ = MagicMock(return_value=False)

    call_count = [0]

    def sleep_side_effect(duration):
        call_count[0] += 1
        if call_count[0] > 0:
            raise KeyboardInterrupt()

    mock_time.sleep.side_effect = sleep_side_effect

    report_command(live=True, refresh=2)

    mock_live_class.assert_called_once()
    assert any("stopped" in str(c).lower() for c in mock_console.print.call_args_list)


@patch("runpod_flash.cli.commands.resource.ResourceManager")
@patch("runpod_flash.cli.commands.resource.console")
def test_report_command_with_custom_refresh(mock_console, mock_resource_manager_class):
    """Test report_command accepts custom refresh interval."""
    mock_manager_instance = MagicMock()
    mock_manager_instance._resources = {}
    mock_resource_manager_class.return_value = mock_manager_instance

    report_command(live=False, refresh=5)

    mock_resource_manager_class.assert_called_once()
    mock_console.print.assert_called_once()


@patch("runpod_flash.cli.commands.resource.ResourceManager")
@patch("runpod_flash.cli.commands.resource.console")
def test_report_command_instantiates_resource_manager(
    mock_console, mock_resource_manager_class
):
    """Test that report_command instantiates ResourceManager."""
    mock_manager_instance = MagicMock()
    mock_manager_instance._resources = {}
    mock_resource_manager_class.return_value = mock_manager_instance

    report_command(live=False)

    mock_resource_manager_class.assert_called_once_with()


@patch("runpod_flash.cli.commands.resource._render_resource_report")
@patch("runpod_flash.cli.commands.resource.ResourceManager")
@patch("runpod_flash.cli.commands.resource.console")
def test_report_command_calls_render_report(
    mock_console, mock_resource_manager_class, mock_render
):
    """Test that report_command calls _render_resource_report."""
    mock_manager_instance = MagicMock()
    mock_resource_manager_class.return_value = mock_manager_instance
    mock_render.return_value = MagicMock()

    report_command(live=False)

    mock_render.assert_called_once_with(mock_manager_instance)
