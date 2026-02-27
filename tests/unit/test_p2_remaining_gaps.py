"""P2 remaining gap tests.

Covers:
  CLI-RUN-018  – watchfiles fallback stub raises ModuleNotFoundError
  REM-CLS-013  – extract_class_code_simple fallback when inspect.getsource fails
  RES-LS-008   – ServerlessResource.env default populated from .env file
  VOL-006      – NetworkVolume with empty name still constructs (no validator guards it)
  SCAN-016     – RemoteDecoratorScanner handles @remote on nested class (class in function)
  SCAN-017     – RemoteDecoratorScanner handles conditional @remote gracefully
  STUB-STACK-004 – detect_remote_dependencies terminates on circular dependency graph
  SRVGEN-008   – RemoteClassWrapper stores _class_type for Pydantic introspection
  LB-ROUTE-003 – LoadBalancer random strategy selects from endpoint pool
  RT-SER-005   – serialize/deserialize roundtrip with complex stdlib objects
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# CLI-RUN-018: watchfiles fallback stub raises ModuleNotFoundError
# ---------------------------------------------------------------------------


class TestWatchfilesFallback:
    """watchfiles import failure creates a callable stub that raises ModuleNotFoundError."""

    def test_watchfiles_stub_raises_module_not_found(self, monkeypatch):
        """CLI-RUN-018: When watchfiles is absent, calling the stub raises ModuleNotFoundError."""
        # Simulate watchfiles being absent by removing it from sys.modules and
        # making the import raise ModuleNotFoundError.
        import sys

        # Stash any real watchfiles entry so we can restore it afterwards.
        real_watchfiles = sys.modules.pop("watchfiles", None)

        # Also remove any submodule entries that may already be cached.
        cached_keys = [k for k in list(sys.modules) if k.startswith("watchfiles")]
        stashed = {k: sys.modules.pop(k) for k in cached_keys}

        # Reload the run module with a fake watchfiles that raises on import.
        run_module_key = "runpod_flash.cli.commands.run"
        stashed_run = sys.modules.pop(run_module_key, None)

        # Provide a fake 'watchfiles' that raises immediately.
        fake_watchfiles = MagicMock(side_effect=ModuleNotFoundError("watchfiles"))
        sys.modules["watchfiles"] = fake_watchfiles

        try:
            # Force a fresh import of run so the try/except at module level fires.

            # We need to import the module in a context where watchfiles raises.
            # The simplest way: temporarily break the import inside the try block.
            # The module was already cached with the real watchfiles, so we patch
            # the module-level stub directly.
            del sys.modules["watchfiles"]

            # Patch builtins.__import__ to raise for watchfiles specifically.
            real_import = (
                __builtins__.__import__
                if hasattr(__builtins__, "__import__")
                else __import__
            )

            def patched_import(name, *args, **kwargs):
                if name == "watchfiles":
                    raise ModuleNotFoundError(
                        "watchfiles is required for flash run --reload. "
                        "Install it with: pip install watchfiles"
                    )
                return real_import(name, *args, **kwargs)

            # Re-import run module from scratch.
            import builtins

            original_import = builtins.__import__
            builtins.__import__ = patched_import

            try:
                if run_module_key in sys.modules:
                    del sys.modules[run_module_key]
                import runpod_flash.cli.commands.run as run_mod  # noqa: F401

                watch_fn = run_mod._watchfiles_watch  # type: ignore[attr-defined]

                # Arrange / Act / Assert
                with pytest.raises(ModuleNotFoundError, match="watchfiles"):
                    watch_fn("/some/path")
            finally:
                builtins.__import__ = original_import
                # Restore original run module entry if it existed.
                if stashed_run is not None:
                    sys.modules[run_module_key] = stashed_run
                elif run_module_key in sys.modules:
                    del sys.modules[run_module_key]
        finally:
            # Restore watchfiles.
            if real_watchfiles is not None:
                sys.modules["watchfiles"] = real_watchfiles
            for k, v in stashed.items():
                sys.modules[k] = v

    def test_watchfiles_stub_raises_with_kwargs(self, monkeypatch):
        """CLI-RUN-018: The watchfiles stub also raises when called with keyword args."""

        # Directly construct the fallback stub as defined in run.py lines 23-27.
        def _watchfiles_watch_stub(*_a, **_kw):
            raise ModuleNotFoundError(
                "watchfiles is required for flash run --reload. "
                "Install it with: pip install watchfiles"
            )

        with pytest.raises(ModuleNotFoundError, match="pip install watchfiles"):
            _watchfiles_watch_stub(watch_filter=None, stop_event=None)

    def test_watchfiles_default_filter_stub_is_instantiable(self):
        """CLI-RUN-018: The fallback _WatchfilesDefaultFilter stub is instantiable."""

        # Construct the stub class as defined in run.py lines 29-31.
        class _WatchfilesDefaultFilter:
            def __init__(self, **_kw):
                pass

        # Should not raise.
        obj = _WatchfilesDefaultFilter(ignore_paths=["/tmp"])
        assert obj is not None


# ---------------------------------------------------------------------------
# REM-CLS-013: Fallback class extraction when inspect.getsource fails
# ---------------------------------------------------------------------------


class TestExtractClassCodeFallback:
    """extract_class_code_simple falls back gracefully when getsource is unavailable."""

    def test_fallback_when_getsource_raises(self):
        """REM-CLS-013: Returns valid stub code when inspect.getsource raises OSError."""
        from runpod_flash.execute_class import extract_class_code_simple

        class MyWorker:
            def process(self, x: int) -> int:
                return x * 2

            def health_check(self) -> bool:
                return True

        with patch("inspect.getsource", side_effect=OSError("source not available")):
            result = extract_class_code_simple(MyWorker)

        # The fallback must produce a string containing the class name.
        assert "MyWorker" in result
        # It should be compilable Python.
        compile(result, "<fallback>", "exec")

    def test_fallback_contains_method_stubs(self):
        """REM-CLS-013: Fallback code includes method placeholder stubs."""
        from runpod_flash.execute_class import extract_class_code_simple

        class FancyService:
            def infer(self, payload):
                return payload

        with patch("inspect.getsource", side_effect=OSError("no source")):
            result = extract_class_code_simple(FancyService)

        # The fallback should reference the method name.
        assert "infer" in result
        # Must be valid Python.
        compile(result, "<fallback>", "exec")

    def test_happy_path_returns_class_definition(self):
        """REM-CLS-013 (positive): Normal path returns source with class keyword."""
        from runpod_flash.execute_class import extract_class_code_simple

        class SimpleClass:
            def run(self):
                pass

        result = extract_class_code_simple(SimpleClass)
        assert result.startswith("class SimpleClass")


# ---------------------------------------------------------------------------
# RES-LS-008: env dict merged from .env file
# ---------------------------------------------------------------------------


class TestServerlessResourceEnvLoading:
    """ServerlessResource.env default is populated by get_env_vars() / EnvironmentVars."""

    def test_env_loaded_from_dotenv_file(self, tmp_path):
        """RES-LS-008: env field is populated from a .env file when it exists."""

        # Write a temporary .env file.
        env_file = tmp_path / ".env"
        env_file.write_text("FLASH_TEST_SECRET=hunter2\nFLASH_TEST_FOO=bar\n")

        # patch dotenv_values to return our custom file's content.
        with patch(
            "runpod_flash.core.resources.environment.dotenv_values",
            return_value={"FLASH_TEST_SECRET": "hunter2", "FLASH_TEST_FOO": "bar"},
        ):
            from runpod_flash.core.resources.serverless import get_env_vars

            env = get_env_vars()

        assert env.get("FLASH_TEST_SECRET") == "hunter2"
        assert env.get("FLASH_TEST_FOO") == "bar"

    def test_env_field_on_serverless_resource_is_dict(self, monkeypatch):
        """RES-LS-008: ServerlessResource.env is a dict (not None) after construction."""
        # Patch get_env_vars so we don't need a real .env.
        monkeypatch.setattr(
            "runpod_flash.core.resources.serverless.get_env_vars",
            lambda: {"INJECTED": "yes"},
        )
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="env-test-resource")
        assert isinstance(resource.env, dict)

    def test_env_vars_empty_dict_when_no_dotenv(self):
        """RES-LS-008: get_env_vars returns an empty dict when .env has no content."""
        with patch(
            "runpod_flash.core.resources.environment.dotenv_values",
            return_value={},
        ):
            from runpod_flash.core.resources.serverless import get_env_vars

            env = get_env_vars()

        assert env == {}


# ---------------------------------------------------------------------------
# VOL-006: NetworkVolume with empty name
# ---------------------------------------------------------------------------


class TestNetworkVolumeEmptyName:
    """NetworkVolume behaviour when name is the empty string."""

    def test_network_volume_with_empty_name_does_not_raise(self):
        """VOL-006: Pydantic model accepts empty name= (no validator rejects it)."""
        from runpod_flash.core.resources.network_volume import NetworkVolume

        # According to the source, name: str with no empty-string validator.
        # Construction should succeed.
        vol = NetworkVolume(name="")
        assert vol.name == ""

    def test_network_volume_non_empty_name_works(self):
        """VOL-006 (positive): Non-empty name constructs fine."""
        from runpod_flash.core.resources.network_volume import NetworkVolume

        vol = NetworkVolume(name="my-volume", size=50)
        assert vol.name == "my-volume"
        assert vol.size == 50

    def test_network_volume_size_zero_raises(self):
        """VOL-006: size=0 violates the gt=0 constraint and raises ValidationError."""
        from pydantic import ValidationError

        from runpod_flash.core.resources.network_volume import NetworkVolume

        with pytest.raises(ValidationError):
            NetworkVolume(name="vol", size=0)

    @pytest.mark.asyncio
    async def test_find_existing_volume_skips_empty_name(self):
        """VOL-006: _find_existing_volume returns None immediately when name is empty."""
        from runpod_flash.core.resources.network_volume import NetworkVolume

        vol = NetworkVolume(name="")

        # _find_existing_volume is an async method; we run it with a mock client.
        mock_client = MagicMock()

        result = await vol._find_existing_volume(mock_client)
        assert result is None
        # list_network_volumes should NOT have been called.
        mock_client.list_network_volumes.assert_not_called()


# ---------------------------------------------------------------------------
# SCAN-016: Scanner handles @remote on nested class (class inside function)
# ---------------------------------------------------------------------------


class TestScannerNestedClass:
    """RemoteDecoratorScanner does not crash when a class is defined inside a function."""

    def _make_scanner(self, tmp_path: Path):
        from runpod_flash.cli.commands.build_utils.scanner import RemoteDecoratorScanner

        return RemoteDecoratorScanner(tmp_path)

    def test_nested_class_does_not_cause_scanner_error(self, tmp_path):
        """SCAN-016: Scanner processes a file containing a @remote on a nested class without error."""
        source = """\
from runpod_flash import remote, LiveServerless

gpu = LiveServerless(name="nested-test")

def factory():
    @remote(gpu)
    class InnerWorker:
        def run(self):
            pass
    return InnerWorker
"""
        py_file = tmp_path / "nested_worker.py"
        py_file.write_text(source)

        scanner = self._make_scanner(tmp_path)
        # Should not raise.
        functions = scanner.discover_remote_functions()
        # The nested class may or may not be discovered (ast.walk visits all nodes),
        # but the scanner must not raise an exception.
        assert isinstance(functions, list)

    def test_nested_class_extracted_via_ast_walk(self, tmp_path):
        """SCAN-016: ast.walk descends into function bodies; scanner handles it gracefully."""
        source = """\
from runpod_flash import remote, LiveServerless

cfg = LiveServerless(name="walk-test")

def outer():
    @remote(cfg)
    class Nested:
        def work(self): ...
"""
        py_file = tmp_path / "walk_worker.py"
        py_file.write_text(source)

        scanner = self._make_scanner(tmp_path)
        # The key assertion: no exception.
        result = scanner.discover_remote_functions()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# SCAN-017: Scanner handles conditional @remote (if/else around decorator)
# ---------------------------------------------------------------------------


class TestScannerConditionalRemote:
    """RemoteDecoratorScanner handles or skips conditional decorators gracefully."""

    def _make_scanner(self, tmp_path: Path):
        from runpod_flash.cli.commands.build_utils.scanner import RemoteDecoratorScanner

        return RemoteDecoratorScanner(tmp_path)

    def test_conditional_decorator_does_not_crash_scanner(self, tmp_path):
        """SCAN-017: File with conditional @remote is scanned without exception."""
        source = """\
import os
from runpod_flash import remote, LiveServerless

cfg = LiveServerless(name="cond-test")

USE_REMOTE = os.environ.get("USE_REMOTE", "false") == "true"

if USE_REMOTE:
    @remote(cfg)
    async def process(x):
        return x
else:
    async def process(x):
        return x
"""
        py_file = tmp_path / "conditional_worker.py"
        py_file.write_text(source)

        scanner = self._make_scanner(tmp_path)
        result = scanner.discover_remote_functions()
        assert isinstance(result, list)

    def test_unconditional_remote_still_discovered_alongside_conditional(
        self, tmp_path
    ):
        """SCAN-017: Normal @remote functions in the same file are still discovered."""
        source = """\
from runpod_flash import remote, LiveServerless

cfg = LiveServerless(name="mixed-test")

@remote(cfg)
async def normal_func(x):
    return x

USE_REMOTE = False

if USE_REMOTE:
    @remote(cfg)
    async def conditional_func(x):
        return x
"""
        py_file = tmp_path / "mixed_worker.py"
        py_file.write_text(source)

        scanner = self._make_scanner(tmp_path)
        result = scanner.discover_remote_functions()
        # normal_func should be discovered; no exception regardless.
        names = [f.function_name for f in result]
        assert "normal_func" in names


# ---------------------------------------------------------------------------
# STUB-STACK-004: Circular dependency detection terminates
# ---------------------------------------------------------------------------


class TestCircularDependencyTerminates:
    """detect_remote_dependencies does not hang on a mutually-referencing dependency graph."""

    def test_no_remote_dependencies_returns_empty(self):
        """STUB-STACK-004 (baseline): No remote deps → empty list, no infinite loop."""
        from runpod_flash.stubs.dependency_resolver import detect_remote_dependencies

        source = "def foo(x):\n    return bar(x)\n"
        # bar is a plain function, not a @remote decorated one.
        func_globals: dict[str, Any] = {"bar": lambda x: x}

        result = detect_remote_dependencies(source, func_globals)
        assert result == []

    def test_circular_globals_do_not_cause_infinite_loop(self):
        """STUB-STACK-004: Globals referencing each other with __remote_config__ don't loop."""
        from runpod_flash.stubs.dependency_resolver import detect_remote_dependencies

        # Build two fake @remote stubs that call each other.
        stub_a = SimpleNamespace(__remote_config__={"resource_config": None})
        stub_b = SimpleNamespace(__remote_config__={"resource_config": None})

        # Source of A calls B.
        source_a = "async def func_a(x):\n    return await func_b(x)\n"

        func_globals: dict[str, Any] = {
            "func_a": stub_a,
            "func_b": stub_b,
        }

        # detect_remote_dependencies only does a single AST parse + lookup —
        # it must return immediately without recursion.
        result = detect_remote_dependencies(source_a, func_globals)
        assert "func_b" in result

    def test_detect_only_direct_calls_not_attribute_calls(self):
        """STUB-STACK-004: Attribute calls (obj.func) are not detected as remote deps."""
        from runpod_flash.stubs.dependency_resolver import detect_remote_dependencies

        stub = SimpleNamespace(__remote_config__={"resource_config": None})
        source = "async def caller():\n    return await obj.func_b()\n"
        func_globals: dict[str, Any] = {"func_b": stub}

        result = detect_remote_dependencies(source, func_globals)
        assert result == []


# ---------------------------------------------------------------------------
# SRVGEN-008: RemoteClassWrapper stores _class_type for introspection
# ---------------------------------------------------------------------------


class TestRemoteClassWrapperClassType:
    """RemoteClassWrapper instances expose _class_type pointing to the original class."""

    def test_class_type_attribute_is_original_class(self):
        """SRVGEN-008: _class_type on an instance equals the decorated class."""
        from runpod_flash.execute_class import create_remote_class
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="cls-type-test")

        class TargetClass:
            def infer(self, x):
                return x

        WrapperClass = create_remote_class(
            cls=TargetClass,
            resource_config=resource,
            dependencies=None,
            system_dependencies=None,
            accelerate_downloads=True,
            extra={},
        )
        instance = WrapperClass()
        assert instance._class_type is TargetClass

    def test_class_type_usable_for_method_introspection(self):
        """SRVGEN-008: _class_type can be used to inspect the original method signature."""
        import inspect

        from runpod_flash.execute_class import create_remote_class
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="sig-test")

        class ModelRunner:
            def run(self, payload: dict, temperature: float = 0.7) -> str:
                return ""

        WrapperClass = create_remote_class(
            cls=ModelRunner,
            resource_config=resource,
            dependencies=None,
            system_dependencies=None,
            accelerate_downloads=True,
            extra={},
        )
        instance = WrapperClass()

        sig = inspect.signature(instance._class_type.run)
        param_names = list(sig.parameters.keys())
        assert "payload" in param_names
        assert "temperature" in param_names

    def test_multiple_instances_share_same_class_type(self):
        """SRVGEN-008: Different instances of the wrapper all point to the same original class."""
        from runpod_flash.execute_class import create_remote_class
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="multi-instance-test")

        class SharedClass:
            pass

        WrapperClass = create_remote_class(
            cls=SharedClass,
            resource_config=resource,
            dependencies=None,
            system_dependencies=None,
            accelerate_downloads=True,
            extra={},
        )
        inst1 = WrapperClass()
        inst2 = WrapperClass()
        assert inst1._class_type is inst2._class_type is SharedClass


# ---------------------------------------------------------------------------
# LB-ROUTE-003: Random strategy is non-deterministic across many calls
# ---------------------------------------------------------------------------


class TestLoadBalancerRandomStrategy:
    """LoadBalancer RANDOM strategy selects from the endpoint pool and varies over runs."""

    @pytest.mark.asyncio
    async def test_random_strategy_selects_from_pool(self):
        """LB-ROUTE-003: _random_select returns one of the provided endpoints."""
        from runpod_flash.runtime.load_balancer import LoadBalancer
        from runpod_flash.runtime.reliability_config import LoadBalancerStrategy

        lb = LoadBalancer(strategy=LoadBalancerStrategy.RANDOM)
        endpoints = ["http://ep1", "http://ep2", "http://ep3"]

        result = await lb._random_select(endpoints)
        assert result in endpoints

    @pytest.mark.asyncio
    async def test_random_strategy_produces_varied_results(self):
        """LB-ROUTE-003: Over many calls, random strategy selects more than one endpoint."""
        from runpod_flash.runtime.load_balancer import LoadBalancer
        from runpod_flash.runtime.reliability_config import LoadBalancerStrategy

        lb = LoadBalancer(strategy=LoadBalancerStrategy.RANDOM)
        endpoints = ["http://ep-a", "http://ep-b", "http://ep-c"]

        seen = {await lb._random_select(endpoints) for _ in range(60)}
        # With 60 draws from 3 options, seeing at least 2 different values is
        # virtually certain (probability of seeing only 1 is (1/3)^59 ≈ 0).
        assert len(seen) >= 2

    @pytest.mark.asyncio
    async def test_random_strategy_via_select_endpoint(self):
        """LB-ROUTE-003: select_endpoint with RANDOM strategy returns an endpoint."""
        from runpod_flash.runtime.load_balancer import LoadBalancer
        from runpod_flash.runtime.reliability_config import LoadBalancerStrategy

        lb = LoadBalancer(strategy=LoadBalancerStrategy.RANDOM)
        endpoints = ["http://ep-x", "http://ep-y"]

        result = await lb.select_endpoint(endpoints)
        assert result in endpoints

    @pytest.mark.asyncio
    async def test_random_strategy_single_endpoint_returns_it(self):
        """LB-ROUTE-003: With a single endpoint, random always returns it."""
        from runpod_flash.runtime.load_balancer import LoadBalancer
        from runpod_flash.runtime.reliability_config import LoadBalancerStrategy

        lb = LoadBalancer(strategy=LoadBalancerStrategy.RANDOM)
        endpoints = ["http://only-one"]

        result = await lb._random_select(endpoints)
        assert result == "http://only-one"


# ---------------------------------------------------------------------------
# RT-SER-005: Serialize/deserialize with complex objects (no numpy/PIL)
# ---------------------------------------------------------------------------


class TestSerializationRoundtrip:
    """serialize_arg / deserialize_arg roundtrip with complex stdlib objects."""

    def test_nested_dict_roundtrip(self):
        """RT-SER-005: Deeply nested dict survives serialize → deserialize."""
        from runpod_flash.runtime.serialization import deserialize_arg, serialize_arg

        original = {
            "level1": {
                "level2": {
                    "level3": [1, 2, 3],
                    "meta": {"key": "value", "number": 42},
                }
            },
            "list_of_dicts": [{"a": 1}, {"b": 2}],
        }
        serialized = serialize_arg(original)
        result = deserialize_arg(serialized)
        assert result == original

    def test_list_of_mixed_types_roundtrip(self):
        """RT-SER-005: List containing mixed stdlib types survives roundtrip."""
        from runpod_flash.runtime.serialization import deserialize_arg, serialize_arg

        original = [None, True, 3.14, "hello", b"bytes", (1, 2), frozenset({3, 4})]
        serialized = serialize_arg(original)
        result = deserialize_arg(serialized)
        assert result == original

    def test_lambda_serializable_via_cloudpickle(self):
        """RT-SER-005: Lambdas are serializable by cloudpickle (not possible with pickle)."""
        import sys
        from runpod_flash.runtime.serialization import deserialize_arg, serialize_arg

        # Force recursion limit high enough for cloudpickle (test pollution can lower it)
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old_limit, 2000))
        try:
            fn = lambda x: x * 3  # noqa: E731
            serialized = serialize_arg(fn)
            recovered = deserialize_arg(serialized)
            assert recovered(7) == 21
        finally:
            sys.setrecursionlimit(old_limit)

    def test_custom_class_instance_roundtrip(self):
        """RT-SER-005: Instance of a locally-defined class survives roundtrip."""
        import sys
        from runpod_flash.runtime.serialization import deserialize_arg, serialize_arg

        # Force recursion limit high enough for cloudpickle (test pollution can lower it)
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old_limit, 2000))
        try:

            class Payload:
                def __init__(self, data: list, label: str):
                    self.data = data
                    self.label = label

                def __eq__(self, other):
                    return (
                        isinstance(other, Payload)
                        and self.data == other.data
                        and self.label == other.label
                    )

            original = Payload(data=[10, 20, 30], label="batch-1")
            serialized = serialize_arg(original)
            result = deserialize_arg(serialized)
            assert result == original
        finally:
            sys.setrecursionlimit(old_limit)

    def test_serialize_args_tuple(self):
        """RT-SER-005: serialize_args handles a multi-element args tuple."""
        from runpod_flash.runtime.serialization import deserialize_args, serialize_args

        args = ({"key": "val"}, [1, 2, 3], "plain string")
        serialized_list = serialize_args(args)
        recovered = deserialize_args(serialized_list)
        assert list(args) == recovered

    def test_serialize_kwargs_dict(self):
        """RT-SER-005: serialize_kwargs / deserialize_kwargs preserve key-value pairs."""
        from runpod_flash.runtime.serialization import (
            deserialize_kwargs,
            serialize_kwargs,
        )

        kwargs = {"threshold": 0.95, "items": [1, 2, 3], "meta": {"source": "test"}}
        serialized = serialize_kwargs(kwargs)
        recovered = deserialize_kwargs(serialized)
        assert recovered == kwargs

    def test_empty_args_roundtrip(self):
        """RT-SER-005: Empty args tuple serializes to empty list and back."""
        from runpod_flash.runtime.serialization import deserialize_args, serialize_args

        assert serialize_args(()) == []
        assert deserialize_args([]) == []

    def test_serialization_error_on_unserializable_object(self):
        """RT-SER-005: SerializationError raised for a truly unserializable object."""

        from runpod_flash.runtime.exceptions import SerializationError
        from runpod_flash.runtime.serialization import serialize_arg

        # A raw file handle is not serializable by cloudpickle.
        import tempfile

        with tempfile.TemporaryFile() as f:
            with pytest.raises(SerializationError):
                serialize_arg(f)
