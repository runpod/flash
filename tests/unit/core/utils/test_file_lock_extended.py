"""Extended tests for core/utils/file_lock.py - cross-platform file locking."""

import platform
from unittest.mock import patch

import pytest

from runpod_flash.core.utils.file_lock import (
    FileLockError,
    FileLockTimeout,
    _acquire_fallback_lock,
    _acquire_unix_lock,
    _release_fallback_lock,
    _release_unix_lock,
    file_lock,
    get_platform_info,
)


class TestFileLock:
    """Test file_lock context manager."""

    def test_acquire_and_release_exclusive(self, tmp_path):
        """Acquires and releases exclusive lock successfully."""
        lock_file = tmp_path / "test.lock"
        lock_file.write_bytes(b"data")

        with open(lock_file, "rb") as f:
            with file_lock(f, exclusive=True):
                # Lock is held here
                assert True
        # Lock should be released

    def test_acquire_and_release_shared(self, tmp_path):
        """Acquires and releases shared lock successfully."""
        lock_file = tmp_path / "test.lock"
        lock_file.write_bytes(b"data")

        with open(lock_file, "rb") as f:
            with file_lock(f, exclusive=False):
                assert True

    def test_lock_released_on_exception(self, tmp_path):
        """Lock is released even when an exception occurs."""
        lock_file = tmp_path / "test.lock"
        lock_file.write_bytes(b"data")

        with pytest.raises(ValueError, match="test error"):
            with open(lock_file, "rb") as f:
                with file_lock(f, exclusive=True):
                    raise ValueError("test error")

        # Lock should be released - should be able to acquire again
        with open(lock_file, "rb") as f:
            with file_lock(f, exclusive=True):
                assert True

    def test_timeout_raises_file_lock_timeout(self, tmp_path):
        """FileLockTimeout is raised when lock cannot be acquired within timeout."""
        lock_file = tmp_path / "test.lock"
        lock_file.write_bytes(b"data")

        # Mock acquire to always fail
        with (
            patch(
                "runpod_flash.core.utils.file_lock._acquire_unix_lock",
                side_effect=OSError("locked"),
            ),
            patch("runpod_flash.core.utils.file_lock._IS_UNIX", True),
            patch("runpod_flash.core.utils.file_lock._UNIX_LOCKING_AVAILABLE", True),
        ):
            with open(lock_file, "rb") as f:
                with pytest.raises(FileLockTimeout, match="Could not acquire"):
                    with file_lock(f, exclusive=True, timeout=0.2, retry_interval=0.05):
                        pass

    def test_none_timeout_retries_indefinitely(self, tmp_path):
        """With timeout=None, retries until lock is acquired."""
        lock_file = tmp_path / "test.lock"
        lock_file.write_bytes(b"data")

        call_count = 0

        def fail_then_succeed(file_handle, exclusive):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise OSError("locked")
            # Success on 3rd try

        with (
            patch(
                "runpod_flash.core.utils.file_lock._acquire_unix_lock",
                side_effect=fail_then_succeed,
            ),
            patch("runpod_flash.core.utils.file_lock._IS_UNIX", True),
            patch("runpod_flash.core.utils.file_lock._UNIX_LOCKING_AVAILABLE", True),
            patch("runpod_flash.core.utils.file_lock._release_unix_lock"),
        ):
            with open(lock_file, "rb") as f:
                with file_lock(f, exclusive=True, timeout=None, retry_interval=0.01):
                    assert call_count == 3


class TestUnixLocking:
    """Test Unix-specific locking (only on Unix platforms)."""

    @pytest.mark.skipif(platform.system() == "Windows", reason="Unix-only test")
    def test_acquire_exclusive_lock(self, tmp_path):
        """Acquires exclusive Unix lock."""
        lock_file = tmp_path / "test.lock"
        lock_file.write_bytes(b"data")

        with open(lock_file, "rb") as f:
            _acquire_unix_lock(f, exclusive=True)
            _release_unix_lock(f)

    @pytest.mark.skipif(platform.system() == "Windows", reason="Unix-only test")
    def test_acquire_shared_lock(self, tmp_path):
        """Acquires shared Unix lock."""
        lock_file = tmp_path / "test.lock"
        lock_file.write_bytes(b"data")

        with open(lock_file, "rb") as f:
            _acquire_unix_lock(f, exclusive=False)
            _release_unix_lock(f)

    def test_unix_lock_unavailable_raises(self):
        """Raises FileLockError when fcntl is not available."""
        with patch("runpod_flash.core.utils.file_lock._UNIX_LOCKING_AVAILABLE", False):
            with pytest.raises(FileLockError, match="not available"):
                _acquire_unix_lock(None, exclusive=True)


class TestFallbackLocking:
    """Test fallback file-based locking."""

    def test_fallback_creates_lock_file(self, tmp_path):
        """Fallback creates a .lock file."""
        data_file = tmp_path / "data.pkl"
        data_file.write_bytes(b"data")

        with open(data_file, "rb") as f:
            _acquire_fallback_lock(f, exclusive=True, timeout=5.0)
            lock_path = data_file.with_suffix(".pkl.lock")
            assert lock_path.exists()
            _release_fallback_lock(f)
            assert not lock_path.exists()

    def test_fallback_timeout(self, tmp_path):
        """Fallback raises FileLockError on timeout when lock file exists."""
        data_file = tmp_path / "data.pkl"
        data_file.write_bytes(b"data")
        lock_file = data_file.with_suffix(".pkl.lock")
        lock_file.touch()  # Pre-create lock file

        with open(data_file, "rb") as f:
            with pytest.raises(FileLockError, match="Fallback lock timeout"):
                _acquire_fallback_lock(f, exclusive=True, timeout=0.2)

    def test_release_fallback_handles_missing_lock_file(self, tmp_path):
        """Release doesn't raise when lock file doesn't exist."""
        data_file = tmp_path / "data.pkl"
        data_file.write_bytes(b"data")

        with open(data_file, "rb") as f:
            _release_fallback_lock(f)  # Should not raise


class TestGetPlatformInfo:
    """Test get_platform_info function."""

    def test_returns_dict_with_expected_keys(self):
        """Returns dict with platform, locking availability."""
        info = get_platform_info()
        assert "platform" in info
        assert "windows_locking" in info
        assert "unix_locking" in info
        assert "fallback_only" in info

    def test_platform_matches_system(self):
        """Platform matches current system."""
        info = get_platform_info()
        assert info["platform"] == platform.system()

    @pytest.mark.skipif(platform.system() == "Windows", reason="Unix-only test")
    def test_unix_locking_available_on_unix(self):
        """Unix locking should be available on Unix/macOS."""
        info = get_platform_info()
        assert info["unix_locking"] is True
        assert info["fallback_only"] is False
