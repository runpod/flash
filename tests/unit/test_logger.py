"""Unit tests for logger module."""

import logging
from io import StringIO
from logging.handlers import TimedRotatingFileHandler
from unittest.mock import patch


from runpod_flash.logger import (
    setup_logging,
    _add_file_handler_if_local,
    LoggingConfig,
    get_logging_config,
    set_logging_config,
)


def cleanup_handlers(logger: logging.Logger) -> None:
    """Close and clear all handlers to prevent file descriptor leaks."""
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_stream_handler_created(self, tmp_path, monkeypatch):
        """Verify stdout logging handler is created."""
        # Change to temp directory to isolate test
        monkeypatch.chdir(tmp_path)

        # Clear any existing handlers
        root_logger = logging.getLogger()
        cleanup_handlers(root_logger)

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
        cleanup_handlers(root_logger)

    def test_file_handler_in_local_mode(self, tmp_path, monkeypatch):
        """Verify file handler is added in local development mode."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Clear existing handlers
        root_logger = logging.getLogger()
        cleanup_handlers(root_logger)

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
        cleanup_handlers(root_logger)

    def test_no_file_handler_in_deployed_mode(self, tmp_path, monkeypatch):
        """Verify file handler is NOT added in deployed container mode."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Clear existing handlers
        root_logger = logging.getLogger()
        cleanup_handlers(root_logger)

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
        cleanup_handlers(root_logger)

    def test_graceful_degradation_on_error(self, tmp_path, monkeypatch):
        """Verify CLI continues with stdout-only if file logging fails."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Clear existing handlers
        root_logger = logging.getLogger()
        cleanup_handlers(root_logger)

        # Capture stdout
        stream = StringIO()

        # Mock is_local_development and Path.mkdir to simulate failure
        with patch(
            "runpod_flash.runtime.context.is_local_development", return_value=True
        ):
            with patch(
                "runpod_flash.logger.Path.mkdir",
                side_effect=Exception("Simulated error"),
            ):
                setup_logging(level=logging.WARNING, stream=stream)

        # Verify only stream handler exists (graceful fallback)
        assert len(root_logger.handlers) == 1
        stream_handlers = [
            h for h in root_logger.handlers if isinstance(h, logging.StreamHandler)
        ]
        assert len(stream_handlers) == 1

        # Verify warning was logged
        output = stream.getvalue()
        assert "Could not set up file logging" in output
        assert "Simulated error" in output

        # Cleanup
        cleanup_handlers(root_logger)

    def test_log_file_creation(self, tmp_path, monkeypatch):
        """Verify log messages are written to file."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Clear existing handlers
        root_logger = logging.getLogger()
        cleanup_handlers(root_logger)

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
        cleanup_handlers(root_logger)

    def test_handler_not_duplicated(self, tmp_path, monkeypatch):
        """Verify calling setup_logging() twice doesn't duplicate handlers."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Clear existing handlers
        root_logger = logging.getLogger()
        cleanup_handlers(root_logger)

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
        cleanup_handlers(root_logger)

    def test_log_level_override_via_env(self, tmp_path, monkeypatch):
        """Verify LOG_LEVEL environment variable overrides level."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Clear existing handlers
        root_logger = logging.getLogger()
        cleanup_handlers(root_logger)

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
        cleanup_handlers(root_logger)
        monkeypatch.delenv("LOG_LEVEL")

    def test_debug_format_includes_details(self, tmp_path, monkeypatch):
        """Verify DEBUG level uses detailed format."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Clear existing handlers
        root_logger = logging.getLogger()
        cleanup_handlers(root_logger)

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
        cleanup_handlers(root_logger)


class TestAddFileHandlerIfLocal:
    """Tests for _add_file_handler_if_local helper function."""

    def test_skips_if_deployed(self, tmp_path, monkeypatch):
        """Verify function returns early in deployed mode."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        root_logger = logging.getLogger()
        cleanup_handlers(root_logger)

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
        cleanup_handlers(root_logger)

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

        cleanup_handlers(root_logger)

    def test_file_handler_format_matches_console(self, tmp_path, monkeypatch):
        """Verify file handler uses same format as console."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        root_logger = logging.getLogger()
        cleanup_handlers(root_logger)

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

        # Verify the formatter produces output matching the expected format
        file_handler = file_handlers[0]
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        formatted_output = file_handler.format(record)
        assert formatted_output == "INFO - Test message"

        cleanup_handlers(root_logger)

    def test_error_handling_prints_warning(self, tmp_path, monkeypatch, capsys):
        """Verify errors are caught and warning is logged."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        root_logger = logging.getLogger()
        cleanup_handlers(root_logger)

        # Add a stream handler so warnings can be captured
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.WARNING)

        # Mock local mode and force an error
        with patch(
            "runpod_flash.runtime.context.is_local_development", return_value=True
        ):
            with patch(
                "runpod_flash.logger.Path.mkdir", side_effect=RuntimeError("Test error")
            ):
                _add_file_handler_if_local(root_logger, logging.INFO, "%(message)s")

        # Verify warning was logged
        output = stream.getvalue()
        assert "Could not set up file logging" in output
        assert "Test error" in output

        # Verify no file handler was added (only the stream handler we added)
        assert len(root_logger.handlers) == 1

        cleanup_handlers(root_logger)


class TestLoggingConfig:
    """Tests for LoggingConfig class."""

    def test_default_values(self):
        """Verify default configuration values."""
        config = LoggingConfig()
        assert config.enabled is True
        assert config.retention_days == 30
        assert config.log_dir == ".flash/logs"

    def test_from_env_enabled_true(self, monkeypatch):
        """Verify FLASH_FILE_LOGGING_ENABLED=true enables file logging."""
        monkeypatch.setenv("FLASH_FILE_LOGGING_ENABLED", "true")
        config = LoggingConfig.from_env()
        assert config.enabled is True

    def test_from_env_enabled_false(self, monkeypatch):
        """Verify FLASH_FILE_LOGGING_ENABLED=false disables file logging."""
        monkeypatch.setenv("FLASH_FILE_LOGGING_ENABLED", "false")
        config = LoggingConfig.from_env()
        assert config.enabled is False

    def test_from_env_retention_days(self, monkeypatch):
        """Verify FLASH_LOG_RETENTION_DAYS is applied."""
        monkeypatch.setenv("FLASH_LOG_RETENTION_DAYS", "7")
        config = LoggingConfig.from_env()
        assert config.retention_days == 7

    def test_from_env_invalid_retention_days(self, monkeypatch, capsys):
        """Verify invalid retention days falls back to default with warning."""
        monkeypatch.setenv("FLASH_LOG_RETENTION_DAYS", "0")

        # Capture logging warning
        logger = logging.getLogger()
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.WARNING)
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)

        try:
            config = LoggingConfig.from_env()
            assert config.retention_days == 30

            # Verify warning was logged
            output = stream.getvalue()
            assert "Invalid FLASH_LOG_RETENTION_DAYS=0" in output
        finally:
            logger.removeHandler(handler)
            handler.close()

    def test_from_env_custom_log_dir(self, monkeypatch):
        """Verify FLASH_LOG_DIR custom directory is used."""
        custom_dir = "/tmp/my-logs"
        monkeypatch.setenv("FLASH_LOG_DIR", custom_dir)
        config = LoggingConfig.from_env()
        assert config.log_dir == custom_dir

    def test_get_logging_config_lazy_loads(self, monkeypatch):
        """Verify get_logging_config() lazy-loads configuration."""
        # Reset global config
        set_logging_config(None)

        monkeypatch.setenv("FLASH_LOG_RETENTION_DAYS", "15")
        config = get_logging_config()
        assert config.retention_days == 15

        # Calling again should return same instance
        config2 = get_logging_config()
        assert config is config2

    def test_set_logging_config_for_testing(self):
        """Verify set_logging_config() allows test isolation."""
        test_config = LoggingConfig(
            enabled=False, retention_days=5, log_dir="/test/path"
        )
        set_logging_config(test_config)

        config = get_logging_config()
        assert config.enabled is False
        assert config.retention_days == 5
        assert config.log_dir == "/test/path"

        # Reset for other tests
        set_logging_config(None)

    def test_file_logging_disabled_via_config(self, tmp_path, monkeypatch):
        """Verify file handler is NOT added when config.enabled=False."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Set config to disabled
        set_logging_config(LoggingConfig(enabled=False))

        # Clear existing handlers
        root_logger = logging.getLogger()
        cleanup_handlers(root_logger)

        # Mock local mode
        with patch(
            "runpod_flash.runtime.context.is_local_development", return_value=True
        ):
            _add_file_handler_if_local(root_logger, logging.INFO, "%(message)s")

        # Verify no file handler was added
        file_handlers = [
            h for h in root_logger.handlers if isinstance(h, TimedRotatingFileHandler)
        ]
        assert len(file_handlers) == 0

        # Verify no log directory created
        flash_dir = tmp_path / ".flash"
        assert not flash_dir.exists()

        # Cleanup
        cleanup_handlers(root_logger)
        set_logging_config(None)

    def test_custom_retention_applied_to_handler(self, tmp_path, monkeypatch):
        """Verify custom retention days is applied to TimedRotatingFileHandler."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Set custom retention
        set_logging_config(LoggingConfig(retention_days=7))

        # Clear existing handlers
        root_logger = logging.getLogger()
        cleanup_handlers(root_logger)

        # Mock local mode
        with patch(
            "runpod_flash.runtime.context.is_local_development", return_value=True
        ):
            _add_file_handler_if_local(root_logger, logging.INFO, "%(message)s")

        # Verify file handler has correct backupCount
        file_handlers = [
            h for h in root_logger.handlers if isinstance(h, TimedRotatingFileHandler)
        ]
        assert len(file_handlers) == 1
        assert file_handlers[0].backupCount == 7

        # Cleanup
        cleanup_handlers(root_logger)
        set_logging_config(None)

    def test_custom_log_dir_created(self, tmp_path, monkeypatch):
        """Verify custom log directory is created and used."""
        # Change to temp directory
        monkeypatch.chdir(tmp_path)

        # Set custom log directory
        custom_log_dir = tmp_path / "custom" / "logs"
        set_logging_config(LoggingConfig(log_dir=str(custom_log_dir)))

        # Clear existing handlers
        root_logger = logging.getLogger()
        cleanup_handlers(root_logger)

        # Mock local mode
        with patch(
            "runpod_flash.runtime.context.is_local_development", return_value=True
        ):
            _add_file_handler_if_local(root_logger, logging.INFO, "%(message)s")

        # Verify custom directory was created
        assert custom_log_dir.exists()
        assert custom_log_dir.is_dir()

        # Verify log file is in custom directory
        log_file = custom_log_dir / "activity.log"
        assert log_file.exists()

        # Cleanup
        cleanup_handlers(root_logger)
        set_logging_config(None)
