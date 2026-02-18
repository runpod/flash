"""Unit tests for run CLI command."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner

from runpod_flash.cli.main import app
from runpod_flash.cli.commands.run import WorkerInfo, _generate_flash_server


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

    @pytest.fixture(autouse=True)
    def patch_watcher(self):
        """Prevent the background watcher thread from blocking tests."""
        with patch("runpod_flash.cli.commands.run._watch_and_regenerate"):
            yield

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


class TestRunCommandHotReload:
    """Test flash run hot-reload behavior."""

    @pytest.fixture(autouse=True)
    def patch_watcher(self):
        """Prevent the background watcher thread from blocking tests."""
        with patch("runpod_flash.cli.commands.run._watch_and_regenerate"):
            yield

    def _invoke_run(self, runner, monkeypatch, temp_fastapi_app, extra_args=None):
        """Helper: invoke flash run and return the Popen call args."""
        monkeypatch.chdir(temp_fastapi_app)
        monkeypatch.delenv("FLASH_PORT", raising=False)
        monkeypatch.delenv("FLASH_HOST", raising=False)

        with patch("runpod_flash.cli.commands.run.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.wait.side_effect = KeyboardInterrupt()
            mock_popen.return_value = mock_process

            with patch("runpod_flash.cli.commands.run.os.getpgid", return_value=12345):
                with patch("runpod_flash.cli.commands.run.os.killpg"):
                    runner.invoke(app, ["run"] + (extra_args or []))

            return mock_popen.call_args[0][0]

    def test_reload_watches_flash_server_py(
        self, runner, temp_fastapi_app, monkeypatch
    ):
        """Uvicorn watches .flash/server.py, not the whole project."""
        cmd = self._invoke_run(runner, monkeypatch, temp_fastapi_app)

        assert "--reload" in cmd
        assert "--reload-dir" in cmd
        reload_dir_index = cmd.index("--reload-dir")
        assert cmd[reload_dir_index + 1] == ".flash"

        assert "--reload-include" in cmd
        reload_include_index = cmd.index("--reload-include")
        assert cmd[reload_include_index + 1] == "server.py"

    def test_reload_does_not_watch_project_root(
        self, runner, temp_fastapi_app, monkeypatch
    ):
        """Uvicorn reload-dir must not be '.' to prevent double-reload."""
        cmd = self._invoke_run(runner, monkeypatch, temp_fastapi_app)

        reload_dir_index = cmd.index("--reload-dir")
        assert cmd[reload_dir_index + 1] != "."

    def test_no_reload_skips_watcher_thread(
        self, runner, temp_fastapi_app, monkeypatch
    ):
        """--no-reload: neither uvicorn reload args nor watcher thread started."""
        monkeypatch.chdir(temp_fastapi_app)

        with patch("runpod_flash.cli.commands.run.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.wait.side_effect = KeyboardInterrupt()
            mock_popen.return_value = mock_process

            with patch("runpod_flash.cli.commands.run.os.getpgid", return_value=12345):
                with patch("runpod_flash.cli.commands.run.os.killpg"):
                    with patch(
                        "runpod_flash.cli.commands.run.threading.Thread"
                    ) as mock_thread_cls:
                        mock_thread = MagicMock()
                        mock_thread_cls.return_value = mock_thread

                        runner.invoke(app, ["run", "--no-reload"])

            cmd = mock_popen.call_args[0][0]
            assert "--reload" not in cmd
            mock_thread.start.assert_not_called()

    def test_watcher_thread_started_on_reload(
        self, runner, temp_fastapi_app, monkeypatch, patch_watcher
    ):
        """When reload=True, the background watcher thread is started."""
        monkeypatch.chdir(temp_fastapi_app)

        with patch("runpod_flash.cli.commands.run.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.wait.side_effect = KeyboardInterrupt()
            mock_popen.return_value = mock_process

            with patch("runpod_flash.cli.commands.run.os.getpgid", return_value=12345):
                with patch("runpod_flash.cli.commands.run.os.killpg"):
                    with patch(
                        "runpod_flash.cli.commands.run.threading.Thread"
                    ) as mock_thread_cls:
                        mock_thread = MagicMock()
                        mock_thread_cls.return_value = mock_thread

                        runner.invoke(app, ["run"])

            mock_thread.start.assert_called_once()

    def test_watcher_thread_stopped_on_keyboard_interrupt(
        self, runner, temp_fastapi_app, monkeypatch
    ):
        """KeyboardInterrupt sets stop_event and joins the watcher thread."""
        monkeypatch.chdir(temp_fastapi_app)

        with patch("runpod_flash.cli.commands.run.subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.wait.side_effect = KeyboardInterrupt()
            mock_popen.return_value = mock_process

            with patch("runpod_flash.cli.commands.run.os.getpgid", return_value=12345):
                with patch("runpod_flash.cli.commands.run.os.killpg"):
                    with patch(
                        "runpod_flash.cli.commands.run.threading.Thread"
                    ) as mock_thread_cls:
                        mock_thread = MagicMock()
                        mock_thread_cls.return_value = mock_thread
                        with patch(
                            "runpod_flash.cli.commands.run.threading.Event"
                        ) as mock_event_cls:
                            mock_stop = MagicMock()
                            mock_event_cls.return_value = mock_stop

                            runner.invoke(app, ["run"])

            mock_stop.set.assert_called_once()
            mock_thread.join.assert_called_once_with(timeout=2)


class TestWatchAndRegenerate:
    """Unit tests for the _watch_and_regenerate background function."""

    def test_regenerates_server_py_on_py_file_change(self, tmp_path):
        """When a .py file changes, server.py is regenerated."""
        import threading
        from runpod_flash.cli.commands.run import _watch_and_regenerate

        stop = threading.Event()

        with patch(
            "runpod_flash.cli.commands.run._scan_project_workers", return_value=[]
        ) as mock_scan:
            with patch(
                "runpod_flash.cli.commands.run._generate_flash_server"
            ) as mock_gen:
                with patch(
                    "runpod_flash.cli.commands.run._watchfiles_watch"
                ) as mock_watch:
                    # Yield one batch of changes then stop
                    mock_watch.return_value = iter([{(1, "/path/to/worker.py")}])
                    stop.set()  # ensures the loop exits after one iteration
                    _watch_and_regenerate(tmp_path, stop)

        mock_scan.assert_called_once_with(tmp_path)
        mock_gen.assert_called_once()

    def test_ignores_non_py_changes(self, tmp_path):
        """Changes to non-.py files do not trigger regeneration."""
        import threading
        from runpod_flash.cli.commands.run import _watch_and_regenerate

        stop = threading.Event()

        with patch("runpod_flash.cli.commands.run._scan_project_workers") as mock_scan:
            with patch(
                "runpod_flash.cli.commands.run._generate_flash_server"
            ) as mock_gen:
                with patch(
                    "runpod_flash.cli.commands.run._watchfiles_watch"
                ) as mock_watch:
                    mock_watch.return_value = iter([{(1, "/path/to/README.md")}])
                    _watch_and_regenerate(tmp_path, stop)

        mock_scan.assert_not_called()
        mock_gen.assert_not_called()

    def test_scan_error_does_not_crash_watcher(self, tmp_path):
        """If regeneration raises, the watcher logs a warning and continues."""
        import threading
        from runpod_flash.cli.commands.run import _watch_and_regenerate

        stop = threading.Event()

        with patch(
            "runpod_flash.cli.commands.run._scan_project_workers",
            side_effect=RuntimeError("scan failed"),
        ):
            with patch("runpod_flash.cli.commands.run._watchfiles_watch") as mock_watch:
                mock_watch.return_value = iter([{(1, "/path/to/worker.py")}])
                # Should not raise
                _watch_and_regenerate(tmp_path, stop)


class TestGenerateFlashServer:
    """Test _generate_flash_server() route code generation."""

    def _make_lb_worker(self, tmp_path: Path, method: str) -> WorkerInfo:
        return WorkerInfo(
            file_path=tmp_path / "api.py",
            url_prefix="/api",
            module_path="api",
            resource_name="api",
            worker_type="LB",
            functions=["list_routes"],
            lb_routes=[
                {"method": method, "path": "/routes/list", "fn_name": "list_routes"}
            ],
        )

    def test_get_route_has_no_body_param(self, tmp_path):
        """GET handler must omit body: dict to satisfy FastAPI/browser constraints."""
        worker = self._make_lb_worker(tmp_path, "GET")
        server_path = _generate_flash_server(tmp_path, [worker])
        content = server_path.read_text()

        # The GET handler must be zero-arg
        assert "async def _route_api_list_routes():" in content
        # No body parameter on any GET handler
        assert "body: dict" not in content

    def test_post_route_keeps_body_param(self, tmp_path):
        """POST handler must include body: dict for JSON request body."""
        worker = self._make_lb_worker(tmp_path, "POST")
        server_path = _generate_flash_server(tmp_path, [worker])
        content = server_path.read_text()

        assert "async def _route_api_list_routes(body: dict):" in content
