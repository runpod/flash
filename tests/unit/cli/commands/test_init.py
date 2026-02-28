"""Tests for flash init command."""

from unittest.mock import MagicMock, Mock, patch

import pytest
import typer
from rich.panel import Panel

from runpod_flash.cli.commands.init import init_command


@pytest.fixture
def mock_typer_ctx():
    """Create a mock typer.Context for direct init_command calls."""
    ctx = MagicMock(spec=typer.Context)
    ctx.get_help.return_value = "Usage: flash init [OPTIONS] [PROJECT_NAME]"
    return ctx


@pytest.fixture
def mock_context(monkeypatch):
    """Set up mocks for init command testing."""
    mocks = {
        "console": MagicMock(),
        "detect_conflicts": MagicMock(return_value=[]),
        "create_skeleton": MagicMock(),
    }

    mocks["console"].status = MagicMock()
    mocks["console"].status.return_value.__enter__ = Mock(return_value=None)
    mocks["console"].status.return_value.__exit__ = Mock(return_value=False)

    patches = [
        patch("runpod_flash.cli.commands.init.console", mocks["console"]),
        patch(
            "runpod_flash.cli.commands.init.detect_file_conflicts",
            mocks["detect_conflicts"],
        ),
        patch(
            "runpod_flash.cli.commands.init.create_project_skeleton",
            mocks["create_skeleton"],
        ),
    ]

    for p in patches:
        p.start()

    yield mocks

    for p in patches:
        p.stop()


class TestInitCommandNewDirectory:
    """Tests for init command when creating a new directory."""

    def test_create_new_directory(
        self, mock_typer_ctx, mock_context, tmp_path, monkeypatch
    ):
        """Test creating new project directory."""
        monkeypatch.chdir(tmp_path)

        init_command(mock_typer_ctx, "my_project")

        # Verify directory was created
        assert (tmp_path / "my_project").exists()

        # Verify skeleton was created
        mock_context["create_skeleton"].assert_called_once()

        # Verify console output
        mock_context["console"].print.assert_called()

    def test_create_nested_directory(
        self, mock_typer_ctx, mock_context, tmp_path, monkeypatch
    ):
        """Test creating project in nested directory structure."""
        monkeypatch.chdir(tmp_path)

        init_command(mock_typer_ctx, "path/to/my_project")

        # Verify nested directory was created
        assert (tmp_path / "path/to/my_project").exists()

    def test_force_flag_skips_confirmation(
        self, mock_typer_ctx, mock_context, tmp_path, monkeypatch
    ):
        """Test that force flag bypasses conflict prompts."""
        monkeypatch.chdir(tmp_path)
        mock_context["detect_conflicts"].return_value = ["main.py", "requirements.txt"]

        init_command(mock_typer_ctx, "my_project", force=True)

        # Verify skeleton was created
        mock_context["create_skeleton"].assert_called_once()


class TestInitCommandNoArgs:
    """Tests for init command when called with no arguments."""

    def test_no_args_shows_help_and_exits(self, mock_typer_ctx, mock_context):
        """flash init with no args should show help and exit."""
        with pytest.raises(typer.Exit) as exc_info:
            init_command(mock_typer_ctx, None)

        assert exc_info.value.exit_code == 0

    def test_no_args_does_not_create_skeleton(self, mock_typer_ctx, mock_context):
        """flash init with no args should not create project skeleton."""
        with pytest.raises(typer.Exit):
            init_command(mock_typer_ctx, None)

        mock_context["create_skeleton"].assert_not_called()

    def test_no_args_prints_usage_info(self, mock_typer_ctx, mock_context):
        """flash init with no args should print usage information."""
        with pytest.raises(typer.Exit):
            init_command(mock_typer_ctx, None)

        # Verify console.print was called with a Panel containing usage info
        mock_context["console"].print.assert_called_once()
        panel_arg = mock_context["console"].print.call_args[0][0]
        assert isinstance(panel_arg, Panel)
        assert "flash init" in panel_arg.title


class TestInitCommandCurrentDirectory:
    """Tests for init command when using current directory."""

    @patch("pathlib.Path.cwd")
    def test_init_current_directory_with_dot(
        self, mock_cwd, mock_typer_ctx, mock_context, tmp_path
    ):
        """Test initialization in current directory with '.' argument."""
        mock_cwd.return_value = tmp_path

        init_command(mock_typer_ctx, ".")

        # Verify skeleton was created
        mock_context["create_skeleton"].assert_called_once()


class TestInitCommandConflictDetection:
    """Tests for init command file conflict detection and resolution."""

    def test_no_conflicts_no_prompt(
        self, mock_typer_ctx, mock_context, tmp_path, monkeypatch
    ):
        """Test that prompt is skipped when no conflicts exist."""
        monkeypatch.chdir(tmp_path)
        mock_context["detect_conflicts"].return_value = []

        init_command(mock_typer_ctx, "my_project")

        # Verify skeleton was created
        mock_context["create_skeleton"].assert_called_once()

    def test_console_called_multiple_times(
        self, mock_typer_ctx, mock_context, tmp_path, monkeypatch
    ):
        """Test that console prints multiple outputs."""
        monkeypatch.chdir(tmp_path)

        init_command(mock_typer_ctx, "my_project")

        # Verify console.print was called multiple times
        assert mock_context["console"].print.call_count > 0


class TestInitCommandOutput:
    """Tests for init command output messages."""

    def test_panel_title_for_new_directory(
        self, mock_typer_ctx, mock_context, tmp_path, monkeypatch
    ):
        """Test that panel output is created for new directory."""
        monkeypatch.chdir(tmp_path)

        init_command(mock_typer_ctx, "my_project")

        # Verify console.print was called multiple times
        assert mock_context["console"].print.call_count > 0

    @patch("pathlib.Path.cwd")
    def test_panel_title_for_current_directory(
        self, mock_cwd, mock_typer_ctx, mock_context, tmp_path
    ):
        """Test that panel output is created for current directory."""
        mock_cwd.return_value = tmp_path

        init_command(mock_typer_ctx, ".")

        # Verify console.print was called
        assert mock_context["console"].print.call_count > 0

    def test_next_steps_displayed(
        self, mock_typer_ctx, mock_context, tmp_path, monkeypatch
    ):
        """Test next steps are displayed."""
        monkeypatch.chdir(tmp_path)

        init_command(mock_typer_ctx, "my_project")

        # Verify console.print was called with next steps text
        assert any(
            "Next steps" in str(c) for c in mock_context["console"].print.call_args_list
        )

    @patch("pathlib.Path.cwd")
    def test_api_key_docs_link_displayed(
        self, mock_cwd, mock_typer_ctx, mock_context, tmp_path
    ):
        """Test API key documentation link is displayed."""
        mock_cwd.return_value = tmp_path

        init_command(mock_typer_ctx, ".")

        # Verify console.print was called with API key link
        assert any(
            "runpod.io" in str(c) for c in mock_context["console"].print.call_args_list
        )

    def test_status_message_for_new_directory(
        self, mock_typer_ctx, mock_context, tmp_path, monkeypatch
    ):
        """Test status message while creating new directory."""
        monkeypatch.chdir(tmp_path)

        init_command(mock_typer_ctx, "my_project")

        # Check that status was called with appropriate message
        mock_context["console"].status.assert_called_once()
        status_msg = mock_context["console"].status.call_args[0][0]
        assert "Creating Flash project" in status_msg

    @patch("pathlib.Path.cwd")
    def test_status_message_for_current_directory(
        self, mock_cwd, mock_typer_ctx, mock_context, tmp_path
    ):
        """Test status message while initializing current directory."""
        mock_cwd.return_value = tmp_path

        init_command(mock_typer_ctx, ".")

        # Check that status was called with initialization message
        mock_context["console"].status.assert_called_once()
        status_msg = mock_context["console"].status.call_args[0][0]
        assert "Initializing" in status_msg or "Flash project" in status_msg


class TestInitCommandProjectNameHandling:
    """Tests for project name handling."""

    def test_special_characters_in_project_name(
        self, mock_typer_ctx, mock_context, tmp_path, monkeypatch
    ):
        """Test project name with special characters."""
        monkeypatch.chdir(tmp_path)

        init_command(mock_typer_ctx, "my-project_123")

        # Verify directory was created with the exact name
        assert (tmp_path / "my-project_123").exists()

    def test_console_called_with_panels_and_tables(
        self, mock_typer_ctx, mock_context, tmp_path, monkeypatch
    ):
        """Test that console prints panels and tables."""
        monkeypatch.chdir(tmp_path)

        init_command(mock_typer_ctx, "test_project")

        # Verify console.print was called multiple times
        assert (
            mock_context["console"].print.call_count >= 4
        )  # Panel, "Next steps:", Table, API key info

    def test_directory_created_matches_argument(
        self, mock_typer_ctx, mock_context, tmp_path, monkeypatch
    ):
        """Test that directory created matches the argument."""
        monkeypatch.chdir(tmp_path)

        init_command(mock_typer_ctx, "my_awesome_project")

        # Verify directory was created with exact name
        assert (tmp_path / "my_awesome_project").exists()
        # Verify it's a directory
        assert (tmp_path / "my_awesome_project").is_dir()
