import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from typing import Union, Optional


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
