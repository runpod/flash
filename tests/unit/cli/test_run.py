"""Unit tests for run CLI command."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner

from runpod_flash.cli.main import app
from runpod_flash.cli.commands.run import (
    WorkerInfo,
    _generate_flash_server,
    _has_numeric_module_segments,
    _make_import_line,
    _module_parent_subdir,
    _sanitize_fn_name,
)


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

    def _make_lb_worker(self, tmp_path: Path, method: str = "GET") -> WorkerInfo:
        return WorkerInfo(
            file_path=tmp_path / "api.py",
            url_prefix="/api",
            module_path="api",
            resource_name="api",
            worker_type="LB",
            functions=["list_routes"],
            lb_routes=[
                {
                    "method": method,
                    "path": "/routes/list",
                    "fn_name": "list_routes",
                    "config_variable": "api_config",
                }
            ],
        )

    def test_post_lb_route_generates_body_param(self, tmp_path):
        """POST/PUT/PATCH/DELETE LB routes use body: dict for OpenAPI docs."""
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            worker = self._make_lb_worker(tmp_path, method)
            content = _generate_flash_server(tmp_path, [worker]).read_text()
            assert "async def _route_api_list_routes(body: dict):" in content
            assert "_lb_execute(api_config, list_routes, body)" in content

    def test_get_lb_route_uses_query_params(self, tmp_path):
        """GET LB routes pass query params as a dict."""
        worker = self._make_lb_worker(tmp_path, "GET")
        content = _generate_flash_server(tmp_path, [worker]).read_text()
        assert "async def _route_api_list_routes(request: Request):" in content
        assert (
            "_lb_execute(api_config, list_routes, dict(request.query_params))"
            in content
        )

    def test_lb_config_var_and_function_imported(self, tmp_path):
        """LB config vars and functions are both imported for remote dispatch."""
        worker = self._make_lb_worker(tmp_path)
        content = _generate_flash_server(tmp_path, [worker]).read_text()
        assert "from api import api_config" in content
        assert "from api import list_routes" in content

    def test_lb_execute_import_present_when_lb_routes_exist(self, tmp_path):
        """server.py imports _lb_execute when there are LB workers."""
        worker = self._make_lb_worker(tmp_path)
        content = _generate_flash_server(tmp_path, [worker]).read_text()
        assert "_lb_execute" in content
        assert "lb_execute" in content

    def test_qb_function_still_imported_directly(self, tmp_path):
        """QB workers still import and call functions directly."""
        worker = WorkerInfo(
            file_path=tmp_path / "worker.py",
            url_prefix="/worker",
            module_path="worker",
            resource_name="worker",
            worker_type="QB",
            functions=["process"],
        )
        content = _generate_flash_server(tmp_path, [worker]).read_text()
        assert "from worker import process" in content
        assert "await process(" in content


class TestSanitizeFnName:
    """Test _sanitize_fn_name handles leading-digit identifiers."""

    def test_normal_name_unchanged(self):
        assert _sanitize_fn_name("worker_run_sync") == "worker_run_sync"

    def test_leading_digit_gets_underscore_prefix(self):
        assert _sanitize_fn_name("01_hello_run_sync") == "_01_hello_run_sync"

    def test_slashes_replaced(self):
        assert _sanitize_fn_name("a/b/c") == "a_b_c"

    def test_dots_and_hyphens_replaced(self):
        assert _sanitize_fn_name("a.b-c") == "a_b_c"

    def test_numeric_after_slash(self):
        assert _sanitize_fn_name("01_foo/02_bar") == "_01_foo_02_bar"


class TestHasNumericModuleSegments:
    """Test _has_numeric_module_segments detects digit-prefixed segments."""

    def test_normal_module_path(self):
        assert _has_numeric_module_segments("worker") is False

    def test_dotted_normal(self):
        assert _has_numeric_module_segments("longruns.stage1") is False

    def test_leading_digit_first_segment(self):
        assert _has_numeric_module_segments("01_hello.worker") is True

    def test_leading_digit_nested_segment(self):
        assert _has_numeric_module_segments("getting_started.01_hello.worker") is True

    def test_digit_in_middle_not_leading(self):
        assert _has_numeric_module_segments("stage1.worker") is False


class TestModuleParentSubdir:
    """Test _module_parent_subdir extracts parent directory from dotted path."""

    def test_top_level_returns_none(self):
        assert _module_parent_subdir("worker") is None

    def test_single_parent(self):
        assert _module_parent_subdir("01_hello.gpu_worker") == "01_hello"

    def test_nested_parent(self):
        assert (
            _module_parent_subdir("01_getting_started.03_mixed.pipeline")
            == "01_getting_started/03_mixed"
        )


class TestMakeImportLine:
    """Test _make_import_line generates correct import syntax."""

    def test_normal_module_uses_from_import(self):
        result = _make_import_line("worker", "process")
        assert result == "from worker import process"

    def test_numeric_module_uses_flash_import(self):
        result = _make_import_line("01_hello.gpu_worker", "gpu_hello")
        assert (
            result
            == 'gpu_hello = _flash_import("01_hello.gpu_worker", "gpu_hello", "01_hello")'
        )

    def test_nested_numeric_includes_full_subdir(self):
        result = _make_import_line(
            "01_getting_started.01_hello.gpu_worker", "gpu_hello"
        )
        assert '"01_getting_started/01_hello"' in result

    def test_top_level_numeric_module_no_subdir(self):
        result = _make_import_line("01_worker", "process")
        assert result == 'process = _flash_import("01_worker", "process")'


class TestGenerateFlashServerNumericDirs:
    """Test _generate_flash_server with numeric-prefixed directory names."""

    def test_qb_numeric_dir_uses_flash_import(self, tmp_path):
        """QB workers in numeric dirs use _flash_import with scoped sys.path."""
        worker = WorkerInfo(
            file_path=tmp_path / "01_hello" / "gpu_worker.py",
            url_prefix="/01_hello/gpu_worker",
            module_path="01_hello.gpu_worker",
            resource_name="01_hello_gpu_worker",
            worker_type="QB",
            functions=["gpu_hello"],
        )
        content = _generate_flash_server(tmp_path, [worker]).read_text()

        # Must NOT contain invalid 'from 01_hello...' import
        assert "from 01_hello" not in content
        # Must have _flash_import helper and importlib
        assert "import importlib as _importlib" in content
        assert "def _flash_import(" in content
        assert (
            '_flash_import("01_hello.gpu_worker", "gpu_hello", "01_hello")' in content
        )

    def test_qb_numeric_dir_function_name_prefixed(self, tmp_path):
        """QB handler function names starting with digits get '_' prefix."""
        worker = WorkerInfo(
            file_path=tmp_path / "01_hello" / "gpu_worker.py",
            url_prefix="/01_hello/gpu_worker",
            module_path="01_hello.gpu_worker",
            resource_name="01_hello_gpu_worker",
            worker_type="QB",
            functions=["gpu_hello"],
        )
        content = _generate_flash_server(tmp_path, [worker]).read_text()

        # Function name must start with '_', not a digit
        assert "async def _01_hello_gpu_worker_run_sync(body: dict):" in content

    def test_lb_numeric_dir_uses_flash_import(self, tmp_path):
        """LB workers in numeric dirs use _flash_import for config and function imports."""
        worker = WorkerInfo(
            file_path=tmp_path / "03_advanced" / "05_lb" / "cpu_lb.py",
            url_prefix="/03_advanced/05_lb/cpu_lb",
            module_path="03_advanced.05_lb.cpu_lb",
            resource_name="03_advanced_05_lb_cpu_lb",
            worker_type="LB",
            functions=["validate_data"],
            lb_routes=[
                {
                    "method": "POST",
                    "path": "/validate",
                    "fn_name": "validate_data",
                    "config_variable": "cpu_config",
                }
            ],
        )
        content = _generate_flash_server(tmp_path, [worker]).read_text()

        assert "from 03_advanced" not in content
        assert (
            '_flash_import("03_advanced.05_lb.cpu_lb", "cpu_config", "03_advanced/05_lb")'
            in content
        )
        assert (
            '_flash_import("03_advanced.05_lb.cpu_lb", "validate_data", "03_advanced/05_lb")'
            in content
        )

    def test_mixed_numeric_and_normal_dirs(self, tmp_path):
        """Normal modules use 'from' imports, numeric modules use _flash_import."""
        normal_worker = WorkerInfo(
            file_path=tmp_path / "worker.py",
            url_prefix="/worker",
            module_path="worker",
            resource_name="worker",
            worker_type="QB",
            functions=["process"],
        )
        numeric_worker = WorkerInfo(
            file_path=tmp_path / "01_hello" / "gpu_worker.py",
            url_prefix="/01_hello/gpu_worker",
            module_path="01_hello.gpu_worker",
            resource_name="01_hello_gpu_worker",
            worker_type="QB",
            functions=["gpu_hello"],
        )
        content = _generate_flash_server(
            tmp_path, [normal_worker, numeric_worker]
        ).read_text()

        # Normal worker uses standard import
        assert "from worker import process" in content
        # Numeric worker uses scoped _flash_import
        assert (
            '_flash_import("01_hello.gpu_worker", "gpu_hello", "01_hello")' in content
        )

    def test_no_importlib_when_all_normal_dirs(self, tmp_path):
        """importlib and _flash_import are not emitted when no numeric dirs exist."""
        worker = WorkerInfo(
            file_path=tmp_path / "worker.py",
            url_prefix="/worker",
            module_path="worker",
            resource_name="worker",
            worker_type="QB",
            functions=["process"],
        )
        content = _generate_flash_server(tmp_path, [worker]).read_text()
        assert "importlib" not in content
        assert "_flash_import" not in content

    def test_scoped_import_includes_subdir(self, tmp_path):
        """_flash_import calls pass the subdirectory for sibling import scoping."""
        worker = WorkerInfo(
            file_path=tmp_path / "01_getting_started" / "03_mixed" / "pipeline.py",
            url_prefix="/01_getting_started/03_mixed/pipeline",
            module_path="01_getting_started.03_mixed.pipeline",
            resource_name="01_getting_started_03_mixed_pipeline",
            worker_type="LB",
            functions=["classify"],
            lb_routes=[
                {
                    "method": "POST",
                    "path": "/classify",
                    "fn_name": "classify",
                    "config_variable": "pipeline_config",
                }
            ],
        )
        content = _generate_flash_server(tmp_path, [worker]).read_text()

        # Must scope to correct subdirectory, not add all dirs to sys.path
        assert '"01_getting_started/03_mixed"' in content
        # No global sys.path additions for subdirs — only the project root
        # line at the top and the one inside _flash_import helper body
        lines = content.split("\n")
        global_sys_path_lines = [
            line
            for line in lines
            if "sys.path.insert" in line and not line.startswith(" ")
        ]
        assert len(global_sys_path_lines) == 1

    def test_generated_server_is_valid_python(self, tmp_path):
        """Generated server.py with numeric dirs must be parseable Python."""
        worker = WorkerInfo(
            file_path=tmp_path / "01_getting_started" / "01_hello" / "gpu_worker.py",
            url_prefix="/01_getting_started/01_hello/gpu_worker",
            module_path="01_getting_started.01_hello.gpu_worker",
            resource_name="01_getting_started_01_hello_gpu_worker",
            worker_type="QB",
            functions=["gpu_hello"],
        )
        server_path = _generate_flash_server(tmp_path, [worker])
        content = server_path.read_text()

        # Must parse without SyntaxError
        import ast

        ast.parse(content)


class TestMapBodyToParams:
    """Tests for _map_body_to_params — maps HTTP body to function arguments."""

    def test_body_keys_match_params_spreads_as_kwargs(self):
        from runpod_flash.cli.commands._run_server_helpers import _map_body_to_params

        def process(name: str, value: int):
            pass

        result = _map_body_to_params(process, {"name": "test", "value": 42})
        assert result == {"name": "test", "value": 42}

    def test_body_keys_mismatch_wraps_in_first_param(self):
        from runpod_flash.cli.commands._run_server_helpers import _map_body_to_params

        def run_pipeline(input_data: dict):
            pass

        body = {"text": "hello", "mode": "fast"}
        result = _map_body_to_params(run_pipeline, body)
        assert result == {"input_data": {"text": "hello", "mode": "fast"}}

    def test_non_dict_body_wraps_in_first_param(self):
        from runpod_flash.cli.commands._run_server_helpers import _map_body_to_params

        def run_pipeline(input_data):
            pass

        result = _map_body_to_params(run_pipeline, [1, 2, 3])
        assert result == {"input_data": [1, 2, 3]}

    def test_no_params_returns_empty(self):
        from runpod_flash.cli.commands._run_server_helpers import _map_body_to_params

        def no_args():
            pass

        result = _map_body_to_params(no_args, {"key": "val"})
        assert result == {}

    def test_partial_key_match_wraps_in_first_param(self):
        from runpod_flash.cli.commands._run_server_helpers import _map_body_to_params

        def process(name: str, value: int):
            pass

        result = _map_body_to_params(process, {"name": "test", "extra": "bad"})
        assert result == {"name": {"name": "test", "extra": "bad"}}

    def test_empty_dict_body_spreads_as_empty_kwargs(self):
        from runpod_flash.cli.commands._run_server_helpers import _map_body_to_params

        def run_pipeline(input_data: dict):
            pass

        result = _map_body_to_params(run_pipeline, {})
        assert result == {}
