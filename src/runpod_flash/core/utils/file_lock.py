"""
Cross-platform file locking utilities.

Provides unified file locking interface that works across Windows, macOS, and Linux.
Uses platform-appropriate locking mechanisms:
- Windows: msvcrt.locking()
- Unix/Linux/macOS: fcntl.flock()
- Fallback: Basic file existence checking (limited protection)
"""

import contextlib
import logging
import platform
import time
from pathlib import Path
from typing import BinaryIO, Optional

log = logging.getLogger(__name__)

# Platform detection
_IS_WINDOWS = platform.system() == "Windows"
_IS_UNIX = platform.system() in ("Linux", "Darwin")

# Initialize availability flags
_WINDOWS_LOCKING_AVAILABLE = False
_UNIX_LOCKING_AVAILABLE = False

# Import platform-specific modules
if _IS_WINDOWS:
    try:
        import msvcrt

        _WINDOWS_LOCKING_AVAILABLE = True
    except ImportError:
        msvcrt = None
        log.warning("msvcrt not available on Windows platform")

if _IS_UNIX:
    try:
        import fcntl

        _UNIX_LOCKING_AVAILABLE = True
    except ImportError:
        fcntl = None
        log.warning("fcntl not available on Unix platform")


class FileLockError(Exception):
    """Exception raised when file locking operations fail."""

    pass


class FileLockTimeout(FileLockError):
    """Exception raised when file locking times out."""

    pass


@contextlib.contextmanager
def file_lock(
    file_handle: BinaryIO,
    exclusive: bool = True,
    timeout: Optional[float] = 10.0,
    retry_interval: float = 0.1,
):
    """
    Cross-platform file locking context manager.

    Args:
        file_handle: Open file handle to lock
        exclusive: True for exclusive lock, False for shared lock
        timeout: Maximum seconds to wait for lock (None = no timeout)
        retry_interval: Seconds to wait between lock attempts

    Raises:
        FileLockTimeout: If lock cannot be acquired within timeout
        FileLockError: If locking operation fails

    Usage:
        with open("file.dat", "rb") as f:
            with file_lock(f, exclusive=False):  # Shared read lock
                data = f.read()

        with open("file.dat", "wb") as f:
            with file_lock(f, exclusive=True):   # Exclusive write lock
                f.write(data)
    """
    lock_acquired = False
    start_time = time.time()

    try:
        # Platform-specific locking
        while not lock_acquired:
            try:
                if _IS_WINDOWS and _WINDOWS_LOCKING_AVAILABLE:
                    _acquire_windows_lock(file_handle, exclusive)
                elif _IS_UNIX and _UNIX_LOCKING_AVAILABLE:
                    _acquire_unix_lock(file_handle, exclusive)
                else:
                    # Fallback - limited protection via file existence
                    _acquire_fallback_lock(file_handle, exclusive, timeout)

                lock_acquired = True

            except (OSError, IOError, FileLockError) as e:
                # Check timeout
                if timeout is not None and (time.time() - start_time) >= timeout:
                    raise FileLockTimeout(
                        f"Could not acquire file lock within {timeout} seconds: {e}"
                    ) from e

                # Retry after interval
                time.sleep(retry_interval)

        # Lock acquired successfully
        yield

    finally:
        # Release lock
        if lock_acquired:
            try:
                if _IS_WINDOWS and _WINDOWS_LOCKING_AVAILABLE:
                    _release_windows_lock(file_handle)
                elif _IS_UNIX and _UNIX_LOCKING_AVAILABLE:
                    _release_unix_lock(file_handle)
                else:
                    _release_fallback_lock(file_handle)

            except Exception as e:
                log.error(f"Error releasing file lock: {e}")
                # Don't raise - we're in cleanup


def _acquire_windows_lock(file_handle: BinaryIO, exclusive: bool) -> None:
    """Acquire Windows file lock using msvcrt.locking()."""
    if not _WINDOWS_LOCKING_AVAILABLE:
        raise FileLockError("Windows file locking not available (msvcrt missing)")

    # Windows locking modes
    if exclusive:
        lock_mode = msvcrt.LK_NBLCK  # Non-blocking exclusive lock
    else:
        # Windows doesn't have shared locks in msvcrt
        # Fall back to exclusive for compatibility
        lock_mode = msvcrt.LK_NBLCK
        log.debug("Windows: Using exclusive lock instead of shared (msvcrt limitation)")

    try:
        # Lock the entire file (position 0, length 1)
        file_handle.seek(0)
        msvcrt.locking(file_handle.fileno(), lock_mode, 1)
    except OSError as e:
        raise FileLockError(f"Failed to acquire Windows file lock: {e}") from e


def _release_windows_lock(file_handle: BinaryIO) -> None:
    """Release Windows file lock."""
    if not _WINDOWS_LOCKING_AVAILABLE:
        return

    try:
        file_handle.seek(0)
        msvcrt.locking(file_handle.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError as e:
        raise FileLockError(f"Failed to release Windows file lock: {e}") from e


def _acquire_unix_lock(file_handle: BinaryIO, exclusive: bool) -> None:
    """Acquire Unix file lock using fcntl.flock()."""
    if not _UNIX_LOCKING_AVAILABLE:
        raise FileLockError("Unix file locking not available (fcntl missing)")

    # Unix locking modes
    if exclusive:
        lock_mode = fcntl.LOCK_EX | fcntl.LOCK_NB  # Non-blocking exclusive
    else:
        lock_mode = fcntl.LOCK_SH | fcntl.LOCK_NB  # Non-blocking shared

    try:
        fcntl.flock(file_handle.fileno(), lock_mode)
    except (OSError, IOError) as e:
        raise FileLockError(f"Failed to acquire Unix file lock: {e}") from e


def _release_unix_lock(file_handle: BinaryIO) -> None:
    """Release Unix file lock."""
    if not _UNIX_LOCKING_AVAILABLE:
        return

    try:
        fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)
    except (OSError, IOError) as e:
        raise FileLockError(f"Failed to release Unix file lock: {e}") from e


def _acquire_fallback_lock(
    file_handle: BinaryIO, exclusive: bool, timeout: Optional[float]
) -> None:
    """
    Fallback locking using lock files.

    This provides minimal protection but doesn't prevent all race conditions.
    It's better than no locking but not as robust as OS-level file locks.
    """
    log.warning(
        "Using fallback file locking - limited protection against race conditions"
    )

    # Create lock file based on the original file
    file_path = (
        Path(file_handle.name) if hasattr(file_handle, "name") else Path("unknown")
    )
    lock_file = file_path.with_suffix(file_path.suffix + ".lock")

    start_time = time.time()

    while True:
        try:
            # Try to create lock file atomically
            lock_file.touch(mode=0o600, exist_ok=False)
            log.debug(f"Fallback lock file created: {lock_file}")
            return

        except FileExistsError:
            # Lock file exists, check timeout
            if timeout is not None and (time.time() - start_time) >= timeout:
                raise FileLockError(f"Fallback lock timeout: {lock_file} exists")

            # Wait and retry
            time.sleep(0.1)


def _release_fallback_lock(file_handle: BinaryIO) -> None:
    """Release fallback lock by removing lock file."""
    try:
        file_path = (
            Path(file_handle.name) if hasattr(file_handle, "name") else Path("unknown")
        )
        lock_file = file_path.with_suffix(file_path.suffix + ".lock")

        if lock_file.exists():
            lock_file.unlink()
            log.debug(f"Fallback lock file removed: {lock_file}")

    except Exception as e:
        log.error(f"Failed to remove fallback lock file: {e}")


def get_platform_info() -> dict:
    """Get information about current platform and available locking mechanisms."""
    return {
        "platform": platform.system(),
        "windows_locking": _IS_WINDOWS and _WINDOWS_LOCKING_AVAILABLE,
        "unix_locking": _IS_UNIX and _UNIX_LOCKING_AVAILABLE,
        "fallback_only": not (_WINDOWS_LOCKING_AVAILABLE or _UNIX_LOCKING_AVAILABLE),
    }
