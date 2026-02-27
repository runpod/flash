"""P2 remaining gap tests – second batch.

Covers:
  CLI-BUILD-006/007  pip fallback chain (pip -> ensurepip -> uv pip)
  CLI-BUILD-011      cleanup_python_bytecode removes __pycache__ and .pyc
  CLI-BUILD-018      install_dependencies with empty requirements list
  CLI-DEPLOY-008     preview _parse_resources_from_manifest structure
  CLI-ENV-006        delete_command bubbles error when env fetch fails
  CLI-UNDEPLOY-001   list_command uses ResourceManager.list_all_resources()
  SRVGEN-017         file_to_url_prefix includes directory path (no collision)
  BUILD-015          RemoteDecoratorScanner returns empty list for no @remote
  FILE-005           _build_file_upload_wrapper handles multiple bytes params
  LOG-003            JobOutput.model_post_init logs delayTime and executionTime
"""

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_subprocess_result(
    returncode: int, stdout: str = "", stderr: str = ""
) -> MagicMock:
    """Build a mock CompletedProcess-like object."""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


# ---------------------------------------------------------------------------
# CLI-BUILD-006/007: pip fallback chain
# ---------------------------------------------------------------------------


class TestInstallDependenciesFallbackChain:
    """install_dependencies tries standard pip, then ensurepip, then uv pip."""

    def test_standard_pip_available_uses_pip(self, tmp_path):
        """CLI-BUILD-006: when standard pip --version succeeds, pip install is used."""
        from runpod_flash.cli.commands.build import install_dependencies

        pip_version_ok = _make_subprocess_result(0, "pip 23.0")
        install_ok = _make_subprocess_result(0)

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [pip_version_ok, install_ok]
            result = install_dependencies(tmp_path, ["requests"], no_deps=False)

        assert result is True
        # install call must use sys.executable -m pip (not uv)
        install_call_args = mock_run.call_args_list[-1][0][0]
        assert sys.executable in install_call_args
        assert "pip" in install_call_args

    def test_pip_unavailable_triggers_ensurepip(self, tmp_path):
        """CLI-BUILD-006: when pip --version fails, ensurepip is invoked."""
        from runpod_flash.cli.commands.build import install_dependencies

        pip_version_fail = _make_subprocess_result(1)
        ensurepip_ok = _make_subprocess_result(0)
        pip_version_ok_after = _make_subprocess_result(0, "pip 23.0")
        install_ok = _make_subprocess_result(0)

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                pip_version_fail,  # initial pip --version -> fail
                ensurepip_ok,  # ensurepip --upgrade -> ok
                pip_version_ok_after,  # verify pip after ensurepip -> ok
                install_ok,  # actual pip install -> ok
            ]
            result = install_dependencies(tmp_path, ["numpy"], no_deps=False)

        assert result is True
        # Verify ensurepip was called
        ensurepip_call = mock_run.call_args_list[1][0][0]
        assert "ensurepip" in ensurepip_call

    def test_pip_and_ensurepip_fail_falls_back_to_uv(self, tmp_path):
        """CLI-BUILD-007: when pip and ensurepip both fail, uv pip is tried."""
        from runpod_flash.cli.commands.build import install_dependencies, UV_COMMAND

        pip_version_fail = _make_subprocess_result(1)
        ensurepip_fail = _make_subprocess_result(1)
        uv_version_ok = _make_subprocess_result(0, "uv pip 0.4")
        install_ok = _make_subprocess_result(0)

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                pip_version_fail,  # pip --version -> fail
                ensurepip_fail,  # ensurepip -> fail
                uv_version_ok,  # uv pip --version -> ok
                install_ok,  # uv pip install -> ok
            ]
            result = install_dependencies(tmp_path, ["torch"], no_deps=False)

        assert result is True
        # Last install call must use the uv command
        install_call_args = mock_run.call_args_list[-1][0][0]
        assert UV_COMMAND in install_call_args

    def test_all_pip_methods_fail_returns_false(self, tmp_path):
        """CLI-BUILD-007: when pip, ensurepip, and uv all fail, returns False."""
        from runpod_flash.cli.commands.build import install_dependencies

        fail = _make_subprocess_result(1)

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                fail,  # pip --version -> fail
                fail,  # ensurepip -> fail
                fail,  # uv pip --version -> fail
            ]
            result = install_dependencies(tmp_path, ["scipy"], no_deps=False)

        assert result is False

    def test_pip_install_uses_no_deps_flag(self, tmp_path):
        """CLI-BUILD-006: no_deps=True appends --no-deps to the install command."""
        from runpod_flash.cli.commands.build import install_dependencies

        pip_version_ok = _make_subprocess_result(0, "pip 23.0")
        install_ok = _make_subprocess_result(0)

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [pip_version_ok, install_ok]
            install_dependencies(tmp_path, ["requests"], no_deps=True)

        install_call_args = mock_run.call_args_list[-1][0][0]
        assert "--no-deps" in install_call_args


# ---------------------------------------------------------------------------
# CLI-BUILD-011: cleanup_python_bytecode
# ---------------------------------------------------------------------------


class TestCleanupPythonBytecode:
    """cleanup_python_bytecode removes __pycache__ dirs and .pyc/.pyo/.pyd files."""

    def test_removes_pycache_directory(self, tmp_path):
        """CLI-BUILD-011: __pycache__ directories are deleted."""
        from runpod_flash.cli.commands.build import cleanup_python_bytecode

        pycache = tmp_path / "subpkg" / "__pycache__"
        pycache.mkdir(parents=True)
        (pycache / "module.cpython-311.pyc").write_bytes(b"\x00")

        cleanup_python_bytecode(tmp_path)

        assert not pycache.exists()

    def test_removes_stray_pyc_files(self, tmp_path):
        """CLI-BUILD-011: .pyc files outside __pycache__ are also removed."""
        from runpod_flash.cli.commands.build import cleanup_python_bytecode

        pyc_file = tmp_path / "workers" / "handler.pyc"
        pyc_file.parent.mkdir(parents=True)
        pyc_file.write_bytes(b"\x00")

        cleanup_python_bytecode(tmp_path)

        assert not pyc_file.exists()

    def test_removes_pyo_and_pyd_files(self, tmp_path):
        """CLI-BUILD-011: .pyo and .pyd files are also removed."""
        from runpod_flash.cli.commands.build import cleanup_python_bytecode

        pyo = tmp_path / "helper.pyo"
        pyd = tmp_path / "extension.pyd"
        pyo.write_bytes(b"\x00")
        pyd.write_bytes(b"\x00")

        cleanup_python_bytecode(tmp_path)

        assert not pyo.exists()
        assert not pyd.exists()

    def test_preserves_py_source_files(self, tmp_path):
        """CLI-BUILD-011: .py source files are not removed."""
        from runpod_flash.cli.commands.build import cleanup_python_bytecode

        src = tmp_path / "worker.py"
        src.write_text("print('hello')")

        cleanup_python_bytecode(tmp_path)

        assert src.exists()

    def test_handles_empty_directory(self, tmp_path):
        """CLI-BUILD-011: empty build directory does not raise."""
        from runpod_flash.cli.commands.build import cleanup_python_bytecode

        cleanup_python_bytecode(tmp_path)  # should not raise

    def test_removes_nested_pycache(self, tmp_path):
        """CLI-BUILD-011: __pycache__ nested several levels deep is removed."""
        from runpod_flash.cli.commands.build import cleanup_python_bytecode

        nested = tmp_path / "a" / "b" / "c" / "__pycache__"
        nested.mkdir(parents=True)
        (nested / "deep.pyc").write_bytes(b"\x00")

        cleanup_python_bytecode(tmp_path)

        assert not nested.exists()


# ---------------------------------------------------------------------------
# CLI-BUILD-018: install_dependencies with no requirements
# ---------------------------------------------------------------------------


class TestInstallDependenciesNoDeps:
    """install_dependencies returns True immediately when requirements list is empty."""

    def test_empty_requirements_returns_true_without_subprocess(self, tmp_path):
        """CLI-BUILD-018: empty requirements list -> success, no subprocess calls."""
        from runpod_flash.cli.commands.build import install_dependencies

        with patch("subprocess.run") as mock_run:
            result = install_dependencies(tmp_path, [], no_deps=False)

        assert result is True
        mock_run.assert_not_called()

    def test_empty_requirements_with_no_deps_flag_also_succeeds(self, tmp_path):
        """CLI-BUILD-018: empty requirements + no_deps=True -> still True."""
        from runpod_flash.cli.commands.build import install_dependencies

        with patch("subprocess.run") as mock_run:
            result = install_dependencies(tmp_path, [], no_deps=True)

        assert result is True
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# CLI-DEPLOY-008: preview _parse_resources_from_manifest
# ---------------------------------------------------------------------------


class TestParseResourcesFromManifest:
    """_parse_resources_from_manifest produces valid resource config dict."""

    def test_parses_non_lb_resource_from_manifest(self):
        """CLI-DEPLOY-008: non-LB resource is parsed with is_load_balanced=False."""
        from runpod_flash.cli.commands.preview import _parse_resources_from_manifest

        manifest = {
            "resources": {
                "gpu_worker": {
                    "is_load_balanced": False,
                    "imageName": "runpod/flash-worker:latest",
                    "functions": ["generate"],
                }
            }
        }

        resources = _parse_resources_from_manifest(manifest)

        assert "gpu_worker" in resources
        assert resources["gpu_worker"]["is_load_balanced"] is False
        assert resources["gpu_worker"]["imageName"] == "runpod/flash-worker:latest"
        assert "generate" in resources["gpu_worker"]["functions"]

    def test_parses_lb_resource_from_manifest(self):
        """CLI-DEPLOY-008: LB resource is parsed with is_load_balanced=True."""
        from runpod_flash.cli.commands.preview import _parse_resources_from_manifest

        manifest = {
            "resources": {
                "my_lb": {
                    "is_load_balanced": True,
                    "imageName": "runpod/flash-lb:latest",
                    "functions": [],
                }
            }
        }

        resources = _parse_resources_from_manifest(manifest)

        assert resources["my_lb"]["is_load_balanced"] is True

    def test_injects_default_lb_when_none_present(self):
        """CLI-DEPLOY-008: fallback load_balancer resource is added when no LB in manifest."""
        from runpod_flash.cli.commands.preview import _parse_resources_from_manifest

        manifest = {
            "resources": {
                "cpu_worker": {
                    "is_load_balanced": False,
                    "imageName": "runpod/flash-cpu:latest",
                }
            }
        }

        resources = _parse_resources_from_manifest(manifest)

        # Must inject a default load_balancer
        assert "load_balancer" in resources
        assert resources["load_balancer"]["is_load_balanced"] is True

    def test_no_fallback_lb_when_lb_already_present(self):
        """CLI-DEPLOY-008: no duplicate load_balancer injected when one already exists."""
        from runpod_flash.cli.commands.preview import _parse_resources_from_manifest

        manifest = {
            "resources": {
                "my_lb": {
                    "is_load_balanced": True,
                    "imageName": "runpod/flash-lb:latest",
                }
            }
        }

        resources = _parse_resources_from_manifest(manifest)

        # Should not have a second load_balancer entry
        assert "load_balancer" not in resources

    def test_empty_manifest_returns_fallback_lb(self):
        """CLI-DEPLOY-008: completely empty manifest still produces a load_balancer entry."""
        from runpod_flash.cli.commands.preview import _parse_resources_from_manifest

        resources = _parse_resources_from_manifest({})

        assert "load_balancer" in resources
        assert resources["load_balancer"]["is_load_balanced"] is True


# ---------------------------------------------------------------------------
# CLI-ENV-006: delete_command bubbles error when env fetch fails
# ---------------------------------------------------------------------------


class TestEnvDeleteCommandError:
    """delete_command exits with code 1 when environment fetch raises."""

    def test_delete_nonexistent_env_exits_with_error(self):
        """CLI-ENV-006: exception during fetch prints error and raises Exit(1)."""
        import typer
        from runpod_flash.cli.commands.env import delete_command

        with patch(
            "runpod_flash.cli.commands.env._fetch_environment_info",
            side_effect=Exception("env 'staging' not found"),
        ):
            with patch(
                "runpod_flash.cli.commands.env.discover_flash_project",
                return_value=(Path("/fake/project"), "my-app"),
            ):
                with pytest.raises(typer.Exit) as exc_info:
                    delete_command(env_name="staging", app_name="my-app")

        assert exc_info.value.exit_code == 1

    def test_delete_prints_error_message(self, capsys):
        """CLI-ENV-006: error message mentions the failure when env not found."""
        import typer
        from runpod_flash.cli.commands.env import delete_command

        error_msg = "environment 'does-not-exist' not found"
        with patch(
            "runpod_flash.cli.commands.env._fetch_environment_info",
            side_effect=Exception(error_msg),
        ):
            with pytest.raises(typer.Exit):
                delete_command(env_name="does-not-exist", app_name="my-app")

        # Rich console outputs to stderr by default; check combined output
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "Failed to fetch environment info" in combined or error_msg in combined


# ---------------------------------------------------------------------------
# CLI-UNDEPLOY-001: list_command uses list_all_resources
# ---------------------------------------------------------------------------


class TestUndeployListCommand:
    """undeploy list_command calls ResourceManager.list_all_resources()."""

    def test_list_command_calls_list_all_resources(self):
        """CLI-UNDEPLOY-001: list_command calls manager.list_all_resources()."""
        from runpod_flash.cli.commands.undeploy import list_command

        mock_manager = MagicMock()
        mock_manager.list_all_resources.return_value = {}

        with patch(
            "runpod_flash.cli.commands.undeploy._get_resource_manager",
            return_value=mock_manager,
        ):
            list_command()

        mock_manager.list_all_resources.assert_called_once()

    def test_list_command_prints_no_endpoints_when_empty(self, capsys):
        """CLI-UNDEPLOY-001: empty resource dict prints 'No endpoints found.'."""
        from runpod_flash.cli.commands.undeploy import list_command

        mock_manager = MagicMock()
        mock_manager.list_all_resources.return_value = {}

        with patch(
            "runpod_flash.cli.commands.undeploy._get_resource_manager",
            return_value=mock_manager,
        ):
            list_command()

        captured = capsys.readouterr()
        assert "No endpoints found" in captured.out

    def test_list_command_shows_tracked_resources(self, capsys):
        """CLI-UNDEPLOY-001: tracked serverless resources are printed by list_command."""
        from runpod_flash.cli.commands.undeploy import list_command
        from runpod_flash.core.resources.serverless import ServerlessResource

        # Build a minimal ServerlessResource-like mock
        mock_resource = MagicMock(spec=ServerlessResource)
        mock_resource.name = "my-worker"
        mock_resource.id = "ep-abc123"
        mock_resource.is_deployed.return_value = True

        mock_manager = MagicMock()
        mock_manager.list_all_resources.return_value = {
            "ServerlessResource:my-worker": mock_resource
        }

        with patch(
            "runpod_flash.cli.commands.undeploy._get_resource_manager",
            return_value=mock_manager,
        ):
            list_command()

        captured = capsys.readouterr()
        assert "my-worker" in captured.out


# ---------------------------------------------------------------------------
# SRVGEN-017: file_to_url_prefix includes directory path (no route collision)
# ---------------------------------------------------------------------------


class TestFileToUrlPrefix:
    """file_to_url_prefix embeds the full directory path, preventing collisions."""

    def test_top_level_file_prefix(self, tmp_path):
        """SRVGEN-017: top-level worker.py -> /worker."""
        from runpod_flash.cli.commands.build_utils.scanner import file_to_url_prefix

        py_file = tmp_path / "worker.py"
        prefix = file_to_url_prefix(py_file, tmp_path)
        assert prefix == "/worker"

    def test_nested_file_includes_directory(self, tmp_path):
        """SRVGEN-017: longruns/stage1.py -> /longruns/stage1."""
        from runpod_flash.cli.commands.build_utils.scanner import file_to_url_prefix

        py_file = tmp_path / "longruns" / "stage1.py"
        prefix = file_to_url_prefix(py_file, tmp_path)
        assert prefix == "/longruns/stage1"

    def test_same_filename_different_dirs_gives_unique_prefixes(self, tmp_path):
        """SRVGEN-017: two worker.py files in different dirs get different prefixes."""
        from runpod_flash.cli.commands.build_utils.scanner import file_to_url_prefix

        file_a = tmp_path / "moduleA" / "worker.py"
        file_b = tmp_path / "moduleB" / "worker.py"

        prefix_a = file_to_url_prefix(file_a, tmp_path)
        prefix_b = file_to_url_prefix(file_b, tmp_path)

        assert prefix_a != prefix_b
        assert prefix_a == "/moduleA/worker"
        assert prefix_b == "/moduleB/worker"

    def test_prefix_starts_with_slash(self, tmp_path):
        """SRVGEN-017: returned prefix always starts with /."""
        from runpod_flash.cli.commands.build_utils.scanner import file_to_url_prefix

        py_file = tmp_path / "anything.py"
        prefix = file_to_url_prefix(py_file, tmp_path)
        assert prefix.startswith("/")


# ---------------------------------------------------------------------------
# BUILD-015: Scanner returns empty list when no @remote functions
# ---------------------------------------------------------------------------


class TestScannerEmptyProject:
    """RemoteDecoratorScanner handles projects with no @remote functions."""

    def test_empty_project_directory_returns_empty_list(self, tmp_path):
        """BUILD-015: project with no Python files returns empty list."""
        from runpod_flash.cli.commands.build_utils.scanner import RemoteDecoratorScanner

        scanner = RemoteDecoratorScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert functions == []

    def test_py_files_with_no_remote_decorator(self, tmp_path):
        """BUILD-015: .py files without @remote return empty list."""
        from runpod_flash.cli.commands.build_utils.scanner import RemoteDecoratorScanner

        (tmp_path / "worker.py").write_text(
            "def compute(x):\n    return x * 2\n",
            encoding="utf-8",
        )
        (tmp_path / "utils.py").write_text(
            "CONSTANT = 42\n",
            encoding="utf-8",
        )

        scanner = RemoteDecoratorScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert functions == []

    def test_scanner_with_syntax_error_file_does_not_raise(self, tmp_path):
        """BUILD-015: a file with a syntax error is skipped gracefully."""
        from runpod_flash.cli.commands.build_utils.scanner import RemoteDecoratorScanner

        (tmp_path / "broken.py").write_text(
            "def foo(\n",  # unclosed parenthesis -> SyntaxError
            encoding="utf-8",
        )

        scanner = RemoteDecoratorScanner(tmp_path)
        # Should not raise; broken file is silently skipped
        functions = scanner.discover_remote_functions()
        assert functions == []

    def test_scanner_finds_remote_in_non_empty_project(self, tmp_path):
        """BUILD-015: contrast test – scanner finds @remote when present."""
        from runpod_flash.cli.commands.build_utils.scanner import RemoteDecoratorScanner

        (tmp_path / "worker.py").write_text(
            "from runpod_flash import remote, LiveServerless\n"
            'cfg = LiveServerless(name="my-ep")\n'
            "@remote(cfg)\n"
            "def process(x):\n"
            "    return x\n",
            encoding="utf-8",
        )

        scanner = RemoteDecoratorScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert len(functions) == 1
        assert functions[0].function_name == "process"


# ---------------------------------------------------------------------------
# FILE-005: _build_file_upload_wrapper handles multiple bytes params
# ---------------------------------------------------------------------------


class TestBuildFileUploadWrapperMultipleFiles:
    """_build_file_upload_wrapper correctly handles handlers with multiple bytes params."""

    def test_multiple_bytes_params_become_file_params(self):
        """FILE-005: handler with two bytes params gets two File() annotations."""
        from runpod_flash.runtime.lb_handler import _build_file_upload_wrapper
        import inspect

        def handler(image: bytes, mask: bytes):
            return len(image) + len(mask)

        sig = inspect.signature(handler)
        hints = {"image": bytes, "mask": bytes}

        file_params = [
            ("image", bytes, inspect.Parameter.empty),
            ("mask", bytes, inspect.Parameter.empty),
        ]
        form_params: list = []
        path_params: set = set()

        wrapper = _build_file_upload_wrapper(
            handler, file_params, form_params, path_params, hints, sig
        )

        wrapped_sig = inspect.signature(wrapper)
        param_names = list(wrapped_sig.parameters.keys())
        assert "image" in param_names
        assert "mask" in param_names

    def test_mixed_file_and_form_params(self):
        """FILE-005: bytes params become File(), non-bytes become Form()."""
        from runpod_flash.runtime.lb_handler import _build_file_upload_wrapper
        import inspect

        def handler(data: bytes, label: str):
            return label

        sig = inspect.signature(handler)
        hints = {"data": bytes, "label": str}

        file_params = [("data", bytes, inspect.Parameter.empty)]
        form_params = [("label", str, inspect.Parameter.empty)]
        path_params: set = set()

        wrapper = _build_file_upload_wrapper(
            handler, file_params, form_params, path_params, hints, sig
        )

        wrapped_sig = inspect.signature(wrapper)
        assert "data" in wrapped_sig.parameters
        assert "label" in wrapped_sig.parameters

    def test_wrapper_preserves_handler_name(self):
        """FILE-005: wrapper __name__ matches the original handler's __name__."""
        from runpod_flash.runtime.lb_handler import _build_file_upload_wrapper
        import inspect

        def my_upload_handler(file1: bytes, file2: bytes):
            pass

        sig = inspect.signature(my_upload_handler)
        hints = {"file1": bytes, "file2": bytes}
        file_params = [
            ("file1", bytes, inspect.Parameter.empty),
            ("file2", bytes, inspect.Parameter.empty),
        ]

        wrapper = _build_file_upload_wrapper(
            my_upload_handler, file_params, [], set(), hints, sig
        )

        assert wrapper.__name__ == "my_upload_handler"

    def test_wrap_handler_with_body_model_detects_multiple_file_params(self):
        """FILE-005: _wrap_handler_with_body_model routes multiple bytes params to file wrapper."""
        from runpod_flash.runtime.lb_handler import _wrap_handler_with_body_model
        import inspect

        def upload(photo: bytes, thumbnail: bytes):
            return "ok"

        wrapper = _wrap_handler_with_body_model(upload, "/upload")

        # Resulting signature must include both params
        sig = inspect.signature(wrapper)
        param_names = list(sig.parameters.keys())
        assert "photo" in param_names
        assert "thumbnail" in param_names


# ---------------------------------------------------------------------------
# LOG-003: JobOutput.model_post_init logs delay and execution times
# ---------------------------------------------------------------------------


class TestJobOutputLogging:
    """JobOutput.model_post_init emits log messages for timing fields."""

    def test_model_post_init_logs_delay_time(self, caplog):
        """LOG-003: JobOutput logs delayTime after construction."""
        from runpod_flash.core.resources.serverless import JobOutput

        with caplog.at_level(
            logging.INFO, logger="runpod_flash.core.resources.serverless"
        ):
            JobOutput(
                id="job-001",
                workerId="worker-xyz",
                status="COMPLETED",
                delayTime=42,
                executionTime=100,
                output={"result": "done"},
            )

        delay_logged = any(
            "42" in record.message and "Delay" in record.message
            for record in caplog.records
        )
        assert delay_logged, (
            f"Expected delay time (42) in log records. Records: {[r.message for r in caplog.records]}"
        )

    def test_model_post_init_logs_execution_time(self, caplog):
        """LOG-003: JobOutput logs executionTime after construction."""
        from runpod_flash.core.resources.serverless import JobOutput

        with caplog.at_level(
            logging.INFO, logger="runpod_flash.core.resources.serverless"
        ):
            JobOutput(
                id="job-002",
                workerId="worker-abc",
                status="COMPLETED",
                delayTime=10,
                executionTime=250,
            )

        exec_logged = any(
            "250" in record.message and "Execution" in record.message
            for record in caplog.records
        )
        assert exec_logged, (
            f"Expected execution time (250) in log records. Records: {[r.message for r in caplog.records]}"
        )

    def test_model_post_init_includes_worker_id_in_log(self, caplog):
        """LOG-003: log messages include the workerId for correlation."""
        from runpod_flash.core.resources.serverless import JobOutput

        with caplog.at_level(
            logging.INFO, logger="runpod_flash.core.resources.serverless"
        ):
            JobOutput(
                id="job-003",
                workerId="worker-CORRELATION",
                status="COMPLETED",
                delayTime=5,
                executionTime=75,
            )

        worker_in_log = any(
            "worker-CORRELATION" in record.message for record in caplog.records
        )
        assert worker_in_log, (
            f"Expected workerId in log. Records: {[r.message for r in caplog.records]}"
        )

    def test_model_post_init_logs_both_fields_separately(self, caplog):
        """LOG-003: two separate log records are emitted (one per timing field)."""
        from runpod_flash.core.resources.serverless import JobOutput

        with caplog.at_level(
            logging.INFO, logger="runpod_flash.core.resources.serverless"
        ):
            JobOutput(
                id="job-004",
                workerId="w1",
                status="COMPLETED",
                delayTime=11,
                executionTime=99,
            )

        timing_records = [
            r
            for r in caplog.records
            if "Delay" in r.message or "Execution" in r.message
        ]
        assert len(timing_records) >= 2, (
            f"Expected at least 2 timing log records, got {len(timing_records)}"
        )
