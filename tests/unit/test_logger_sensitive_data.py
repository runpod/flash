"""Unit tests for SensitiveDataFilter in logger module."""

import logging
from io import StringIO
from unittest.mock import patch

from runpod_flash.logger import SensitiveDataFilter, setup_logging


def cleanup_handlers(logger: logging.Logger) -> None:
    """Close and clear all handlers to prevent file descriptor leaks."""
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)


class TestSensitiveDataFilter:
    """Tests for SensitiveDataFilter class."""

    def test_redact_api_keys_in_string(self):
        """Verify API keys in string messages are redacted."""
        filter_instance = SensitiveDataFilter()

        # Create a log record with API key
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="API Key: sk-1234567890abcdef1234567890abcdef",
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)
        assert "sk-1234567890abcdef1234567890abcdef" not in record.msg
        assert "***REDACTED***" in record.msg

    def test_redact_passwords_in_dict(self):
        """Verify password keys in dict-like structures are redacted."""
        filter_instance = SensitiveDataFilter()

        # Use 8-char password for full redaction (not partial)
        config = {"username": "admin", "password": "secr1234"}

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="Config: %s",
            args=(config,),
            exc_info=None,
        )

        filter_instance.filter(record)
        # When a dict is passed as args to LogRecord with %s formatting,
        # it becomes args directly (not a tuple), so access it directly
        sanitized_config = record.args
        assert sanitized_config["password"] == "***REDACTED***"
        assert sanitized_config["username"] == "admin"

    def test_redact_authorization_headers(self):
        """Verify Bearer tokens in Authorization headers are redacted."""
        filter_instance = SensitiveDataFilter()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="Authorization: Bearer sk-abc123def456ghi789",
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)
        assert "sk-abc123def456ghi789" not in record.msg
        assert "Bearer" in record.msg
        assert "***REDACTED***" in record.msg

    def test_preserve_non_sensitive_data(self):
        """Verify non-sensitive data is not modified."""
        filter_instance = SensitiveDataFilter()

        original_msg = "User login successful from 192.168.1.1"
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg=original_msg,
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)
        assert record.msg == original_msg

    def test_recursive_dict_sanitization(self):
        """Verify nested dicts are sanitized."""
        filter_instance = SensitiveDataFilter()

        config = {
            "user": "admin",
            "database": {"host": "localhost", "password": "pass"},
            "api": {"token": "token", "endpoint": "https://api.example.com"},
        }

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="Config: %s",
            args=(config,),
            exc_info=None,
        )

        filter_instance.filter(record)
        # When a dict is passed as args to LogRecord with %s formatting,
        # it becomes args directly (not a tuple)
        sanitized_config = record.args
        assert sanitized_config["database"]["password"] == "***REDACTED***"
        assert sanitized_config["api"]["token"] == "***REDACTED***"
        assert sanitized_config["database"]["host"] == "localhost"
        assert sanitized_config["api"]["endpoint"] == "https://api.example.com"

    def test_long_token_partial_redaction(self):
        """Verify long tokens show first/last 4 chars for debugging."""
        filter_instance = SensitiveDataFilter()

        long_token = "abcdefghijklmnopqrstuvwxyz0123456789"
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg=f"Token: {long_token}",
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)
        # Should show first 4 and last 4 chars
        assert "abcd" in record.msg
        assert "6789" in record.msg
        assert "***REDACTED***" in record.msg
        assert long_token not in record.msg

    def test_short_token_not_redacted(self):
        """Verify short tokens (<32 chars) are not redacted by TOKEN_PATTERN."""
        filter_instance = SensitiveDataFilter()

        # Short string won't match the 32+ pattern, so it's not redacted
        short_token = "short"
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg=f"Token: {short_token}",
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)
        # Short tokens aren't matched by TOKEN_PATTERN (requires 32+ chars)
        assert short_token in record.msg  # Should not be redacted

    def test_multiple_sensitive_patterns(self):
        """Verify multiple sensitive patterns in same message are all redacted."""
        filter_instance = SensitiveDataFilter()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="api_key=sk-1234567890abcdef1234567890abcdef and Authorization: Bearer token123456789012345678901234567890",
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)
        # Both should be redacted
        assert "sk-1234567890abcdef1234567890abcdef" not in record.msg
        assert "token123456789012345678901234567890" not in record.msg

    def test_tuple_args_sanitization(self):
        """Verify tuple arguments are sanitized."""
        filter_instance = SensitiveDataFilter()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="User %s with token %s",
            args=("admin", "sk-1234567890abcdef1234567890abcdef"),
            exc_info=None,
        )

        filter_instance.filter(record)
        assert "sk-1234567890abcdef1234567890abcdef" not in record.args
        assert record.args[0] == "admin"
        assert "***REDACTED***" in record.args[1]

    def test_list_args_sanitization(self):
        """Verify list arguments are sanitized."""
        filter_instance = SensitiveDataFilter()

        token = "sk-1234567890abcdef1234567890abcdef"
        args = ["user1", token, "user2"]

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="Users: %s",
            args=(args,),
            exc_info=None,
        )

        filter_instance.filter(record)
        # Check the sanitized list in record.args
        sanitized_args = record.args[0]
        assert token not in sanitized_args
        assert sanitized_args[0] == "user1"
        assert "***REDACTED***" in sanitized_args[1]
        assert sanitized_args[2] == "user2"

    def test_password_field_redaction(self):
        """Verify password fields are redacted in various formats."""
        filter_instance = SensitiveDataFilter()

        test_cases = [
            ("password=super_secret", "password=***REDACTED***"),
            ("pwd=secret123", "pwd=***REDACTED***"),
            ("passwd:mypass", "passwd:***REDACTED***"),
        ]

        for original, expected_substr in test_cases:
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname=__file__,
                lineno=0,
                msg=original,
                args=(),
                exc_info=None,
            )
            filter_instance.filter(record)
            assert expected_substr in record.msg

    def test_secret_field_redaction(self):
        """Verify secret fields are redacted."""
        filter_instance = SensitiveDataFilter()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="Config: secret=my_secret_value",
            args=(),
            exc_info=None,
        )

        filter_instance.filter(record)
        assert "my_secret_value" not in record.msg
        assert "***REDACTED***" in record.msg

    def test_filter_always_returns_true(self):
        """Verify filter always returns True to allow logging."""
        filter_instance = SensitiveDataFilter()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = filter_instance.filter(record)
        assert result is True

    def test_filter_handles_none_args(self):
        """Verify filter handles None args gracefully."""
        filter_instance = SensitiveDataFilter()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="Test message",
            args=None,
            exc_info=None,
        )

        result = filter_instance.filter(record)
        assert result is True
        assert record.args is None

    def test_filter_handles_exception_safely(self):
        """Verify filter fails gracefully if sanitization raises exception."""
        filter_instance = SensitiveDataFilter()

        # Create a record with circular reference that the sanitizer will traverse
        circular_dict = {"data": "value"}
        circular_dict["self"] = circular_dict  # Create circular reference

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="Test",
            args=(circular_dict,),
            exc_info=None,
        )

        # Filter should still return True and not crash
        result = filter_instance.filter(record)
        assert result is True

    def test_case_insensitive_field_matching(self):
        """Verify sensitive field matching is case-insensitive."""
        filter_instance = SensitiveDataFilter()

        test_dict = {
            "API_KEY": "key",
            "PassWord": "pwd",
            "SECRET_KEY": "sec",
        }

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="Config: %s",
            args=(test_dict,),
            exc_info=None,
        )

        filter_instance.filter(record)
        # When a dict is passed as args to LogRecord with %s formatting,
        # it becomes args directly (not a tuple)
        sanitized_dict = record.args
        assert sanitized_dict["API_KEY"] == "***REDACTED***"
        assert sanitized_dict["PassWord"] == "***REDACTED***"
        assert sanitized_dict["SECRET_KEY"] == "***REDACTED***"

    def test_exception_text_sanitization(self):
        """Verify exception text is sanitized."""
        filter_instance = SensitiveDataFilter()

        exc_text = "Exception: API key sk-1234567890abcdef1234567890abcdef is invalid"

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=0,
            msg="Error occurred",
            args=(),
            exc_info=None,
        )
        record.exc_text = exc_text

        filter_instance.filter(record)
        assert "sk-1234567890abcdef1234567890abcdef" not in record.exc_text
        assert "***REDACTED***" in record.exc_text


class TestFilterAppliedToHandlers:
    """Tests to verify filter is applied to all handlers."""

    def test_filter_applied_to_console_handler(self, tmp_path, monkeypatch):
        """Verify sensitive data filter is applied to console handler."""
        monkeypatch.chdir(tmp_path)

        root_logger = logging.getLogger()
        cleanup_handlers(root_logger)

        stream = StringIO()

        with patch(
            "runpod_flash.runtime.context.is_local_development", return_value=False
        ):
            setup_logging(level=logging.INFO, stream=stream)

        # Verify console handler has the filter
        console_handlers = [
            h for h in root_logger.handlers if isinstance(h, logging.StreamHandler)
        ]
        assert len(console_handlers) == 1

        console_handler = console_handlers[0]
        filters = console_handler.filters
        assert len(filters) > 0

        sensitive_filters = [f for f in filters if isinstance(f, SensitiveDataFilter)]
        assert len(sensitive_filters) == 1

        cleanup_handlers(root_logger)

    def test_filter_applied_to_file_handler(self, tmp_path, monkeypatch):
        """Verify sensitive data filter is applied to file handler."""
        monkeypatch.chdir(tmp_path)

        root_logger = logging.getLogger()
        cleanup_handlers(root_logger)

        with patch(
            "runpod_flash.runtime.context.is_local_development", return_value=True
        ):
            setup_logging(level=logging.INFO)

        # Import here to access the class
        from logging.handlers import TimedRotatingFileHandler

        file_handlers = [
            h for h in root_logger.handlers if isinstance(h, TimedRotatingFileHandler)
        ]
        assert len(file_handlers) == 1

        file_handler = file_handlers[0]
        filters = file_handler.filters
        assert len(filters) > 0

        sensitive_filters = [f for f in filters if isinstance(f, SensitiveDataFilter)]
        assert len(sensitive_filters) == 1

        cleanup_handlers(root_logger)

    def test_sensitive_data_redacted_in_file_logs(self, tmp_path, monkeypatch):
        """Verify sensitive data is actually redacted in written log files."""
        monkeypatch.chdir(tmp_path)

        root_logger = logging.getLogger()
        cleanup_handlers(root_logger)

        with patch(
            "runpod_flash.runtime.context.is_local_development", return_value=True
        ):
            setup_logging(level=logging.INFO)

        # Log sensitive data
        logger = logging.getLogger("test")
        logger.info("API Key: sk-1234567890abcdef1234567890abcdef")

        # Force flush
        for handler in root_logger.handlers:
            handler.flush()

        # Read log file
        log_file = tmp_path / ".flash" / "logs" / "activity.log"
        assert log_file.exists()

        log_contents = log_file.read_text()

        # Verify sensitive data is redacted
        assert "sk-1234567890abcdef1234567890abcdef" not in log_contents
        assert "***REDACTED***" in log_contents

        cleanup_handlers(root_logger)

    def test_sensitive_data_redacted_in_console(self, tmp_path, monkeypatch):
        """Verify sensitive data is redacted in console output."""
        monkeypatch.chdir(tmp_path)

        root_logger = logging.getLogger()
        cleanup_handlers(root_logger)

        stream = StringIO()

        with patch(
            "runpod_flash.runtime.context.is_local_development", return_value=False
        ):
            setup_logging(level=logging.INFO, stream=stream)

        # Log sensitive data
        logger = logging.getLogger("test")
        logger.info("Password: super_secret_password_123")

        output = stream.getvalue()

        # Verify sensitive data is redacted in console
        assert "super_secret_password_123" not in output
        assert "***REDACTED***" in output

        cleanup_handlers(root_logger)
