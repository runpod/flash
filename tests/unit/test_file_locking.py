"""
Unit tests for cross-platform file locking utilities.

Tests the file_lock module across different platforms and scenarios:
- Windows msvcrt.locking() support
- Unix fcntl.flock() support
- Fallback locking mechanism
- Concurrent access patterns
- Error handling and timeout behavior
"""

import platform
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from runpod_flash.core.utils.file_lock import (
    file_lock,
    FileLockError,
    FileLockTimeout,
    get_platform_info,
    _acquire_fallback_lock,
    _release_fallback_lock,
)


class TestPlatformDetection:
    """Test platform detection and capabilities."""

    def test_get_platform_info(self):
        """Test that platform info returns expected structure."""
        info = get_platform_info()

        required_keys = ["platform", "windows_locking", "unix_locking", "fallback_only"]
        assert all(key in info for key in required_keys)

        # Platform should be one of the expected values
        assert info["platform"] in ("Windows", "Linux", "Darwin")

        # Exactly one locking mechanism should be available (or fallback)
        locking_mechanisms = [
            info["windows_locking"],
            info["unix_locking"],
            info["fallback_only"],
        ]
        assert sum(locking_mechanisms) >= 1  # At least fallback should work

    @patch("runpod_flash.core.utils.file_lock.platform.system", return_value="Windows")
    def test_platform_detection_windows(self, mock_system):
        """Test Windows platform detection via get_platform_info()."""
        # Don't use reload() — it pollutes module-level state (_IS_WINDOWS,
        # _UNIX_LOCKING_AVAILABLE, etc.) for all subsequent tests.
        # get_platform_info() calls platform.system() at runtime, so patching suffices.
        info = get_platform_info()
        assert info["platform"] == "Windows"

    @patch("runpod_flash.core.utils.file_lock.platform.system", return_value="Linux")
    def test_platform_detection_linux(self, mock_system):
        """Test Linux platform detection via get_platform_info()."""
        info = get_platform_info()
        assert info["platform"] == "Linux"


@pytest.mark.serial
class TestFileLocking:
    """Test cross-platform file locking functionality."""

    def setup_method(self):
        """Set up temporary files for testing."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.test_file = self.temp_dir / "test_file.dat"
        self.test_file.write_bytes(b"test data")

    def teardown_method(self):
        """Clean up temporary files and wait for any background threads."""
        # Give daemon threads time to release locks
        time.sleep(0.2)
        if self.temp_dir.exists():
            for file in self.temp_dir.iterdir():
                if file.is_file():
                    try:
                        file.unlink()
                    except OSError:
                        pass
            try:
                self.temp_dir.rmdir()
            except OSError:
                pass

    def test_exclusive_lock_basic(self):
        """Test basic exclusive locking functionality."""
        with open(self.test_file, "rb") as f:
            with file_lock(f, exclusive=True):
                data = f.read()
                assert data == b"test data"

    def test_shared_lock_basic(self):
        """Test basic shared locking functionality."""
        with open(self.test_file, "rb") as f:
            with file_lock(f, exclusive=False):
                data = f.read()
                assert data == b"test data"

    def test_concurrent_shared_locks(self):
        """Test that multiple shared locks can coexist."""
        results = []
        errors = []

        def read_with_shared_lock(file_path, results_list, errors_list):
            try:
                with open(file_path, "rb") as f:
                    with file_lock(f, exclusive=False, timeout=5.0):
                        time.sleep(0.1)  # Hold lock briefly
                        data = f.read()
                        results_list.append(data)
            except Exception as e:
                errors_list.append(e)

        # Create multiple threads with shared locks
        threads = []
        for i in range(3):
            thread = threading.Thread(
                target=read_with_shared_lock, args=(self.test_file, results, errors)
            )
            threads.append(thread)

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join(timeout=10)

        # All should succeed (shared locks are compatible)
        assert len(errors) == 0, f"Unexpected errors: {errors}"
        assert len(results) == 3
        assert all(data == b"test data" for data in results)

    def test_exclusive_lock_blocks_others(self):
        """Test that exclusive locks block other access."""
        # Use a dedicated temp file to avoid interference with other tests
        lock_test_file = self.temp_dir / "exclusive_test.dat"
        lock_test_file.write_bytes(b"exclusive test")

        results = []
        errors = []
        holder_acquired = threading.Event()

        def exclusive_lock_holder(file_path, hold_time):
            try:
                with open(file_path, "rb") as f:
                    with file_lock(f, exclusive=True, timeout=10.0):
                        holder_acquired.set()
                        time.sleep(hold_time)
                        results.append("holder_success")
            except Exception as e:
                errors.append(f"holder: {e}")

        def exclusive_lock_waiter(file_path):
            holder_acquired.wait(timeout=5.0)
            time.sleep(0.1)
            try:
                with open(file_path, "rb") as f:
                    with file_lock(f, exclusive=True, timeout=1.0):
                        results.append("waiter_success")
            except FileLockTimeout:
                errors.append("waiter: timeout as expected")
            except Exception as e:
                errors.append(f"waiter: {e}")

        holder_thread = threading.Thread(
            target=exclusive_lock_holder,
            args=(lock_test_file, 2.0),
            daemon=True,
        )
        waiter_thread = threading.Thread(
            target=exclusive_lock_waiter,
            args=(lock_test_file,),
            daemon=True,
        )

        holder_thread.start()
        waiter_thread.start()

        waiter_thread.join(timeout=10)
        holder_thread.join(timeout=10)

        assert "holder_success" in results
        assert any("timeout as expected" in str(error) for error in errors)

    def test_timeout_behavior(self):
        """Test file lock timeout functionality."""
        lock_file = self.temp_dir / "timeout_test.dat"
        lock_file.write_bytes(b"timeout test")
        holder_acquired = threading.Event()

        def hold_lock_for_duration():
            with open(lock_file, "rb") as f:
                with file_lock(f, exclusive=True, timeout=10.0):
                    holder_acquired.set()
                    time.sleep(3.0)

        holder_thread = threading.Thread(target=hold_lock_for_duration, daemon=True)
        holder_thread.start()

        holder_acquired.wait(timeout=5.0)
        time.sleep(0.1)

        with pytest.raises(FileLockTimeout):
            with open(lock_file, "rb") as f:
                with file_lock(f, exclusive=True, timeout=1.0):
                    pass

        holder_thread.join(timeout=10)

    def test_file_lock_with_write_operations(self):
        """Test file locking with write operations."""
        write_file = self.temp_dir / "write_test.dat"

        # Write initial data
        with open(write_file, "wb") as f:
            with file_lock(f, exclusive=True):
                f.write(b"initial data")

        # Verify data was written
        assert write_file.read_bytes() == b"initial data"

        # Overwrite with new data
        with open(write_file, "wb") as f:
            with file_lock(f, exclusive=True):
                f.write(b"updated data")

        # Verify data was updated
        assert write_file.read_bytes() == b"updated data"


@pytest.mark.serial
class TestPlatformSpecificLocking:
    """Test platform-specific locking mechanisms."""

    def setup_method(self):
        """Set up temporary files for testing."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.test_file = self.temp_dir / "platform_test.dat"
        self.test_file.write_bytes(b"platform test data")

    def teardown_method(self):
        """Clean up temporary files."""
        if self.temp_dir.exists():
            for file in self.temp_dir.iterdir():
                if file.is_file():
                    file.unlink()
            self.temp_dir.rmdir()

    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific test")
    def test_windows_locking_available(self):
        """Test Windows locking is available on Windows platform."""
        import runpod_flash.core.utils.file_lock as file_lock_module

        assert file_lock_module._IS_WINDOWS
        # msvcrt should be available on Windows
        if file_lock_module._WINDOWS_LOCKING_AVAILABLE:
            assert file_lock_module.msvcrt is not None

    @pytest.mark.skipif(platform.system() == "Windows", reason="Unix-specific test")
    def test_unix_locking_available(self):
        """Test Unix locking is available on Unix platforms."""
        import runpod_flash.core.utils.file_lock as file_lock_module

        assert file_lock_module._IS_UNIX
        # fcntl should be available on Unix
        if file_lock_module._UNIX_LOCKING_AVAILABLE:
            assert file_lock_module.fcntl is not None

    def test_fallback_locking_mechanism(self):
        """Test fallback locking using lock files."""
        lock_test_file = self.temp_dir / "fallback_test.dat"
        lock_test_file.write_bytes(b"fallback test")

        with open(lock_test_file, "rb") as f:
            # Test fallback lock creation
            _acquire_fallback_lock(f, exclusive=True, timeout=5.0)

            # Verify lock file was created
            expected_lock_file = lock_test_file.with_suffix(".dat.lock")
            assert expected_lock_file.exists()

            # Test fallback lock release
            _release_fallback_lock(f)

            # Verify lock file was removed
            assert not expected_lock_file.exists()

    def test_fallback_lock_timeout(self):
        """Test fallback locking timeout behavior."""
        lock_test_file = self.temp_dir / "fallback_timeout.dat"
        lock_test_file.write_bytes(b"fallback timeout test")

        # Create lock file manually to simulate existing lock
        lock_file = lock_test_file.with_suffix(".dat.lock")
        lock_file.touch()

        try:
            with open(lock_test_file, "rb") as f:
                # Should timeout when trying to acquire existing lock
                with pytest.raises(FileLockError, match="Fallback lock timeout"):
                    _acquire_fallback_lock(f, exclusive=True, timeout=0.5)
        finally:
            # Clean up lock file
            if lock_file.exists():
                lock_file.unlink()


class TestErrorHandling:
    """Test error handling in file locking operations."""

    def test_file_lock_error_inheritance(self):
        """Test FileLockError exception hierarchy."""
        base_error = FileLockError("base error")
        timeout_error = FileLockTimeout("timeout error")

        assert isinstance(timeout_error, FileLockError)
        assert str(base_error) == "base error"
        assert str(timeout_error) == "timeout error"

    def test_invalid_file_handle(self):
        """Test behavior with invalid file handles."""
        # This test depends on platform-specific behavior
        # Different platforms may handle invalid file descriptors differently
        pass  # Implementation depends on specific platform requirements

    def test_lock_cleanup_on_exception(self):
        """Test that locks are properly released even when exceptions occur."""
        temp_dir = Path(tempfile.mkdtemp())
        test_file = temp_dir / "exception_test.dat"
        test_file.write_bytes(b"exception test")

        try:
            with open(test_file, "rb") as f:
                with pytest.raises(RuntimeError, match="intentional error"):
                    with file_lock(f, exclusive=True):
                        # Simulate an error occurring while holding the lock
                        raise RuntimeError("intentional error")

            # Lock should be released even after exception
            # Verify by successfully acquiring lock again
            with open(test_file, "rb") as f:
                with file_lock(f, exclusive=True, timeout=1.0):
                    data = f.read()
                    assert data == b"exception test"

        finally:
            # Clean up
            test_file.unlink()
            temp_dir.rmdir()


if __name__ == "__main__":
    # Run specific tests to validate cross-platform file locking
    pytest.main([__file__, "-v", "-s"])
