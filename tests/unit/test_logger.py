"""Unit tests for logger module."""

import logging
from io import StringIO
from logging.handlers import TimedRotatingFileHandler
from unittest.mock import patch


from runpod_flash.logger import setup_logging, _add_file_handler_if_local


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_stream_handler_created(self, tmp_path, monkeypatch):
        """Verify stdout logging handler is created."""
        # Change to temp directory to isolate test
        monkeypatch.chdir(tmp_path)

        # Clear any existing handlers
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        # Capture stdout
        stream = StringIO()
        setup_logging(level=logging.INFO, stream=stream)

        # Verify handler was added
        assert len(root_logger.handlers) >= 1
        stream_handlers = [
            h for h in root_logger.handlers if isinstance(h, logging.StreamHandler)
        ]
        assert len(stream_handlers) >= 1

        # Verify logging works
        logger = logging.getLogger("test")
        logger.info("Test message")
        output = stream.getvalue()
        assert "Test message" in output

        # Cleanup
        root_logger.handlers.clear()

    def test_file_handler_in_local_mode(self, tmp_path, monkeypatch):
        """Verify file handler is added in local development mode."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Clear existing handlers
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        # Mock is_local_development to return True
        with patch(
            "runpod_flash.runtime.context.is_local_development", return_value=True
        ):
            setup_logging(level=logging.INFO)

        # Verify both stream and file handlers exist
        assert len(root_logger.handlers) == 2
        stream_handlers = [
            h
            for h in root_logger.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, TimedRotatingFileHandler)
        ]
        file_handlers = [
            h for h in root_logger.handlers if isinstance(h, TimedRotatingFileHandler)
        ]

        assert len(stream_handlers) == 1
        assert len(file_handlers) == 1

        # Verify file handler configuration
        file_handler = file_handlers[0]
        assert (
            file_handler.when == "MIDNIGHT"
        )  # TimedRotatingFileHandler stores in uppercase
        assert file_handler.interval == 86400  # Daily interval converted to seconds
        assert file_handler.backupCount == 30
        assert file_handler.suffix == "%Y-%m-%d"

        # Verify log directory was created
        flash_dir = tmp_path / ".flash"
        logs_dir = flash_dir / "logs"
        assert logs_dir.exists()
        assert logs_dir.is_dir()

        # Cleanup
        root_logger.handlers.clear()

    def test_no_file_handler_in_deployed_mode(self, tmp_path, monkeypatch):
        """Verify file handler is NOT added in deployed container mode."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Clear existing handlers
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        # Mock is_local_development to return False (deployed mode)
        with patch(
            "runpod_flash.runtime.context.is_local_development", return_value=False
        ):
            setup_logging(level=logging.INFO)

        # Verify only stream handler exists
        assert len(root_logger.handlers) == 1
        stream_handlers = [
            h for h in root_logger.handlers if isinstance(h, logging.StreamHandler)
        ]
        file_handlers = [
            h for h in root_logger.handlers if isinstance(h, TimedRotatingFileHandler)
        ]

        assert len(stream_handlers) == 1
        assert len(file_handlers) == 0

        # Verify no .flash directory created
        flash_dir = tmp_path / ".flash"
        assert not flash_dir.exists()

        # Cleanup
        root_logger.handlers.clear()

    def test_graceful_degradation_on_error(self, tmp_path, monkeypatch, capsys):
        """Verify CLI continues with stdout-only if file logging fails."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Clear existing handlers
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        # Mock is_local_development and get_paths to simulate failure
        with patch(
            "runpod_flash.runtime.context.is_local_development", return_value=True
        ):
            with patch(
                "runpod_flash.config.get_paths",
                side_effect=Exception("Simulated error"),
            ):
                setup_logging(level=logging.INFO)

        # Verify only stream handler exists (graceful fallback)
        assert len(root_logger.handlers) == 1
        stream_handlers = [
            h for h in root_logger.handlers if isinstance(h, logging.StreamHandler)
        ]
        assert len(stream_handlers) == 1

        # Verify warning was printed to stderr
        captured = capsys.readouterr()
        assert "Warning: Could not set up file logging" in captured.err
        assert "Simulated error" in captured.err

        # Cleanup
        root_logger.handlers.clear()

    def test_log_file_creation(self, tmp_path, monkeypatch):
        """Verify log messages are written to file."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Clear existing handlers
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        # Mock is_local_development
        with patch(
            "runpod_flash.runtime.context.is_local_development", return_value=True
        ):
            setup_logging(level=logging.INFO)

        # Write a test log message
        logger = logging.getLogger("test")
        logger.info("Test file logging")

        # Force flush handlers
        for handler in root_logger.handlers:
            handler.flush()

        # Verify log file exists and contains message
        log_file = tmp_path / ".flash" / "logs" / "activity.log"
        assert log_file.exists()

        log_contents = log_file.read_text()
        assert "Test file logging" in log_contents

        # Cleanup
        root_logger.handlers.clear()

    def test_handler_not_duplicated(self, tmp_path, monkeypatch):
        """Verify calling setup_logging() twice doesn't duplicate handlers."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Clear existing handlers
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        # Mock is_local_development
        with patch(
            "runpod_flash.runtime.context.is_local_development", return_value=True
        ):
            # First call
            setup_logging(level=logging.INFO)
            handler_count_1 = len(root_logger.handlers)

            # Second call - should not add more handlers
            setup_logging(level=logging.INFO)
            handler_count_2 = len(root_logger.handlers)

        # Verify handler count didn't increase
        assert handler_count_1 == handler_count_2 == 2

        # Cleanup
        root_logger.handlers.clear()

    def test_log_level_override_via_env(self, tmp_path, monkeypatch):
        """Verify LOG_LEVEL environment variable overrides level."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Clear existing handlers
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        # Set environment variable
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        # Mock is_local_development
        with patch(
            "runpod_flash.runtime.context.is_local_development", return_value=False
        ):
            setup_logging(level=logging.INFO)

        # Verify level was overridden to DEBUG
        assert root_logger.level == logging.DEBUG

        # Cleanup
        root_logger.handlers.clear()
        monkeypatch.delenv("LOG_LEVEL")

    def test_debug_format_includes_details(self, tmp_path, monkeypatch):
        """Verify DEBUG level uses detailed format."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Clear existing handlers
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        stream = StringIO()

        # Mock is_local_development
        with patch(
            "runpod_flash.runtime.context.is_local_development", return_value=False
        ):
            setup_logging(level=logging.DEBUG, stream=stream)

        # Log a debug message
        logger = logging.getLogger("test")
        logger.debug("Debug message")

        output = stream.getvalue()

        # Verify detailed format includes filename and line number
        assert "Debug message" in output
        assert "test_logger.py" in output  # filename
        assert "test" in output  # logger name

        # Cleanup
        root_logger.handlers.clear()


class TestAddFileHandlerIfLocal:
    """Tests for _add_file_handler_if_local helper function."""

    def test_skips_if_deployed(self, tmp_path, monkeypatch):
        """Verify function returns early in deployed mode."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        # Mock deployed mode
        with patch(
            "runpod_flash.runtime.context.is_local_development", return_value=False
        ):
            _add_file_handler_if_local(root_logger, logging.INFO, "%(message)s")

        # Verify no handlers were added
        assert len(root_logger.handlers) == 0

        # Verify no .flash directory created
        flash_dir = tmp_path / ".flash"
        assert not flash_dir.exists()

    def test_creates_log_directory(self, tmp_path, monkeypatch):
        """Verify function creates .flash/logs directory."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        # Mock local mode
        with patch(
            "runpod_flash.runtime.context.is_local_development", return_value=True
        ):
            _add_file_handler_if_local(root_logger, logging.INFO, "%(message)s")

        # Verify directories were created
        flash_dir = tmp_path / ".flash"
        logs_dir = flash_dir / "logs"
        assert flash_dir.exists()
        assert logs_dir.exists()

        root_logger.handlers.clear()

    def test_file_handler_format_matches_console(self, tmp_path, monkeypatch):
        """Verify file handler uses same format as console."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        test_format = "%(levelname)s - %(message)s"

        # Mock local mode
        with patch(
            "runpod_flash.runtime.context.is_local_development", return_value=True
        ):
            _add_file_handler_if_local(root_logger, logging.INFO, test_format)

        # Get the file handler
        file_handlers = [
            h for h in root_logger.handlers if isinstance(h, TimedRotatingFileHandler)
        ]
        assert len(file_handlers) == 1

        file_handler = file_handlers[0]
        assert file_handler.formatter._fmt == test_format

        root_logger.handlers.clear()

    def test_error_handling_prints_warning(self, tmp_path, monkeypatch, capsys):
        """Verify errors are caught and warning is printed."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        # Mock local mode and force an error
        with patch(
            "runpod_flash.runtime.context.is_local_development", return_value=True
        ):
            with patch(
                "runpod_flash.config.get_paths", side_effect=RuntimeError("Test error")
            ):
                _add_file_handler_if_local(root_logger, logging.INFO, "%(message)s")

        # Verify warning was printed to stderr
        captured = capsys.readouterr()
        assert "Warning: Could not set up file logging" in captured.err
        assert "Test error" in captured.err

        # Verify no handlers were added
        assert len(root_logger.handlers) == 0
