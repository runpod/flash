"""Flash logging configuration with file-based logging for local development.

SECURITY NOTE: The file handler includes a SensitiveDataFilter that redacts
common patterns for API keys, passwords, and tokens. However, developers should
still avoid logging:
- Environment variables in bulk (os.environ)
- Request/response bodies without sanitization
- Raw HTTP headers
- Exception details from external APIs
"""

import logging
import os
import re
import sys
from logging.handlers import TimedRotatingFileHandler
from typing import Union, Optional, Any, Dict


class SensitiveDataFilter(logging.Filter):
    """Redacts sensitive information from log records.

    Prevents accidental logging of API keys, tokens, passwords, and other
    sensitive data by identifying and redacting common patterns:
    - API keys (RUNPOD_API_KEY, api_key, apiKey patterns)
    - Authorization headers (Bearer tokens)
    - Passwords (password, passwd, pwd fields)
    - Tokens (token, access_token, refresh_token, auth_token fields)
    - Secret keys (secret, secret_key fields)
    - Generic long tokens (32+ character alphanumeric strings)

    For long tokens, shows first and last 4 characters with redaction in middle
    to aid debugging while protecting sensitive values.
    """

    SENSITIVE_KEYS = {
        "api_key",
        "apikey",
        "api-key",
        "runpod_api_key",
        "password",
        "passwd",
        "pwd",
        "token",
        "access_token",
        "refresh_token",
        "auth_token",
        "secret",
        "secret_key",
        "authorization",
    }

    # Pattern for generic tokens: 32+ char alphanumeric/underscore/hyphen/dot strings
    # Excludes pure hex strings (commit SHAs, hashes) which are less likely to be tokens
    # Using negative lookahead to exclude pure hex: (?![0-9a-fA-F]+$)
    TOKEN_PATTERN = re.compile(r"(?![0-9a-fA-F]+$)\b[A-Za-z0-9_.-]{32,}\b")

    # Pattern for common API key formats - capture prefix, separator, and quotes for proper redaction
    API_KEY_PATTERN = re.compile(
        r"((?:api[_-]?key|apikey|runpod[_-]?api[_-]?key)\s*[:=]\s*['\"]?)([A-Za-z0-9_-]+)(['\"]?)",
        re.IGNORECASE,
    )

    # Pattern for Bearer tokens in Authorization headers
    BEARER_PATTERN = re.compile(r"(bearer\s+)([A-Za-z0-9_.-]+)", re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:
        """Sanitize log record by redacting sensitive data.

        Args:
            record: The log record to sanitize

        Returns:
            True to allow the record to be logged (always)
        """
        try:
            # Sanitize the main message
            if isinstance(record.msg, str):
                record.msg = self._redact_string(record.msg)

            # Sanitize message arguments if they exist
            if record.args:
                if isinstance(record.args, dict):
                    record.args = self._redact_dict(record.args)
                elif isinstance(record.args, (tuple, list)):
                    record.args = tuple(self._redact_value(arg) for arg in record.args)
                else:
                    record.args = self._redact_value(record.args)

            # Sanitize exception information if present
            if record.exc_text:
                record.exc_text = self._redact_string(record.exc_text)

        except Exception:
            # If sanitization fails, log the record anyway (fail open for logging)
            pass

        return True

    def _redact_string(self, text: str) -> str:
        """Redact sensitive patterns from a string.

        Args:
            text: String to sanitize

        Returns:
            String with sensitive patterns redacted
        """
        if not isinstance(text, str):
            return text

        # Redact Bearer tokens
        text = self.BEARER_PATTERN.sub(r"\1***REDACTED***", text)

        # Redact API key patterns
        text = self.API_KEY_PATTERN.sub(
            lambda m: f"{m.group(1)}***REDACTED***{m.group(3)}", text
        )

        # Redact generic long tokens
        text = self.TOKEN_PATTERN.sub(self._redact_token, text)

        # Redact common password/secret patterns
        # Match field names with : or = separators and redact the value, preserving separator
        # Handles quoted values (captures until closing quote) and unquoted values (captures until whitespace/comma)
        def redact_password_pattern(match):
            field_name = match.group(1)
            separator = match.group(2)
            return f"{field_name}{separator}***REDACTED***"

        # Pattern handles: password="value", password=value, password: value, etc.
        # For quoted values: captures everything until closing quote
        # For unquoted: captures until whitespace or comma
        text = re.sub(
            r"(password|passwd|pwd|secret)(\s*[:=]\s*)(?:\"([^\"]*)\"|'([^']*)'|([^\s,;]+))",
            lambda m: f"{m.group(1)}{m.group(2)}***REDACTED***",
            text,
            flags=re.IGNORECASE,
        )

        return text

    def _redact_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively redact sensitive keys in a dictionary.

        Args:
            data: Dictionary to sanitize

        Returns:
            New dictionary with sensitive values redacted
        """
        if not isinstance(data, dict):
            return data

        result = {}
        for key, value in data.items():
            if key.lower() in self.SENSITIVE_KEYS:
                # Unconditionally redact values for sensitive keys
                if isinstance(value, str) and len(value) > 8:
                    # For long strings, show first/last 4 chars for debugging
                    result[key] = f"{value[:4]}...***REDACTED***...{value[-4:]}"
                else:
                    result[key] = "***REDACTED***"
            elif isinstance(value, dict):
                result[key] = self._redact_dict(value)
            elif isinstance(value, (list, tuple)):
                result[key] = type(value)(
                    self._redact_dict(item)
                    if isinstance(item, dict)
                    else self._redact_value(item)
                    for item in value
                )
            else:
                result[key] = value

        return result

    def _redact_value(self, value: Any) -> Any:
        """Redact a single value if it's sensitive.

        Args:
            value: Value to check and potentially redact

        Returns:
            Redacted value or original value
        """
        if isinstance(value, str):
            return self._redact_string(value)
        elif isinstance(value, dict):
            return self._redact_dict(value)
        elif isinstance(value, (list, tuple)):
            return type(value)(self._redact_value(item) for item in value)
        return value

    @staticmethod
    def _redact_token(match: re.Match) -> str:
        """Generate redacted token showing first and last 4 chars.

        Args:
            match: Regex match object containing the token

        Returns:
            Redacted token string
        """
        token = match.group(0)
        if len(token) <= 8:
            return "***REDACTED***"
        return f"{token[:4]}...***REDACTED***...{token[-4:]}"


def _add_file_handler_if_local(
    logger: logging.Logger, level: int, fmt: Optional[str]
) -> None:
    """Add file handler for local development context only.

    Creates a daily rotating log file in .flash/logs/ directory that:
    - Rotates at midnight
    - Keeps 30 days of history
    - Uses same format as console output

    Args:
        logger: Root logger to attach file handler to
        level: Logging level for file handler
        fmt: Log message format string

    Note:
        Gracefully degrades if file logging fails - CLI continues with stdout only.
        Only activates in local development mode, skipped in deployed containers.
    """
    try:
        # Import at function level to avoid circular dependency
        from runpod_flash.runtime.context import is_local_development
        from runpod_flash.config import get_paths

        # Skip if running in deployed container
        if not is_local_development():
            return

        # Create logs directory
        paths = get_paths()
        paths.ensure_flash_dir()

        # Configure daily rotating file handler
        log_file = paths.logs_dir / "activity.log"
        file_handler = TimedRotatingFileHandler(
            filename=str(log_file),
            when="midnight",  # Rotate at midnight
            interval=1,  # Daily rotation
            backupCount=30,  # Keep 30 days
            encoding="utf-8",
        )
        file_handler.suffix = "%Y-%m-%d"  # Suffix: activity.log.2026-02-11
        file_handler.setFormatter(logging.Formatter(fmt))
        file_handler.setLevel(level)

        # Add sensitive data filter to prevent logging of API keys, tokens, etc.
        sensitive_filter = SensitiveDataFilter()
        file_handler.addFilter(sensitive_filter)

        logger.addHandler(file_handler)

    except Exception:
        # Graceful degradation: log warning but continue with stdout-only
        logger.warning("Could not set up file logging", exc_info=True)


def setup_logging(
    level: Union[int, str] = logging.INFO, stream=sys.stdout, fmt: Optional[str] = None
):
    """
    Sets up the root logger with a stream handler and basic formatting.
    Does nothing if handlers are already configured.
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    # Check for log level override via env var early
    env_level = os.environ.get("LOG_LEVEL")
    if env_level:
        level = getattr(logging, env_level.upper(), level)

    # Determine format based on final effective level
    if fmt is None:
        if level == logging.DEBUG:
            fmt = "%(asctime)s | %(levelname)-5s | %(name)s | %(filename)s:%(lineno)d | %(message)s"
        else:
            # Default format for INFO level and above
            fmt = "%(asctime)s | %(levelname)-5s | %(message)s"

    root_logger = logging.getLogger()
    if not root_logger.hasHandlers():
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter(fmt))
        root_logger.setLevel(level)

        # Add sensitive data filter to prevent logging of API keys, tokens, etc.
        sensitive_filter = SensitiveDataFilter()
        handler.addFilter(sensitive_filter)

        root_logger.addHandler(handler)

        # Add file handler for local development with same level/format
        _add_file_handler_if_local(root_logger, level, fmt)
