"""Unit tests for run CLI command."""

import pytest
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner

from runpod_flash.cli.main import app


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_fastapi_app(tmp_path):
    """Create minimal Flash project with @remote function for testing."""
    worker_file = tmp_path / "worker.py"
    worker_file.write_text(
        "from runpod_flash import LiveServerless, remote\n"
        "gpu_config = LiveServerless(name='test_worker')\n"
        "@remote(gpu_config)\n"
        "async def process(data: dict) -> dict:\n"
        "    return data\n"
    )
    return tmp_path


class TestRunCommandEnvironmentVariables:
    """Test flash run command environment variable support."""

    def test_port_from_environment_variable(
        self, runner, temp_fastapi_app, monkeypatch
    ):
        """Test that FLASH_PORT environment variable is respected."""
        monkeypatch.chdir(temp_fastapi_app)
        monkeypatch.setenv("FLASH_PORT", "8080")

        # Mock subprocess to capture command and prevent actual server start
        with patch("runpod_flash.cli.commands.run.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.wait.side_effect = KeyboardInterrupt()
            mock_popen.return_value = mock_process

            # Mock OS-level process group operations
            with patch("runpod_flash.cli.commands.run.os.getpgid") as mock_getpgid:
                mock_getpgid.return_value = 12345
                with patch("runpod_flash.cli.commands.run.os.killpg"):
                    runner.invoke(app, ["run"])

                    # Verify port 8080 was used in uvicorn command
                    call_args = mock_popen.call_args[0][0]
                    assert "--port" in call_args
                    port_index = call_args.index("--port")
                    assert call_args[port_index + 1] == "8080"

    def test_host_from_environment_variable(
        self, runner, temp_fastapi_app, monkeypatch
    ):
        """Test that FLASH_HOST environment variable is respected."""
        monkeypatch.chdir(temp_fastapi_app)
        monkeypatch.setenv("FLASH_HOST", "0.0.0.0")

        # Mock subprocess to capture command
        with patch("runpod_flash.cli.commands.run.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.wait.side_effect = KeyboardInterrupt()
            mock_popen.return_value = mock_process

            # Mock OS-level operations
            with patch("runpod_flash.cli.commands.run.os.getpgid") as mock_getpgid:
                mock_getpgid.return_value = 12345
                with patch("runpod_flash.cli.commands.run.os.killpg"):
                    runner.invoke(app, ["run"])

                    # Verify host 0.0.0.0 was used
                    call_args = mock_popen.call_args[0][0]
                    assert "--host" in call_args
                    host_index = call_args.index("--host")
                    assert call_args[host_index + 1] == "0.0.0.0"

    def test_cli_flag_overrides_environment_variable(
        self, runner, temp_fastapi_app, monkeypatch
    ):
        """Test that --port flag overrides FLASH_PORT environment variable."""
        monkeypatch.chdir(temp_fastapi_app)
        monkeypatch.setenv("FLASH_PORT", "8080")

        # Mock subprocess to capture command
        with patch("runpod_flash.cli.commands.run.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.wait.side_effect = KeyboardInterrupt()
            mock_popen.return_value = mock_process

            # Mock OS-level operations
            with patch("runpod_flash.cli.commands.run.os.getpgid") as mock_getpgid:
                mock_getpgid.return_value = 12345
                with patch("runpod_flash.cli.commands.run.os.killpg"):
                    # Use --port flag to override env var
                    runner.invoke(app, ["run", "--port", "9000"])

                    # Verify port 9000 was used (flag overrides env)
                    call_args = mock_popen.call_args[0][0]
                    assert "--port" in call_args
                    port_index = call_args.index("--port")
                    assert call_args[port_index + 1] == "9000"

    def test_default_port_when_no_env_or_flag(
        self, runner, temp_fastapi_app, monkeypatch
    ):
        """Test that default port 8888 is used when no env var or flag."""
        monkeypatch.chdir(temp_fastapi_app)
        # Ensure FLASH_PORT is not set
        monkeypatch.delenv("FLASH_PORT", raising=False)

        # Mock subprocess to capture command
        with patch("runpod_flash.cli.commands.run.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.wait.side_effect = KeyboardInterrupt()
            mock_popen.return_value = mock_process

            # Mock OS-level operations
            with patch("runpod_flash.cli.commands.run.os.getpgid") as mock_getpgid:
                mock_getpgid.return_value = 12345
                with patch("runpod_flash.cli.commands.run.os.killpg"):
                    runner.invoke(app, ["run"])

                    # Verify default port 8888 was used
                    call_args = mock_popen.call_args[0][0]
                    assert "--port" in call_args
                    port_index = call_args.index("--port")
                    assert call_args[port_index + 1] == "8888"

    def test_default_host_when_no_env_or_flag(
        self, runner, temp_fastapi_app, monkeypatch
    ):
        """Test that default host localhost is used when no env var or flag."""
        monkeypatch.chdir(temp_fastapi_app)
        # Ensure FLASH_HOST is not set
        monkeypatch.delenv("FLASH_HOST", raising=False)

        # Mock subprocess to capture command
        with patch("runpod_flash.cli.commands.run.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.wait.side_effect = KeyboardInterrupt()
            mock_popen.return_value = mock_process

            # Mock OS-level operations
            with patch("runpod_flash.cli.commands.run.os.getpgid") as mock_getpgid:
                mock_getpgid.return_value = 12345
                with patch("runpod_flash.cli.commands.run.os.killpg"):
                    runner.invoke(app, ["run"])

                    # Verify default host localhost was used
                    call_args = mock_popen.call_args[0][0]
                    assert "--host" in call_args
                    host_index = call_args.index("--host")
                    assert call_args[host_index + 1] == "localhost"

    def test_both_host_and_port_from_environment(
        self, runner, temp_fastapi_app, monkeypatch
    ):
        """Test that both FLASH_HOST and FLASH_PORT environment variables work together."""
        monkeypatch.chdir(temp_fastapi_app)
        monkeypatch.setenv("FLASH_HOST", "0.0.0.0")
        monkeypatch.setenv("FLASH_PORT", "3000")

        # Mock subprocess to capture command
        with patch("runpod_flash.cli.commands.run.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.wait.side_effect = KeyboardInterrupt()
            mock_popen.return_value = mock_process

            # Mock OS-level operations
            with patch("runpod_flash.cli.commands.run.os.getpgid") as mock_getpgid:
                mock_getpgid.return_value = 12345
                with patch("runpod_flash.cli.commands.run.os.killpg"):
                    runner.invoke(app, ["run"])

                    # Verify both host and port were used
                    call_args = mock_popen.call_args[0][0]

                    assert "--host" in call_args
                    host_index = call_args.index("--host")
                    assert call_args[host_index + 1] == "0.0.0.0"

                    assert "--port" in call_args
                    port_index = call_args.index("--port")
                    assert call_args[port_index + 1] == "3000"

    def test_short_port_flag_overrides_environment(
        self, runner, temp_fastapi_app, monkeypatch
    ):
        """Test that -p short flag also overrides FLASH_PORT environment variable."""
        monkeypatch.chdir(temp_fastapi_app)
        monkeypatch.setenv("FLASH_PORT", "8080")

        # Mock subprocess to capture command
        with patch("runpod_flash.cli.commands.run.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.wait.side_effect = KeyboardInterrupt()
            mock_popen.return_value = mock_process

            # Mock OS-level operations
            with patch("runpod_flash.cli.commands.run.os.getpgid") as mock_getpgid:
                mock_getpgid.return_value = 12345
                with patch("runpod_flash.cli.commands.run.os.killpg"):
                    # Use -p short flag
                    runner.invoke(app, ["run", "-p", "7000"])

                    # Verify port 7000 was used (short flag overrides env)
                    call_args = mock_popen.call_args[0][0]
                    assert "--port" in call_args
                    port_index = call_args.index("--port")
                    assert call_args[port_index + 1] == "7000"
