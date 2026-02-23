"""Unit tests for dependency_resolver module.

Tests detection, stub generation, source assembly, and async resolution
of @remote function dependencies for stacked execution.
"""

import ast
import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runpod_flash.stubs.dependency_resolver import (
    RemoteDependency,
    build_augmented_source,
    detect_remote_dependencies,
    generate_stub_code,
    resolve_dependencies,
)


# ---------------------------------------------------------------------------
# Helpers: fake @remote-decorated functions for detection tests
# ---------------------------------------------------------------------------


def _make_remote_func(name: str, source: str, resource_config=None):
    """Create a fake function with __remote_config__ to simulate @remote."""
    ns: dict = {}
    exec(compile(source, "<test>", "exec"), ns)
    func = ns[name]
    func.__remote_config__ = {
        "resource_config": resource_config or MagicMock(name=name),
        "dependencies": ["numpy"],
        "system_dependencies": [],
    }
    return func


# Shared globals dict simulating a module where both funcA and funcB live
_shared_globals: dict = {}

_funcB_source = textwrap.dedent("""\
async def funcB(param: dict) -> dict:
    return {"result": param}
""")

_funcB = _make_remote_func("funcB", _funcB_source)
_shared_globals["funcB"] = _funcB

_funcC_source = textwrap.dedent("""\
async def funcC(x: int) -> int:
    return x + 1
""")
_funcC = _make_remote_func("funcC", _funcC_source)
_shared_globals["funcC"] = _funcC


def _plain_helper(x):
    """A plain function — no __remote_config__."""
    return x


_shared_globals["_plain_helper"] = _plain_helper


# funcA calls funcB (a @remote function) and _plain_helper (not @remote)
_funcA_source = textwrap.dedent("""\
async def funcA(foo: str) -> dict:
    payload = _plain_helper(foo)
    return await funcB(payload)
""")


# funcD calls both funcB and funcC
_funcD_source = textwrap.dedent("""\
async def funcD(data: str) -> dict:
    b = await funcB({"key": data})
    c = await funcC(42)
    return {"b": b, "c": c}
""")


# funcE calls nothing remote
_funcE_source = textwrap.dedent("""\
async def funcE(x: int) -> int:
    return x * 2
""")


# funcF calls funcB via attribute (indirect — should NOT be detected)
_funcF_source = textwrap.dedent("""\
async def funcF(x: int) -> int:
    import somemodule
    return somemodule.funcB(x)
""")


# ---------------------------------------------------------------------------
# Tests: detect_remote_dependencies
# ---------------------------------------------------------------------------


class TestDetectRemoteDependencies:
    def test_detects_single_remote_dependency(self):
        result = detect_remote_dependencies(_funcA_source, _shared_globals)
        assert result == ["funcB"]

    def test_detects_multiple_remote_dependencies(self):
        result = detect_remote_dependencies(_funcD_source, _shared_globals)
        assert sorted(result) == ["funcB", "funcC"]

    def test_no_remote_dependencies(self):
        result = detect_remote_dependencies(_funcE_source, _shared_globals)
        assert result == []

    def test_ignores_plain_helpers(self):
        result = detect_remote_dependencies(_funcA_source, _shared_globals)
        assert "_plain_helper" not in result

    def test_ignores_builtins(self):
        source = textwrap.dedent("""\
        async def funcX(x: int) -> str:
            return str(len([x]))
        """)
        result = detect_remote_dependencies(source, _shared_globals)
        assert result == []

    def test_ignores_attribute_calls(self):
        """Only ast.Name calls are detected, not ast.Attribute calls."""
        result = detect_remote_dependencies(_funcF_source, _shared_globals)
        assert "funcB" not in result

    def test_ignores_names_not_in_globals(self):
        source = textwrap.dedent("""\
        async def funcX(x: int) -> int:
            return unknown_func(x)
        """)
        result = detect_remote_dependencies(source, _shared_globals)
        assert result == []


# ---------------------------------------------------------------------------
# Tests: generate_stub_code
# ---------------------------------------------------------------------------


class TestGenerateStubCode:
    def _make_dep(self, name="funcB", endpoint_id="ep-123", source=None):
        return RemoteDependency(
            name=name,
            endpoint_id=endpoint_id,
            source=source or _funcB_source,
            dependencies=["numpy"],
            system_dependencies=[],
        )

    def test_generates_valid_python(self):
        dep = self._make_dep()
        code = generate_stub_code(dep)
        # Must compile without errors
        compile(code, "<stub>", "exec")

    def test_stub_defines_correct_function_name(self):
        dep = self._make_dep(name="funcB")
        code = generate_stub_code(dep)
        tree = ast.parse(code)
        func_names = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert "funcB" in func_names

    def test_stub_is_async(self):
        dep = self._make_dep()
        code = generate_stub_code(dep)
        tree = ast.parse(code)
        async_funcs = [
            node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)
        ]
        assert len(async_funcs) >= 1

    def test_endpoint_id_embedded(self):
        dep = self._make_dep(endpoint_id="ep-abc-999")
        code = generate_stub_code(dep)
        assert "ep-abc-999" in code

    def test_function_source_embedded(self):
        dep = self._make_dep()
        code = generate_stub_code(dep)
        # The original source should appear somewhere in the stub (as a string)
        assert "funcB" in code

    def test_preserves_original_signature(self):
        """Stub should accept same params as original function."""
        dep = self._make_dep()
        code = generate_stub_code(dep)
        # The stub for funcB(param: dict) should have 'param' in its signature
        assert "param" in code

    def test_handles_multi_param_function(self):
        multi_src = textwrap.dedent("""\
        async def multi(a: int, b: str, c: float = 1.0) -> dict:
            return {"a": a, "b": b, "c": c}
        """)
        dep = self._make_dep(name="multi", source=multi_src)
        code = generate_stub_code(dep)
        compile(code, "<stub>", "exec")
        assert "multi" in code

    def test_handles_triple_quotes_in_source(self):
        """Source with triple-quoted docstrings should be safely escaped."""
        src_with_docs = textwrap.dedent('''\
        async def documented(x: int) -> int:
            """Process x with triple-quoted docstring."""
            return x
        ''')
        dep = self._make_dep(name="documented", source=src_with_docs)
        code = generate_stub_code(dep)
        compile(code, "<stub>", "exec")


# ---------------------------------------------------------------------------
# Tests: build_augmented_source
# ---------------------------------------------------------------------------


class TestBuildAugmentedSource:
    def test_no_stubs_returns_original(self):
        original = "async def funcA(x): return x\n"
        result = build_augmented_source(original, [])
        assert result == original

    def test_stubs_prepended_before_original(self):
        original = "async def funcA(x): return x\n"
        stub = "async def funcB(y): return y\n"
        result = build_augmented_source(original, [stub])
        # stub should appear before original
        assert result.index("funcB") < result.index("funcA")

    def test_augmented_source_is_valid_python(self):
        original = textwrap.dedent("""\
        async def funcA(foo: str) -> dict:
            return await funcB(foo)
        """)
        stub = textwrap.dedent("""\
        async def funcB(param: dict) -> dict:
            return {"stub": True}
        """)
        result = build_augmented_source(original, [stub])
        compile(result, "<augmented>", "exec")

    def test_multiple_stubs_prepended(self):
        original = "async def funcA(x): return x\n"
        stubs = [
            "async def funcB(y): return y\n",
            "async def funcC(z): return z\n",
        ]
        result = build_augmented_source(original, stubs)
        assert "funcB" in result
        assert "funcC" in result
        assert result.index("funcB") < result.index("funcA")
        assert result.index("funcC") < result.index("funcA")


# ---------------------------------------------------------------------------
# Tests: resolve_dependencies (async, mocked ResourceManager)
# ---------------------------------------------------------------------------


class TestResolveDependencies:
    """Tests for resolve_dependencies with mocked ResourceManager and get_function_source."""

    def _patch_resolve(self, mock_rm):
        """Return combined patch context for ResourceManager and get_function_source."""
        return (
            patch(
                "runpod_flash.core.resources.ResourceManager",
                return_value=mock_rm,
            ),
            patch(
                "runpod_flash.stubs.dependency_resolver.get_function_source",
                side_effect=lambda func: (
                    f"async def {func.__name__}(): pass\n",
                    "hash",
                ),
            ),
        )

    @pytest.mark.asyncio
    async def test_resolves_single_dependency(self):
        mock_resource = MagicMock()
        mock_resource.id = "ep-resolved-123"

        mock_rm = MagicMock()
        mock_rm.get_or_deploy_resource = AsyncMock(return_value=mock_resource)

        rm_patch, gfs_patch = self._patch_resolve(mock_rm)
        with rm_patch, gfs_patch:
            deps = await resolve_dependencies(_funcA_source, _shared_globals)

        assert len(deps) == 1
        assert deps[0].name == "funcB"
        assert deps[0].endpoint_id == "ep-resolved-123"

    @pytest.mark.asyncio
    async def test_resolves_multiple_dependencies(self):
        mock_resource_b = MagicMock()
        mock_resource_b.id = "ep-b"
        mock_resource_c = MagicMock()
        mock_resource_c.id = "ep-c"

        async def mock_deploy(config):
            if config is _funcB.__remote_config__["resource_config"]:
                return mock_resource_b
            return mock_resource_c

        mock_rm = MagicMock()
        mock_rm.get_or_deploy_resource = AsyncMock(side_effect=mock_deploy)

        rm_patch, gfs_patch = self._patch_resolve(mock_rm)
        with rm_patch, gfs_patch:
            deps = await resolve_dependencies(_funcD_source, _shared_globals)

        assert len(deps) == 2
        names = {d.name for d in deps}
        assert names == {"funcB", "funcC"}

    @pytest.mark.asyncio
    async def test_no_dependencies_returns_empty(self):
        deps = await resolve_dependencies(_funcE_source, _shared_globals)
        assert deps == []

    @pytest.mark.asyncio
    async def test_provisioning_failure_raises(self):
        mock_rm = MagicMock()
        mock_rm.get_or_deploy_resource = AsyncMock(
            side_effect=RuntimeError("deploy failed")
        )

        rm_patch, gfs_patch = self._patch_resolve(mock_rm)
        with rm_patch, gfs_patch:
            with pytest.raises(RuntimeError, match="deploy failed"):
                await resolve_dependencies(_funcA_source, _shared_globals)


# ---------------------------------------------------------------------------
# Tests: exec() integration — verify augmented source works at runtime
# ---------------------------------------------------------------------------


class TestExecIntegration:
    def test_exec_augmented_source_defines_both_functions(self):
        """When we exec() augmented source, both funcA and the funcB stub exist."""
        dep = RemoteDependency(
            name="funcB",
            endpoint_id="ep-test",
            source=_funcB_source,
            dependencies=[],
            system_dependencies=[],
        )
        stub_code = generate_stub_code(dep)
        augmented = build_augmented_source(_funcA_source, [stub_code])

        namespace: dict = {"_plain_helper": lambda x: x}
        exec(compile(augmented, "<test>", "exec"), namespace)

        assert "funcA" in namespace
        assert "funcB" in namespace
        assert callable(namespace["funcA"])
        assert callable(namespace["funcB"])
