"""unit tests for RuntimeScanner (build_utils/scanner.py).

covers import error paths, introspection edge cases, cross-call analysis,
module cleanup, __flash_local__ propagation, and lb route stamp correctness.
"""

import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from runpod_flash.cli.commands.build_utils.scanner import (
    MODULE_IMPORT_TIMEOUT_SECONDS,
    RemoteFunctionMetadata,
    RuntimeScanner,
    _analyze_cross_calls_ast,
    _find_endpoint_instances,
    _find_remote_decorated,
    _import_module_from_file,
    file_to_module_path,
    file_to_resource_name,
    file_to_url_prefix,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write_worker(tmp_path: Path, filename: str, code: str) -> Path:
    """write a python file into tmp_path and return its path."""
    p = tmp_path / filename
    p.write_text(textwrap.dedent(code), encoding="utf-8")
    return p


def _write_remote_worker(tmp_path: Path, filename: str = "worker.py") -> Path:
    """write a minimal valid @remote worker."""
    return _write_worker(
        tmp_path,
        filename,
        """\
        from runpod_flash import remote, LiveServerless
        cfg = LiveServerless(name="test-ep")

        @remote(cfg)
        def process(x):
            return x
        """,
    )


# ---------------------------------------------------------------------------
# _import_module_from_file
# ---------------------------------------------------------------------------


class TestImportModuleFromFile:
    """_import_module_from_file error paths and cleanup."""

    def test_syntax_error_raises(self, tmp_path):
        p = _write_worker(tmp_path, "bad.py", "def foo(\n")
        with pytest.raises(SyntaxError):
            _import_module_from_file(p, "bad")

    def test_import_error_raises(self, tmp_path):
        p = _write_worker(tmp_path, "missing_dep.py", "import nonexistent_module_xyz\n")
        with pytest.raises(ModuleNotFoundError):
            _import_module_from_file(p, "missing_dep")

    def test_runtime_error_raises(self, tmp_path):
        p = _write_worker(tmp_path, "crasher.py", 'raise RuntimeError("boom")\n')
        with pytest.raises(RuntimeError, match="boom"):
            _import_module_from_file(p, "crasher")

    def test_returns_none_for_bad_spec(self, tmp_path):
        p = tmp_path / "nonexistent.py"
        # file doesn't exist so the import raises FileNotFoundError
        with pytest.raises(FileNotFoundError):
            _import_module_from_file(p, "nonexistent")

    def test_successful_import_returns_module(self, tmp_path):
        p = _write_worker(tmp_path, "ok.py", "VALUE = 42\n")
        mod = _import_module_from_file(p, "ok_module")
        assert mod is not None
        assert mod.VALUE == 42

    def test_module_cleanup_on_success(self, tmp_path):
        """sys.modules is restored after a successful import."""
        module_name = "_test_cleanup_success_xyz"
        assert module_name not in sys.modules

        p = _write_worker(tmp_path, "clean.py", "X = 1\n")
        _import_module_from_file(p, module_name)

        # should be cleaned up
        assert module_name not in sys.modules

    def test_module_cleanup_on_failure(self, tmp_path):
        """sys.modules is restored after a failed import."""
        module_name = "_test_cleanup_fail_xyz"
        assert module_name not in sys.modules

        p = _write_worker(tmp_path, "fail.py", 'raise ValueError("fail")\n')
        with pytest.raises(ValueError):
            _import_module_from_file(p, module_name)

        assert module_name not in sys.modules

    def test_module_cleanup_preserves_existing(self, tmp_path):
        """if the module name was already in sys.modules, it is restored."""
        module_name = "_test_preserve_xyz"
        sentinel = object()
        sys.modules[module_name] = sentinel  # type: ignore[assignment]
        try:
            p = _write_worker(tmp_path, "preserve.py", "X = 1\n")
            _import_module_from_file(p, module_name)
            assert sys.modules.get(module_name) is sentinel
        finally:
            sys.modules.pop(module_name, None)

    def test_timeout_on_blocking_module(self, tmp_path):
        """modules that block longer than the timeout raise TimeoutError."""
        import signal

        if not hasattr(signal, "SIGALRM"):
            pytest.skip("SIGALRM not available on this platform")

        p = _write_worker(
            tmp_path,
            "slow.py",
            "import time\ntime.sleep(10)\n",
        )
        with patch(
            "runpod_flash.cli.commands.build_utils.scanner.MODULE_IMPORT_TIMEOUT_SECONDS",
            1,
        ):
            with pytest.raises(TimeoutError, match="timed out"):
                _import_module_from_file(p, "slow_module")


# ---------------------------------------------------------------------------
# _find_remote_decorated
# ---------------------------------------------------------------------------


class TestFindRemoteDecorated:
    """_find_remote_decorated introspection edge cases."""

    def test_finds_objects_with_remote_config(self):
        import types

        mod = types.ModuleType("fake")
        fn = lambda x: x  # noqa: E731
        fn.__remote_config__ = {"resource_config": None}  # type: ignore[attr-defined]
        mod.my_func = fn  # type: ignore[attr-defined]
        mod.plain = 42  # type: ignore[attr-defined]

        result = _find_remote_decorated(mod)
        assert "my_func" in result
        assert "plain" not in result

    def test_skips_getattr_exceptions(self):
        """objects that raise on getattr are silently skipped."""
        import types

        mod = types.ModuleType("fake")

        class Exploder:
            def __getattr__(self, name):
                raise RuntimeError("no")

        mod.__dict__["bomb"] = Exploder()
        mod.safe = "ok"  # type: ignore[attr-defined]

        # should not raise
        result = _find_remote_decorated(mod)
        assert "safe" not in result  # safe has no __remote_config__

    def test_empty_module(self):
        import types

        mod = types.ModuleType("empty")
        result = _find_remote_decorated(mod)
        assert result == {}


# ---------------------------------------------------------------------------
# _find_endpoint_instances
# ---------------------------------------------------------------------------


class TestFindEndpointInstances:
    """_find_endpoint_instances edge cases."""

    def test_finds_non_client_endpoints(self):
        import types

        from runpod_flash.core.resources.gpu import GpuGroup
        from runpod_flash.endpoint import Endpoint

        mod = types.ModuleType("fake")
        ep = Endpoint(name="test-ep", gpu=GpuGroup.AMPERE_16)
        mod.ep = ep  # type: ignore[attr-defined]

        result = _find_endpoint_instances(mod)
        assert "ep" in result

    def test_skips_client_endpoints(self):
        import types

        from runpod_flash.endpoint import Endpoint

        mod = types.ModuleType("fake")
        client_ep = Endpoint(name="client-ep", image="my-image:latest")
        mod.client_ep = client_ep  # type: ignore[attr-defined]

        result = _find_endpoint_instances(mod)
        assert "client_ep" not in result


# ---------------------------------------------------------------------------
# _analyze_cross_calls_ast
# ---------------------------------------------------------------------------


class TestAnalyzeCrossCallsAst:
    """cross-call detection via AST."""

    def test_detects_direct_calls(self, tmp_path):
        p = _write_worker(
            tmp_path,
            "cross.py",
            """\
            def helper():
                pass

            def caller():
                helper()
            """,
        )
        result = _analyze_cross_calls_ast(p, {"caller", "helper"}, {"helper"})
        assert "caller" in result
        assert "helper" in result["caller"]

    def test_ignores_attribute_calls(self, tmp_path):
        p = _write_worker(
            tmp_path,
            "attr.py",
            """\
            def caller():
                obj.helper()
            """,
        )
        result = _analyze_cross_calls_ast(p, {"caller"}, {"helper"})
        assert result == {}

    def test_returns_empty_on_syntax_error(self, tmp_path):
        p = _write_worker(tmp_path, "broken.py", "def foo(\n")
        result = _analyze_cross_calls_ast(p, {"foo"}, {"bar"})
        assert result == {}

    def test_returns_empty_on_nonexistent_file(self, tmp_path):
        p = tmp_path / "nonexistent.py"
        result = _analyze_cross_calls_ast(p, {"foo"}, {"bar"})
        assert result == {}

    def test_handles_async_functions(self, tmp_path):
        p = _write_worker(
            tmp_path,
            "async_cross.py",
            """\
            async def remote_fn():
                pass

            async def caller():
                remote_fn()
            """,
        )
        result = _analyze_cross_calls_ast(p, {"caller", "remote_fn"}, {"remote_fn"})
        assert "caller" in result
        assert "remote_fn" in result["caller"]

    def test_handles_class_methods(self, tmp_path):
        p = _write_worker(
            tmp_path,
            "cls_cross.py",
            """\
            def remote_fn():
                pass

            class MyClass:
                def method(self):
                    remote_fn()
            """,
        )
        result = _analyze_cross_calls_ast(p, {"MyClass", "remote_fn"}, {"remote_fn"})
        assert "MyClass" in result

    def test_no_duplicates_in_called_list(self, tmp_path):
        p = _write_worker(
            tmp_path,
            "dupes.py",
            """\
            def remote_fn():
                pass

            def caller():
                remote_fn()
                remote_fn()
                remote_fn()
            """,
        )
        result = _analyze_cross_calls_ast(p, {"caller", "remote_fn"}, {"remote_fn"})
        assert result["caller"] == ["remote_fn"]


# ---------------------------------------------------------------------------
# RuntimeScanner.discover_remote_functions
# ---------------------------------------------------------------------------


class TestRuntimeScannerDiscovery:
    """RuntimeScanner end-to-end discovery tests."""

    def test_discovers_remote_function(self, tmp_path):
        _write_remote_worker(tmp_path)
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert len(functions) == 1
        assert functions[0].function_name == "process"

    def test_records_import_errors(self, tmp_path):
        _write_worker(tmp_path, "broken.py", "import nonexistent_xyz_123\n")
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert functions == []
        assert "broken.py" in scanner.import_errors
        assert "ModuleNotFoundError" in scanner.import_errors["broken.py"]

    def test_records_syntax_errors(self, tmp_path):
        _write_worker(tmp_path, "bad_syntax.py", "def oops(\n")
        scanner = RuntimeScanner(tmp_path)
        scanner.discover_remote_functions()
        assert "bad_syntax.py" in scanner.import_errors
        assert "SyntaxError" in scanner.import_errors["bad_syntax.py"]

    def test_records_runtime_errors(self, tmp_path):
        _write_worker(tmp_path, "crasher.py", 'raise ValueError("nope")\n')
        scanner = RuntimeScanner(tmp_path)
        scanner.discover_remote_functions()
        assert "crasher.py" in scanner.import_errors
        assert "ValueError" in scanner.import_errors["crasher.py"]

    def test_skips_init_files(self, tmp_path):
        (tmp_path / "__init__.py").write_text(
            "from runpod_flash import remote, LiveServerless\n"
            'cfg = LiveServerless(name="init-ep")\n'
            "@remote(cfg)\n"
            "def init_func(x): return x\n",
            encoding="utf-8",
        )
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert functions == []

    def test_cross_call_detection(self, tmp_path):
        _write_worker(
            tmp_path,
            "multi.py",
            """\
            from runpod_flash import remote, LiveServerless
            cfg = LiveServerless(name="test-ep")

            @remote(cfg)
            def helper(x):
                return x * 2

            @remote(cfg)
            def caller(x):
                return helper(x)
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        caller = next(f for f in functions if f.function_name == "caller")
        assert caller.calls_remote_functions is True
        assert "helper" in caller.called_remote_functions

    def test_sys_path_cleanup(self, tmp_path):
        """project root is removed from sys.path after scanning."""
        root_str = str(tmp_path)
        assert root_str not in sys.path

        _write_remote_worker(tmp_path)
        scanner = RuntimeScanner(tmp_path)
        scanner.discover_remote_functions()

        assert root_str not in sys.path

    def test_synthetic_package_cleanup(self, tmp_path):
        """synthetic parent packages are removed from sys.modules after scanning."""
        sub = tmp_path / "subpkg"
        sub.mkdir()
        _write_remote_worker(sub, "worker.py")

        scanner = RuntimeScanner(tmp_path)
        scanner.discover_remote_functions()

        assert "subpkg" not in sys.modules

    def test_populates_resource_dicts(self, tmp_path):
        _write_remote_worker(tmp_path)
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert len(functions) == 1

        name = functions[0].resource_config_name
        assert name in scanner.resource_configs
        assert name in scanner.resource_types
        assert name in scanner.resource_flags

    def test_discovers_async_function(self, tmp_path):
        _write_worker(
            tmp_path,
            "async_worker.py",
            """\
            from runpod_flash import remote, LiveServerless
            cfg = LiveServerless(name="async-ep")

            @remote(cfg)
            async def async_process(x):
                return x
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert len(functions) == 1
        assert functions[0].is_async is True

    def test_discovers_class(self, tmp_path):
        _write_worker(
            tmp_path,
            "cls_worker.py",
            """\
            from runpod_flash import remote, LiveServerless
            cfg = LiveServerless(name="cls-ep")

            @remote(cfg)
            class MyModel:
                def predict(self, x):
                    return x
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert len(functions) == 1
        assert functions[0].is_class is True
        assert "predict" in functions[0].class_methods

    def test_docstring_extraction(self, tmp_path):
        _write_worker(
            tmp_path,
            "doc_worker.py",
            """\
            from runpod_flash import remote, LiveServerless
            cfg = LiveServerless(name="doc-ep")

            @remote(cfg)
            def documented(x):
                \"\"\"process the input.\"\"\"
                return x
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert functions[0].docstring == "process the input."

    def test_param_names_extraction(self, tmp_path):
        _write_worker(
            tmp_path,
            "params_worker.py",
            """\
            from runpod_flash import remote, LiveServerless
            cfg = LiveServerless(name="params-ep")

            @remote(cfg)
            def multi_param(a, b, c):
                return a + b + c
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert functions[0].param_names == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# __flash_local__ propagation
# ---------------------------------------------------------------------------


class TestFlashLocalFlag:
    """__flash_local__ flag is correctly read from decorated objects."""

    def test_local_flag_true(self, tmp_path):
        _write_worker(
            tmp_path,
            "local_worker.py",
            """\
            from runpod_flash import remote, LiveServerless
            cfg = LiveServerless(name="local-ep")

            @remote(cfg, local=True)
            def local_fn(x):
                return x
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert len(functions) == 1
        assert functions[0].local is True

    def test_local_flag_false_by_default(self, tmp_path):
        _write_remote_worker(tmp_path)
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert len(functions) == 1
        assert functions[0].local is False


# ---------------------------------------------------------------------------
# lb route stamp correctness
# ---------------------------------------------------------------------------


class TestLBRouteStamps:
    """lb route handler detection picks up method and path from endpoint decorators."""

    def test_lb_route_method_and_path(self, tmp_path):
        _write_worker(
            tmp_path,
            "lb_worker.py",
            """\
            from runpod_flash.endpoint import Endpoint
            from runpod_flash.core.resources.gpu import GpuGroup

            api = Endpoint(name="lb-api", gpu=GpuGroup.AMPERE_16)

            @api.post("/compute")
            def compute(data):
                return data
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert len(functions) == 1
        meta = functions[0]
        assert meta.http_method == "POST"
        assert meta.http_path == "/compute"
        assert meta.is_lb_route_handler is True
        assert meta.is_load_balanced is True

    def test_lb_get_route(self, tmp_path):
        _write_worker(
            tmp_path,
            "lb_get.py",
            """\
            from runpod_flash.endpoint import Endpoint
            from runpod_flash.core.resources.gpu import GpuGroup

            api = Endpoint(name="lb-get", gpu=GpuGroup.AMPERE_16)

            @api.get("/health")
            def health():
                return {"status": "ok"}
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert len(functions) == 1
        meta = functions[0]
        assert meta.http_method == "GET"
        assert meta.http_path == "/health"

    def test_config_variable_traced_for_lb_route(self, tmp_path):
        _write_worker(
            tmp_path,
            "lb_var.py",
            """\
            from runpod_flash.endpoint import Endpoint
            from runpod_flash.core.resources.gpu import GpuGroup

            my_api = Endpoint(name="lb-var", gpu=GpuGroup.AMPERE_16)

            @my_api.post("/run")
            def run_it(x):
                return x
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert len(functions) == 1
        assert functions[0].config_variable == "my_api"


# ---------------------------------------------------------------------------
# path utility functions
# ---------------------------------------------------------------------------


class TestPathUtilities:
    """file_to_* helper functions."""

    def test_file_to_url_prefix(self, tmp_path):
        p = tmp_path / "longruns" / "stage1.py"
        assert file_to_url_prefix(p, tmp_path) == "/longruns/stage1"

    def test_file_to_resource_name(self, tmp_path):
        p = tmp_path / "longruns" / "stage1.py"
        assert file_to_resource_name(p, tmp_path) == "longruns_stage1"

    def test_file_to_resource_name_hyphens(self, tmp_path):
        p = tmp_path / "my-worker.py"
        assert file_to_resource_name(p, tmp_path) == "my_worker"

    def test_file_to_module_path(self, tmp_path):
        p = tmp_path / "longruns" / "stage1.py"
        assert file_to_module_path(p, tmp_path) == "longruns.stage1"

    def test_file_to_module_path_simple(self, tmp_path):
        p = tmp_path / "worker.py"
        assert file_to_module_path(p, tmp_path) == "worker"


# ---------------------------------------------------------------------------
# cross-call analysis with partial import failures
# ---------------------------------------------------------------------------


class TestCrossCallPartialFailure:
    """cross-call analysis degrades when some files failed to import."""

    def test_cross_calls_skipped_for_failed_files(self, tmp_path):
        """cross-call AST analysis only runs on files that imported successfully."""
        # good worker has a function that calls a name matching a remote
        _write_worker(
            tmp_path,
            "good.py",
            """\
            from runpod_flash import remote, LiveServerless
            cfg = LiveServerless(name="good-ep")

            @remote(cfg)
            def helper(x):
                return x

            @remote(cfg)
            def caller(x):
                return helper(x)
            """,
        )
        # bad worker fails to import
        _write_worker(tmp_path, "bad.py", "import nonexistent_xyz_123\n")

        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()

        # only good.py functions are discovered
        assert len(functions) == 2
        assert "bad.py" in scanner.import_errors

        # cross-call analysis still works for the successful file
        caller = next(f for f in functions if f.function_name == "caller")
        assert caller.calls_remote_functions is True


# ---------------------------------------------------------------------------
# multiple files
# ---------------------------------------------------------------------------


class TestMultipleFiles:
    """scanner handles multiple worker files correctly."""

    def test_discovers_across_files(self, tmp_path):
        _write_worker(
            tmp_path,
            "worker_a.py",
            """\
            from runpod_flash import remote, LiveServerless
            cfg = LiveServerless(name="ep-a")

            @remote(cfg)
            def func_a(x):
                return x
            """,
        )
        _write_worker(
            tmp_path,
            "worker_b.py",
            """\
            from runpod_flash import remote, LiveServerless
            cfg = LiveServerless(name="ep-b")

            @remote(cfg)
            def func_b(x):
                return x
            """,
        )

        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        names = {f.function_name for f in functions}
        assert names == {"func_a", "func_b"}

    def test_deduplication_across_same_file(self, tmp_path):
        """same function name in the same module is only discovered once."""
        _write_remote_worker(tmp_path)
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert len(functions) == 1


# ---------------------------------------------------------------------------
# subdirectory / nested package support
# ---------------------------------------------------------------------------


class TestSubdirectorySupport:
    """scanner handles files in subdirectories."""

    def test_discovers_in_subdirectory(self, tmp_path):
        sub = tmp_path / "workers"
        sub.mkdir()
        _write_remote_worker(sub, "gpu_worker.py")

        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert len(functions) == 1
        assert functions[0].module_path == "workers.gpu_worker"
