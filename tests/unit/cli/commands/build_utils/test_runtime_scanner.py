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
    RuntimeScanner,
    _analyze_cross_calls_ast,
    _find_endpoint_instances,
    _find_remote_decorated,
    _import_module_from_file,
    file_to_module_path,
    file_to_resource_name,
    file_to_url_prefix,
)
from runpod_flash.endpoint import Endpoint


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

    def test_detects_client_endpoint_reference(self, tmp_path):
        p = _write_worker(
            tmp_path,
            "client_ref.py",
            """\
            async def caller(x):
                return await vllm.runsync(x)
            """,
        )
        vllm = Endpoint(name="vllm", image="vllm/vllm-openai:latest")
        result = _analyze_cross_calls_ast(p, {"caller"}, set(), {"vllm": vllm})
        assert result == {"caller": ["vllm"]}

    def test_detects_aliased_inline_client_endpoint(self, tmp_path):
        p = _write_worker(
            tmp_path,
            "alias.py",
            """\
            async def caller(x):
                return await EP(id="abc123").runsync(x)
            """,
        )
        result = _analyze_cross_calls_ast(p, {"caller"}, set(), {"EP": Endpoint})
        assert result == {"caller": ["Endpoint"]}

    def test_detects_runpod_sdk_use(self, tmp_path):
        import runpod

        p = _write_worker(
            tmp_path,
            "sdk.py",
            """\
            def caller(x):
                return runpod.Endpoint("abc123").run_sync(x)
            """,
        )
        result = _analyze_cross_calls_ast(p, {"caller"}, set(), {"runpod": runpod})
        assert result == {"caller": ["runpod"]}

    def test_detects_api_key_read(self, tmp_path):
        p = _write_worker(
            tmp_path,
            "env_read.py",
            """\
            import os

            def caller(x):
                return os.environ["RUNPOD_API_KEY"]
            """,
        )
        result = _analyze_cross_calls_ast(p, {"caller"}, set())
        assert result == {"caller": ["RUNPOD_API_KEY"]}

    @pytest.mark.parametrize("kwarg", ['id="abc123"', 'image="org/img:1"'])
    def test_detects_inline_client_endpoint(self, tmp_path, kwarg):
        p = _write_worker(
            tmp_path,
            "inline_client.py",
            f"""\
            async def caller(x):
                return await Endpoint({kwarg}).runsync(x)
            """,
        )
        result = _analyze_cross_calls_ast(p, {"caller"}, set())
        assert result == {"caller": ["Endpoint"]}

    def test_analysis_error_assumes_key_needed(self, tmp_path):
        p = _write_worker(tmp_path, "boom.py", "def caller():\n    pass\n")
        with patch(
            "runpod_flash.cli.commands.build_utils.scanner._remote_call_targets",
            side_effect=RuntimeError("boom"),
        ):
            result = _analyze_cross_calls_ast(p, {"caller"}, set())
        assert result == {"caller": ["<unanalyzed>"]}

    def test_ignores_non_client_endpoint_construction(self, tmp_path):
        p = _write_worker(
            tmp_path,
            "inline_decorator.py",
            """\
            def caller(x):
                return Endpoint(name="ep", gpu=None)
            """,
        )
        result = _analyze_cross_calls_ast(p, {"caller"}, set())
        assert result == {}


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

    def test_client_endpoint_call_detection(self, tmp_path):
        """calling a client-mode Endpoint counts as a remote call."""
        _write_worker(
            tmp_path,
            "wrapper.py",
            """\
            from runpod_flash import Endpoint
            vllm = Endpoint(name="vllm-backend", image="vllm/vllm-openai:latest")

            @Endpoint(name="wrapper", cpu="cpu3c-1-2")
            async def caller(x):
                return await vllm.runsync(x)

            @Endpoint(name="isolated", cpu="cpu3c-1-2")
            async def isolated(x):
                return x
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        caller = next(f for f in functions if f.function_name == "caller")
        isolated = next(f for f in functions if f.function_name == "isolated")
        assert caller.calls_remote_functions is True
        assert caller.called_remote_functions == ["vllm"]
        assert isolated.calls_remote_functions is False

    def test_helper_in_other_file_detection(self, tmp_path):
        """a helper in another project file that calls an endpoint counts."""
        _write_worker(
            tmp_path,
            "clients.py",
            """\
            from runpod_flash import Endpoint
            vllm = Endpoint(name="vllm-backend", image="vllm/vllm-openai:latest")

            async def generate(x):
                return await vllm.runsync(x)

            def double(x):
                return x * 2
            """,
        )
        _write_worker(
            tmp_path,
            "wrapper.py",
            """\
            from runpod_flash import Endpoint
            import clients
            from clients import double

            @Endpoint(name="via-helper", cpu="cpu3c-1-2")
            async def via_helper(x):
                return await clients.generate(x)

            @Endpoint(name="pure-helper", cpu="cpu3c-1-2")
            async def pure_helper(x):
                return double(x)
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        via_helper = next(f for f in functions if f.function_name == "via_helper")
        pure_helper = next(f for f in functions if f.function_name == "pure_helper")
        assert via_helper.called_remote_functions == ["generate"]
        assert pure_helper.calls_remote_functions is False

    def test_remote_function_via_module_alias_or_value(self, tmp_path):
        """another @Endpoint reached through a module, an alias, or as a value."""
        _write_worker(
            tmp_path,
            "tasks.py",
            """\
            from runpod_flash import Endpoint

            @Endpoint(name="square", cpu="cpu3c-1-2")
            async def square(x):
                return x * x
            """,
        )
        _write_worker(
            tmp_path,
            "app.py",
            """\
            from runpod_flash import Endpoint
            import tasks
            from tasks import square as sq

            @Endpoint(name="via-module", cpu="cpu3c-1-2")
            async def via_module(x):
                return await tasks.square(x)

            @Endpoint(name="aliased", cpu="cpu3c-1-2")
            async def aliased(x):
                return await sq(x)

            @Endpoint(name="passed", cpu="cpu3c-1-2")
            async def passed(xs):
                return list(map(tasks.square, xs))
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        by_name = {
            f.function_name: f
            for f in scanner.discover_remote_functions()
            if f.function_name != "square"
        }
        assert by_name["via_module"].called_remote_functions == ["tasks.square"]
        assert by_name["aliased"].called_remote_functions == ["sq"]
        assert by_name["passed"].called_remote_functions == ["tasks.square"]

    def test_function_local_imports(self, tmp_path):
        """imports inside the endpoint function are resolved too."""
        _write_worker(
            tmp_path,
            "local_imports.py",
            """\
            from runpod_flash import Endpoint

            @Endpoint(name="local-alias", cpu="cpu3c-1-2")
            async def local_alias(x):
                from runpod_flash import Endpoint as EP
                return await EP(id="abc123").runsync(x)

            @Endpoint(name="local-sdk", cpu="cpu3c-1-2")
            async def local_sdk(x):
                import runpod
                return runpod.Endpoint("abc123").run_sync(x)

            @Endpoint(name="local-stdlib", cpu="cpu3c-1-2")
            async def local_stdlib(x):
                import json
                return json.dumps(x)
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        by_name = {f.function_name: f for f in scanner.discover_remote_functions()}
        assert by_name["local_alias"].called_remote_functions == ["Endpoint"]
        assert "runpod" in by_name["local_sdk"].called_remote_functions
        assert by_name["local_stdlib"].calls_remote_functions is False

    def test_cyclic_helpers_shared_by_two_endpoints(self, tmp_path):
        """a helper first reached mid-cycle is still detected for later callers."""
        _write_worker(
            tmp_path,
            "cyclic.py",
            """\
            from runpod_flash import Endpoint
            vllm = Endpoint(name="vllm-backend", image="vllm/vllm-openai:latest")

            async def helper_a(x, depth=0):
                if depth:
                    await helper_b(x, depth - 1)
                return await vllm.runsync(x)

            async def helper_b(x, depth=0):
                return await helper_a(x, depth)

            @Endpoint(name="first", cpu="cpu3c-1-2")
            async def first(x):
                return await helper_a(x, 1)

            @Endpoint(name="second", cpu="cpu3c-1-2")
            async def second(x):
                return await helper_b(x, 1)
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        by_name = {f.function_name: f for f in scanner.discover_remote_functions()}
        assert by_name["first"].calls_remote_functions is True
        assert by_name["second"].calls_remote_functions is True

    def test_helpers_outside_scanned_files_are_not_analyzed(self, tmp_path):
        """library code in an in-project .venv is not treated as a helper."""
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "fakelib.py").write_text(
            "import os\n\ndef read_key():\n    return os.environ.get('RUNPOD_API_KEY')\n",
            encoding="utf-8",
        )
        _write_worker(
            tmp_path,
            "app.py",
            """\
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent / ".venv"))
            from fakelib import read_key
            from runpod_flash import Endpoint

            @Endpoint(name="lib-call", cpu="cpu3c-1-2")
            async def lib_call(x):
                read_key()
                return x
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        try:
            lib_call = scanner.discover_remote_functions()[0]
        finally:
            sys.path[:] = [x for x in sys.path if x != str(venv)]
            sys.modules.pop("fakelib", None)
        assert scanner.import_errors == {}
        assert lib_call.calls_remote_functions is False

    def test_function_local_project_imports(self, tmp_path):
        """sibling modules imported inside the endpoint resolve after scanning."""
        _write_worker(
            tmp_path,
            "local_tasks.py",
            """\
            from runpod_flash import Endpoint

            @Endpoint(name="square", cpu="cpu3c-1-2")
            async def square(x):
                return x * x
            """,
        )
        _write_worker(
            tmp_path,
            "local_app.py",
            """\
            from runpod_flash import Endpoint

            @Endpoint(name="from-import", cpu="cpu3c-1-2")
            async def from_import(x):
                from local_tasks import square as sq
                return await sq(x)

            @Endpoint(name="module-import", cpu="cpu3c-1-2")
            async def module_import(x):
                import local_tasks
                return await local_tasks.square(x)
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        by_name = {f.function_name: f for f in scanner.discover_remote_functions()}
        assert by_name["from_import"].called_remote_functions == ["sq"]
        assert by_name["module_import"].called_remote_functions == [
            "local_tasks.square"
        ]

    def test_relative_and_package_qualified_imports(self, tmp_path):
        """subpackage endpoints reached relatively or through the package path."""
        (tmp_path / "rel_pkg").mkdir()
        _write_worker(
            tmp_path,
            "rel_pkg/tasks.py",
            """\
            from runpod_flash import Endpoint

            @Endpoint(name="square", cpu="cpu3c-1-2")
            async def square(x):
                return x * x
            """,
        )
        _write_worker(
            tmp_path,
            "rel_pkg/app.py",
            """\
            from runpod_flash import Endpoint

            @Endpoint(name="relative", cpu="cpu3c-1-2")
            async def relative(x):
                from .tasks import square as sq
                return await sq(x)

            @Endpoint(name="qualified", cpu="cpu3c-1-2")
            async def qualified(x):
                import rel_pkg.tasks
                return await rel_pkg.tasks.square(x)

            @Endpoint(name="missing", cpu="cpu3c-1-2")
            async def missing(x):
                from .nowhere import thing
                return thing(x)
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        by_name = {f.function_name: f for f in scanner.discover_remote_functions()}
        assert by_name["relative"].called_remote_functions == ["sq"]
        assert by_name["qualified"].called_remote_functions == ["rel_pkg.tasks.square"]
        # a project import that cannot be resolved errs toward the key
        assert by_name["missing"].called_remote_functions == ["<unanalyzed>"]

    def test_unresolved_import_of_failed_project_module(self, tmp_path):
        """a local import of a project file that failed to import errs toward the key."""
        _write_worker(tmp_path, "broken_dep.py", "raise RuntimeError('boom')\n")
        _write_worker(
            tmp_path,
            "uses_broken.py",
            """\
            from runpod_flash import Endpoint

            @Endpoint(name="uses-broken", cpu="cpu3c-1-2")
            async def uses_broken(x):
                from broken_dep import helper
                return helper(x)
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        uses_broken = next(
            f
            for f in scanner.discover_remote_functions()
            if f.function_name == "uses_broken"
        )
        assert uses_broken.called_remote_functions == ["<unanalyzed>"]

    def test_helper_in_package_init(self, tmp_path):
        """helpers defined in a package __init__.py are analyzed."""
        (tmp_path / "init_utils").mkdir()
        _write_worker(
            tmp_path,
            "init_utils/__init__.py",
            """\
            from runpod_flash import Endpoint
            vllm = Endpoint(id="abc123")

            def call_model(x):
                return vllm.runsync(x)
            """,
        )
        _write_worker(
            tmp_path,
            "init_app.py",
            """\
            from runpod_flash import Endpoint
            import init_utils

            @Endpoint(name="via-init", cpu="cpu3c-1-2")
            async def via_init(x):
                return init_utils.call_model(x)
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        try:
            via_init = scanner.discover_remote_functions()[0]
        finally:
            sys.modules.pop("init_utils", None)
        assert via_init.called_remote_functions == ["call_model"]

    def test_project_classes_and_instances(self, tmp_path):
        """methods, static/class methods, and instance attributes are followed."""
        _write_worker(
            tmp_path,
            "cls_clients.py",
            """\
            from runpod_flash import Endpoint

            class ModelClient:
                def generate(self, x):
                    return Endpoint(id="abc123").runsync(x)

            class Holder:
                def __init__(self, ep):
                    self.ep = ep

            class Helpers:
                @staticmethod
                def call(x):
                    return Endpoint(id="abc123").runsync(x)

            class Pure:
                def double(self, x):
                    return x * 2

            client = ModelClient()
            holder = Holder(Endpoint(id="abc123"))
            nested = Holder(Holder(Endpoint(id="abc123")))
            pure = Pure()
            pure.self_ref = pure
            """,
        )
        _write_worker(
            tmp_path,
            "cls_app.py",
            """\
            from runpod_flash import Endpoint
            from cls_clients import Helpers, client, holder, nested, pure

            @Endpoint(name="method", cpu="cpu3c-1-2")
            async def method(x):
                return client.generate(x)

            @Endpoint(name="static", cpu="cpu3c-1-2")
            async def static(x):
                return Helpers.call(x)

            @Endpoint(name="attribute", cpu="cpu3c-1-2")
            async def attribute(x):
                return holder.ep.runsync(x)

            @Endpoint(name="nested-attribute", cpu="cpu3c-1-2")
            async def nested_attribute(x):
                return nested.ep.ep.runsync(x)

            @Endpoint(name="pure-method", cpu="cpu3c-1-2")
            async def pure_method(x):
                return pure.double(x)
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        by_name = {f.function_name: f for f in scanner.discover_remote_functions()}
        assert by_name["method"].called_remote_functions == ["client"]
        assert by_name["static"].called_remote_functions == ["Helpers"]
        assert by_name["attribute"].called_remote_functions == ["holder"]
        assert by_name["nested_attribute"].called_remote_functions == ["nested"]
        assert by_name["pure_method"].calls_remote_functions is False

    def test_wrapped_and_contained_client_endpoints(self, tmp_path):
        """bound methods, partials, containers, and cached factories are followed."""
        _write_worker(
            tmp_path,
            "wrapped.py",
            """\
            import functools
            from runpod_flash import Endpoint

            vllm = Endpoint(id="abc123")
            run_vllm = vllm.runsync
            CLIENTS = {"vllm": vllm}
            call = functools.partial(vllm.runsync, timeout=5)

            @functools.lru_cache
            def client():
                return Endpoint(id="abc123")

            @Endpoint(name="bound", cpu="cpu3c-1-2")
            async def bound(x):
                return await run_vllm(x)

            @Endpoint(name="container", cpu="cpu3c-1-2")
            async def container(x):
                return await CLIENTS["vllm"].runsync(x)

            @Endpoint(name="partial", cpu="cpu3c-1-2")
            async def partial(x):
                return await call(x)

            @Endpoint(name="cached", cpu="cpu3c-1-2")
            async def cached(x):
                return await client().runsync(x)

            @Endpoint(name="plain-dict", cpu="cpu3c-1-2")
            async def plain_dict(x):
                return {"a": 1}.get(x)
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        by_name = {f.function_name: f for f in scanner.discover_remote_functions()}
        assert by_name["bound"].called_remote_functions == ["run_vllm"]
        assert by_name["container"].called_remote_functions == ["CLIENTS"]
        assert by_name["partial"].called_remote_functions == ["call"]
        assert by_name["cached"].called_remote_functions == ["client"]
        assert by_name["plain_dict"].calls_remote_functions is False

    def test_unparseable_helper_assumes_key_needed(self, tmp_path):
        """a helper whose source cannot be read or parsed errs toward the key."""
        _write_worker(
            tmp_path,
            "opaque_helper.py",
            """\
            from runpod_flash import Endpoint

            def helper(x):
                return x

            @Endpoint(name="via-helper", cpu="cpu3c-1-2")
            async def via_helper(x):
                return helper(x)
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        with patch(
            "runpod_flash.cli.commands.build_utils.scanner.inspect.getsource",
            side_effect=OSError("could not get source code"),
        ):
            via_helper = scanner.discover_remote_functions()[0]
        assert via_helper.called_remote_functions == ["helper"]

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


class TestClassAsyncDetection:
    """scanner detects is_async for class-based workers."""

    def test_sync_class_not_async(self, tmp_path):
        _write_worker(
            tmp_path,
            "sync_cls.py",
            """\
            from runpod_flash import remote, LiveServerless
            cfg = LiveServerless(name="sync-cls")

            @remote(cfg)
            class SyncWorker:
                def predict(self, x):
                    return x
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert len(functions) == 1
        assert functions[0].is_class is True
        assert functions[0].is_async is False

    def test_async_class_detected(self, tmp_path):
        _write_worker(
            tmp_path,
            "async_cls.py",
            """\
            from runpod_flash import remote, LiveServerless
            cfg = LiveServerless(name="async-cls")

            @remote(cfg)
            class AsyncWorker:
                async def predict(self, x):
                    return x
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert len(functions) == 1
        assert functions[0].is_class is True
        assert functions[0].is_async is True

    def test_mixed_class_detected_as_async(self, tmp_path):
        """Class with both sync and async methods is detected as async."""
        _write_worker(
            tmp_path,
            "mixed_cls.py",
            """\
            from runpod_flash import remote, LiveServerless
            cfg = LiveServerless(name="mixed-cls")

            @remote(cfg)
            class MixedWorker:
                def setup(self):
                    pass

                async def predict(self, x):
                    return x
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert len(functions) == 1
        assert functions[0].is_class is True
        assert functions[0].is_async is True


# ---------------------------------------------------------------------------
# client-mode Endpoint collection
# ---------------------------------------------------------------------------


class TestCollectClientEndpoints:
    """RuntimeScanner.client_endpoints records top-level Endpoint(image=...)."""

    def test_collects_image_endpoint_without_functions(self, tmp_path):
        """a client-mode endpoint is collected even with no decorated functions."""
        _write_worker(
            tmp_path,
            "vllm_ep.py",
            """\
            from runpod_flash import Endpoint
            from runpod_flash.core.resources.gpu import GpuGroup

            vllm = Endpoint(
                name="vllm-server",
                image="runpod/vllm-openai:stable",
                gpu=GpuGroup.ADA_24,
            )
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert functions == []
        assert set(scanner.client_endpoints) == {"vllm-server"}
        info = scanner.client_endpoints["vllm-server"]
        assert info["var_name"] == "vllm"
        assert info["module_path"] == "vllm_ep"
        assert info["file_path"] == tmp_path / "vllm_ep.py"

    def test_skips_id_endpoints(self, tmp_path):
        """Endpoint(id=...) attaches to an existing endpoint; nothing to provision."""
        _write_worker(
            tmp_path,
            "attach.py",
            """\
            from runpod_flash import Endpoint

            existing = Endpoint(name="existing", id="ep-123")
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        scanner.discover_remote_functions()
        assert scanner.client_endpoints == {}

    def test_skips_decorator_mode_endpoints(self, tmp_path):
        """Endpoint without image= is decorator-mode, not a client endpoint."""
        _write_remote_worker(tmp_path)
        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()
        assert len(functions) == 1
        assert scanner.client_endpoints == {}

    def test_dedupes_reexported_endpoint_across_files(self, tmp_path):
        """an endpoint imported into a second module is recorded only once."""
        _write_worker(
            tmp_path,
            "a_defs.py",
            """\
            from runpod_flash import Endpoint

            vllm = Endpoint(name="vllm-server", image="img:v1")
            """,
        )
        _write_worker(
            tmp_path,
            "b_reexport.py",
            """\
            from a_defs import vllm
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        scanner.discover_remote_functions()
        assert set(scanner.client_endpoints) == {"vllm-server"}
        # recorded against the defining file (a_defs.py sorts first)
        assert scanner.client_endpoints["vllm-server"]["file_path"] == (
            tmp_path / "a_defs.py"
        )

    def test_same_name_in_two_files_raises(self, tmp_path):
        """two distinct endpoints sharing a name fail the scan loudly."""
        _write_worker(
            tmp_path,
            "a_defs.py",
            """\
            from runpod_flash import Endpoint

            ep = Endpoint(name="dup", image="img:v1")
            """,
        )
        _write_worker(
            tmp_path,
            "b_defs.py",
            """\
            from runpod_flash import Endpoint

            ep = Endpoint(name="dup", image="img:v2")
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        with pytest.raises(ValueError, match="defined in multiple files"):
            scanner.discover_remote_functions()

    def test_same_file_alias_records_once(self, tmp_path):
        """``b = vllm`` exposes one object under two names; it is recorded once."""
        _write_worker(
            tmp_path,
            "aliases.py",
            """\
            from runpod_flash import Endpoint

            vllm = Endpoint(name="vllm-server", image="img:v1")
            b = vllm
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        scanner.discover_remote_functions()
        assert len(scanner.client_endpoints) == 1
        assert scanner.client_endpoints["vllm-server"]["image"] == "img:v1"

    def test_same_name_same_file_last_wins(self, tmp_path):
        """two distinct same-name endpoints in ONE file: last wins, no raise.

        Deliberately asymmetric with the cross-file raise: across files a
        duplicate name is ambiguous, but within one module dir() iteration is
        deterministic, so pinning the resolution is cheap and explicit.
        """
        _write_worker(
            tmp_path,
            "dups.py",
            """\
            from runpod_flash import Endpoint

            a = Endpoint(name="dup", image="img:v1")
            z = Endpoint(name="dup", image="img:v2")
            """,
        )
        scanner = RuntimeScanner(tmp_path)
        scanner.discover_remote_functions()
        assert len(scanner.client_endpoints) == 1
        # dir() iterates alphabetically, so z is seen last and overwrites a
        assert scanner.client_endpoints["dup"]["var_name"] == "z"
        assert scanner.client_endpoints["dup"]["image"] == "img:v2"
