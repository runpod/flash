import logging
import os
import sys
from dataclasses import dataclass
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Union, Optional


@dataclass
class LoggingConfig:
    """Configuration for file-based logging.

    Attributes:
        enabled: Whether file-based logging is enabled (default: True)
        retention_days: Number of days to retain log files (default: 30, min: 1)
        log_dir: Directory to store log files (default: .flash/logs)
    """

    enabled: bool = True
    retention_days: int = 30
    log_dir: str = ".flash/logs"

    @classmethod
    def from_env(cls) -> "LoggingConfig":
        """Load configuration from environment variables.

        Environment variables:
        - FLASH_FILE_LOGGING_ENABLED: Enable/disable file logging (default: true)
        - FLASH_LOG_RETENTION_DAYS: Days to retain logs (default: 30, min: 1)
        - FLASH_LOG_DIR: Custom log directory (default: .flash/logs)

        Returns:
            LoggingConfig initialized from environment variables.
        """
        enabled = os.getenv("FLASH_FILE_LOGGING_ENABLED", "true").lower() == "true"

        retention_days = int(os.getenv("FLASH_LOG_RETENTION_DAYS", "30"))
        if retention_days < 1:
            logging.warning(
                f"Invalid FLASH_LOG_RETENTION_DAYS={retention_days}, using default 30"
            )
            retention_days = 30

        log_dir = os.getenv("FLASH_LOG_DIR", ".flash/logs")

        return cls(enabled=enabled, retention_days=retention_days, log_dir=log_dir)


# Global configuration (lazy-loaded)
_logging_config: Optional[LoggingConfig] = None


def get_logging_config() -> LoggingConfig:
    """Get global logging configuration (lazy-loaded).

    Returns:
        LoggingConfig instance initialized from environment.
    """
    global _logging_config
    if _logging_config is None:
        _logging_config = LoggingConfig.from_env()
    return _logging_config


def set_logging_config(config: LoggingConfig) -> None:
    """Set global logging configuration (for testing).

    Args:
        config: LoggingConfig to set as global.
    """
    global _logging_config
    _logging_config = config


def _add_file_handler_if_local(
    logger: logging.Logger, level: int, fmt: Optional[str]
) -> None:
    """Add file handler for local development context only.

    Creates a daily rotating log file that:
    - Rotates at midnight
    - Keeps configurable history (default: 30 days)
    - Uses same format as console output
    - Can be disabled via FLASH_FILE_LOGGING_ENABLED=false

    Args:
        logger: Root logger to attach file handler to
        level: Logging level for file handler
        fmt: Log message format string

    Note:
        Gracefully degrades if file logging fails - CLI continues with stdout only.
        Only activates in local development mode, skipped in deployed containers.
        Configured via environment variables (see LoggingConfig.from_env).
    """
    try:
        # Import at function level to avoid circular dependency
        from runpod_flash.runtime.context import is_local_development

        # Get configuration
        config = get_logging_config()

        # Skip if running in deployed container or disabled via config
        if not is_local_development() or not config.enabled:
            return

        # Create logs directory
        log_dir = Path(config.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        # Configure daily rotating file handler
        log_file = log_dir / "activity.log"
        file_handler = TimedRotatingFileHandler(
            filename=str(log_file),
            when="midnight",  # Rotate at midnight
            interval=1,  # Daily rotation
            backupCount=config.retention_days,  # Configurable retention
            encoding="utf-8",
        )
        file_handler.suffix = "%Y-%m-%d"  # Suffix: activity.log.2026-02-11
        file_handler.setFormatter(logging.Formatter(fmt))
        file_handler.setLevel(level)
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
        root_logger.addHandler(handler)

        # Add file handler for local development with same level/format
        _add_file_handler_if_local(root_logger, level, fmt)
