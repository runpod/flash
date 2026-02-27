"""Tests for cli/utils/conda.py - conda environment management."""

import subprocess
from unittest.mock import MagicMock, patch


from runpod_flash.cli.utils.conda import (
    check_conda_available,
    create_conda_environment,
    environment_exists,
    get_activation_command,
    install_packages_in_env,
)


class TestCheckCondaAvailable:
    """Test check_conda_available function."""

    @patch("runpod_flash.cli.utils.conda.subprocess.run")
    def test_returns_true_when_available(self, mock_run):
        """Returns True when conda --version succeeds."""
        mock_run.return_value = MagicMock(returncode=0)
        assert check_conda_available() is True
        mock_run.assert_called_once()

    @patch("runpod_flash.cli.utils.conda.subprocess.run")
    def test_returns_false_on_nonzero_exit(self, mock_run):
        """Returns False when conda returns non-zero exit code."""
        mock_run.return_value = MagicMock(returncode=1)
        assert check_conda_available() is False

    @patch("runpod_flash.cli.utils.conda.subprocess.run")
    def test_returns_false_on_file_not_found(self, mock_run):
        """Returns False when conda binary is not found."""
        mock_run.side_effect = FileNotFoundError()
        assert check_conda_available() is False

    @patch("runpod_flash.cli.utils.conda.subprocess.run")
    def test_returns_false_on_subprocess_error(self, mock_run):
        """Returns False on subprocess errors."""
        mock_run.side_effect = subprocess.SubprocessError("error")
        assert check_conda_available() is False

    @patch("runpod_flash.cli.utils.conda.subprocess.run")
    def test_timeout_is_set(self, mock_run):
        """Verify timeout is set when calling conda."""
        mock_run.return_value = MagicMock(returncode=0)
        check_conda_available()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["timeout"] == 5


class TestCreateCondaEnvironment:
    """Test create_conda_environment function."""

    @patch("runpod_flash.cli.utils.conda.subprocess.run")
    def test_success(self, mock_run):
        """Returns (True, message) on success."""
        mock_run.return_value = MagicMock(returncode=0)
        success, msg = create_conda_environment("test-env", "3.11")
        assert success is True
        assert "successfully" in msg.lower()

    @patch("runpod_flash.cli.utils.conda.subprocess.run")
    def test_failure(self, mock_run):
        """Returns (False, message) on failure."""
        mock_run.return_value = MagicMock(returncode=1, stderr="conda error")
        success, msg = create_conda_environment("test-env")
        assert success is False
        assert "conda error" in msg

    @patch("runpod_flash.cli.utils.conda.subprocess.run")
    def test_timeout(self, mock_run):
        """Returns (False, message) on timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired("conda", 300)
        success, msg = create_conda_environment("test-env")
        assert success is False
        assert "timed out" in msg.lower()

    @patch("runpod_flash.cli.utils.conda.subprocess.run")
    def test_generic_exception(self, mock_run):
        """Returns (False, message) on unexpected error."""
        mock_run.side_effect = RuntimeError("unexpected")
        success, msg = create_conda_environment("test-env")
        assert success is False
        assert "unexpected" in msg

    @patch("runpod_flash.cli.utils.conda.subprocess.run")
    def test_passes_python_version(self, mock_run):
        """Verify python version is included in command."""
        mock_run.return_value = MagicMock(returncode=0)
        create_conda_environment("test-env", "3.12")
        cmd = mock_run.call_args[0][0]
        assert "python=3.12" in cmd


class TestInstallPackagesInEnv:
    """Test install_packages_in_env function."""

    @patch("runpod_flash.cli.utils.conda.subprocess.run")
    def test_pip_install_success(self, mock_run):
        """Installs with pip by default."""
        mock_run.return_value = MagicMock(returncode=0)
        success, msg = install_packages_in_env("test-env", ["numpy", "pandas"])
        assert success is True
        cmd = mock_run.call_args[0][0]
        assert "pip" in cmd
        assert "numpy" in cmd
        assert "pandas" in cmd

    @patch("runpod_flash.cli.utils.conda.subprocess.run")
    def test_conda_install(self, mock_run):
        """Installs with conda when use_pip=False."""
        mock_run.return_value = MagicMock(returncode=0)
        success, msg = install_packages_in_env("test-env", ["scipy"], use_pip=False)
        assert success is True
        cmd = mock_run.call_args[0][0]
        assert "conda" == cmd[0]
        assert "install" in cmd
        assert "scipy" in cmd

    @patch("runpod_flash.cli.utils.conda.subprocess.run")
    def test_install_failure(self, mock_run):
        """Returns (False, message) on failure."""
        mock_run.return_value = MagicMock(returncode=1, stderr="install error")
        success, msg = install_packages_in_env("test-env", ["bad-pkg"])
        assert success is False
        assert "install error" in msg

    @patch("runpod_flash.cli.utils.conda.subprocess.run")
    def test_install_timeout(self, mock_run):
        """Returns (False, message) on timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 600)
        success, msg = install_packages_in_env("test-env", ["torch"])
        assert success is False
        assert "timed out" in msg.lower()


class TestEnvironmentExists:
    """Test environment_exists function."""

    @patch("runpod_flash.cli.utils.conda.subprocess.run")
    def test_exists_true(self, mock_run):
        """Returns True when environment is in the list."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="base\ntest-env\nother-env"
        )
        assert environment_exists("test-env") is True

    @patch("runpod_flash.cli.utils.conda.subprocess.run")
    def test_exists_false(self, mock_run):
        """Returns False when environment is not in the list."""
        mock_run.return_value = MagicMock(returncode=0, stdout="base\nother-env")
        assert environment_exists("test-env") is False

    @patch("runpod_flash.cli.utils.conda.subprocess.run")
    def test_exists_on_failure(self, mock_run):
        """Returns False on subprocess failure."""
        mock_run.return_value = MagicMock(returncode=1)
        assert environment_exists("test-env") is False

    @patch("runpod_flash.cli.utils.conda.subprocess.run")
    def test_exists_on_exception(self, mock_run):
        """Returns False on exception."""
        mock_run.side_effect = Exception("unexpected")
        assert environment_exists("test-env") is False


class TestGetActivationCommand:
    """Test get_activation_command function."""

    def test_returns_correct_command(self):
        """Returns correct conda activate command."""
        assert get_activation_command("my-env") == "conda activate my-env"

    def test_with_different_name(self):
        """Works with different environment names."""
        assert get_activation_command("flash-3.11") == "conda activate flash-3.11"
