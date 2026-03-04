"""Integration tests for cross-endpoint dependency resolution in stubs.

These tests verify the FULL pipeline that flows through the stubs when a
@remote function calls another @remote function — particularly via in-body
imports (the bug fixed in PR #224).

Covers blind spots:
- STUB-STACK-005: In-body `from X import Y` imports resolved by stubs
- STUB-STACK-006: Stub source augmented with dispatch stubs after stripping imports
- STUB-LS-007:    Cache key recomputed when dependencies change
- LiveServerlessStub.prepare_request integration (not mocking resolve_dependencies)
- LoadBalancerSlsStub._prepare_request integration (not mocking resolve_dependencies)
"""

import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runpod_flash.stubs.dependency_resolver import RemoteDependency
from runpod_flash.stubs.live_serverless import (
    LiveServerlessStub,
    _SERIALIZED_FUNCTION_CACHE,
)
from runpod_flash.stubs.load_balancer_sls import LoadBalancerSlsStub


@pytest.fixture(autouse=True)
def clear_function_cache():
    """Clear the function cache between tests."""
    _SERIALIZED_FUNCTION_CACHE.clear()
    yield
    _SERIALIZED_FUNCTION_CACHE.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_remote_func(name, source, resource_config=None):
    """Create a function object with __remote_config__ to simulate @remote."""
    ns: dict = {}
    exec(compile(source, "<test>", "exec"), ns)
    func = ns[name]
    func.__remote_config__ = {
        "resource_config": resource_config or MagicMock(name=name),
        "dependencies": ["numpy"],
        "system_dependencies": [],
    }
    return func


_gpu_inference_source = textwrap.dedent("""\
async def gpu_inference(payload: dict) -> dict:
    return {"result": payload}
""")


# ---------------------------------------------------------------------------
# STUB-STACK-005: In-body imports resolved by LiveServerlessStub
# ---------------------------------------------------------------------------
class TestLiveServerlessStubInBodyImports:
    """Verify LiveServerlessStub.prepare_request resolves in-body @remote imports.

    This is the integration path that was broken before PR #224:
    1. User writes: `from gpu_worker import gpu_inference` inside function body
    2. `gpu_inference` is NOT in `func.__globals__`
    3. `resolve_in_function_imports` must discover it
    4. `detect_remote_dependencies` finds it in augmented globals
    5. `strip_remote_imports` removes the stale import
    6. `generate_stub_code` + `build_augmented_source` inject the dispatch stub
    """

    @pytest.mark.asyncio
    async def test_prepare_request_resolves_in_body_import(self):
        """prepare_request detects @remote dep imported inside function body."""
        mock_server = MagicMock()
        stub = LiveServerlessStub(mock_server)

        # Create a function that imports a @remote function inside its body.
        # We define the function in a way that inspect.getsource works.
        gpu_func = _make_remote_func("gpu_inference", _gpu_inference_source)

        # The calling function — gpu_inference is NOT in its __globals__
        def classify(text: str) -> dict:
            from gpu_worker import gpu_inference  # noqa: F401

            return gpu_inference({"text": text})

        # Mock resolve_in_function_imports to simulate finding gpu_inference
        # in the in-body import (we can't actually import gpu_worker)
        mock_resource = MagicMock()
        mock_resource.id = "ep-gpu-123"
        mock_rm = MagicMock()
        mock_rm.get_or_deploy_resource = AsyncMock(return_value=mock_resource)

        with (
            patch(
                "runpod_flash.stubs.dependency_resolver.resolve_in_function_imports",
                return_value={**classify.__globals__, "gpu_inference": gpu_func},
            ),
            patch(
                "runpod_flash.core.resources.ResourceManager",
                return_value=mock_rm,
            ),
            patch(
                "runpod_flash.stubs.dependency_resolver.get_function_source",
                return_value=(_gpu_inference_source, "hash"),
            ),
        ):
            request = await stub.prepare_request(classify, [], [], True, "hello")

        # The augmented source should contain the dispatch stub for gpu_inference
        assert "gpu_inference" in request.function_code
        assert "ep-gpu-123" in request.function_code
        # Original import should be stripped
        assert "from gpu_worker import" not in request.function_code

    @pytest.mark.asyncio
    async def test_prepare_request_without_deps_skips_augmentation(self):
        """When no @remote deps found, source is not augmented."""
        mock_server = MagicMock()
        stub = LiveServerlessStub(mock_server)

        def simple_func(x: int) -> int:
            return x * 2

        with patch(
            "runpod_flash.stubs.dependency_resolver.resolve_dependencies",
            new_callable=AsyncMock,
            return_value=[],
        ):
            request = await stub.prepare_request(simple_func, [], [], True, 5)

        assert "simple_func" in request.function_code
        assert "ep-" not in request.function_code  # No endpoint stubs injected


# ---------------------------------------------------------------------------
# STUB-STACK-005: In-body imports resolved by LoadBalancerSlsStub
# ---------------------------------------------------------------------------
class TestLoadBalancerSlsStubInBodyImports:
    """Verify LoadBalancerSlsStub._prepare_request resolves in-body @remote imports."""

    @pytest.mark.asyncio
    async def test_prepare_request_resolves_in_body_import(self):
        """_prepare_request detects @remote dep imported inside function body."""
        mock_server = MagicMock()
        stub = LoadBalancerSlsStub(mock_server)

        gpu_func = _make_remote_func("gpu_inference", _gpu_inference_source)

        def classify(text: str) -> dict:
            from gpu_worker import gpu_inference  # noqa: F401

            return gpu_inference({"text": text})

        mock_resource = MagicMock()
        mock_resource.id = "ep-gpu-456"
        mock_rm = MagicMock()
        mock_rm.get_or_deploy_resource = AsyncMock(return_value=mock_resource)

        with (
            patch(
                "runpod_flash.stubs.dependency_resolver.resolve_in_function_imports",
                return_value={**classify.__globals__, "gpu_inference": gpu_func},
            ),
            patch(
                "runpod_flash.core.resources.ResourceManager",
                return_value=mock_rm,
            ),
            patch(
                "runpod_flash.stubs.dependency_resolver.get_function_source",
                return_value=(_gpu_inference_source, "hash"),
            ),
        ):
            request = await stub._prepare_request(classify, [], [], True, "hello")

        assert "gpu_inference" in request["function_code"]
        assert "ep-gpu-456" in request["function_code"]
        assert "from gpu_worker import" not in request["function_code"]

    @pytest.mark.asyncio
    async def test_prepare_request_without_deps_no_augmentation(self):
        """When no @remote deps, LB stub source is not augmented."""
        mock_server = MagicMock()
        stub = LoadBalancerSlsStub(mock_server)

        def simple_func(x: int) -> int:
            return x * 2

        with patch(
            "runpod_flash.stubs.dependency_resolver.resolve_dependencies",
            new_callable=AsyncMock,
            return_value=[],
        ):
            request = await stub._prepare_request(simple_func, [], [], True, 5)

        assert "simple_func" in request["function_code"]
        assert "ep-" not in request["function_code"]


# ---------------------------------------------------------------------------
# STUB-STACK-006: Augmented source is valid Python in exec() namespace
# ---------------------------------------------------------------------------
class TestAugmentedSourceExecIntegration:
    """Verify the full strip → stub → augment pipeline produces executable code."""

    def test_stripped_and_augmented_source_runs_in_exec(self):
        """After stripping in-body import and injecting stub, exec() works."""
        from runpod_flash.stubs.dependency_resolver import (
            build_augmented_source,
            generate_stub_code,
            strip_remote_imports,
        )

        # Source with in-body import (the pattern that broke before PR #224)
        source_with_import = textwrap.dedent("""\
        async def classify(text: str) -> dict:
            from gpu_worker import gpu_inference
            return await gpu_inference({"text": text})
        """)

        dep = RemoteDependency(
            name="gpu_inference",
            endpoint_id="ep-test-789",
            source=_gpu_inference_source,
            dependencies=["torch"],
            system_dependencies=[],
        )

        # Run the full pipeline
        stripped = strip_remote_imports(source_with_import, {"gpu_inference"})
        stub_code = generate_stub_code(dep)
        augmented = build_augmented_source(stripped, [stub_code])

        # Must compile
        compiled = compile(augmented, "<test>", "exec")

        # Must define both functions in exec namespace
        namespace: dict = {}
        exec(compiled, namespace)
        assert "classify" in namespace
        assert "gpu_inference" in namespace
        assert callable(namespace["classify"])
        assert callable(namespace["gpu_inference"])

    def test_multiple_in_body_imports_all_resolved(self):
        """Multiple in-body @remote imports all get stubs injected."""
        from runpod_flash.stubs.dependency_resolver import (
            build_augmented_source,
            generate_stub_code,
            strip_remote_imports,
        )

        source = textwrap.dedent("""\
        async def pipeline(data: dict) -> dict:
            from cpu_worker import preprocess
            from gpu_worker import inference
            cleaned = await preprocess(data)
            return await inference(cleaned)
        """)

        dep_preprocess = RemoteDependency(
            name="preprocess",
            endpoint_id="ep-cpu-001",
            source="async def preprocess(data: dict) -> dict:\n    return data\n",
            dependencies=[],
            system_dependencies=[],
        )
        dep_inference = RemoteDependency(
            name="inference",
            endpoint_id="ep-gpu-001",
            source="async def inference(data: dict) -> dict:\n    return data\n",
            dependencies=["torch"],
            system_dependencies=[],
        )

        stripped = strip_remote_imports(source, {"preprocess", "inference"})
        stubs = [generate_stub_code(dep_preprocess), generate_stub_code(dep_inference)]
        augmented = build_augmented_source(stripped, stubs)

        namespace: dict = {}
        exec(compile(augmented, "<test>", "exec"), namespace)
        assert "pipeline" in namespace
        assert "preprocess" in namespace
        assert "inference" in namespace

    def test_partial_import_keeps_non_remote_names(self):
        """When import has both @remote and non-remote names, only remote is stripped."""
        from runpod_flash.stubs.dependency_resolver import (
            build_augmented_source,
            generate_stub_code,
            strip_remote_imports,
        )

        source = textwrap.dedent("""\
        async def classify(text: str) -> dict:
            from worker import gpu_inference, tokenize
            tokens = tokenize(text)
            return await gpu_inference({"tokens": tokens})
        """)

        dep = RemoteDependency(
            name="gpu_inference",
            endpoint_id="ep-gpu-partial",
            source=_gpu_inference_source,
            dependencies=[],
            system_dependencies=[],
        )

        stripped = strip_remote_imports(source, {"gpu_inference"})
        stub_code = generate_stub_code(dep)
        augmented = build_augmented_source(stripped, [stub_code])

        # tokenize import should be preserved
        assert "from worker import tokenize" in augmented
        # gpu_inference should come from the stub, not the import
        assert "ep-gpu-partial" in augmented

        compiled = compile(augmented, "<test>", "exec")
        namespace: dict = {}
        exec(compiled, namespace)
        assert "classify" in namespace
        assert "gpu_inference" in namespace


# ---------------------------------------------------------------------------
# STUB-LS-007: Cache key recomputed when dependencies change
# ---------------------------------------------------------------------------
class TestCacheKeyRecomputedWithDeps:
    """Verify that LiveServerlessStub cache key changes when deps change."""

    @pytest.mark.asyncio
    async def test_cache_key_changes_with_different_deps(self):
        """Same function with different resolved deps gets different cache keys."""
        mock_server = MagicMock()
        stub = LiveServerlessStub(mock_server)

        def my_func(x: int) -> int:
            return x * 2

        # First call: no dependencies
        with patch(
            "runpod_flash.stubs.dependency_resolver.resolve_dependencies",
            new_callable=AsyncMock,
            return_value=[],
        ):
            await stub.prepare_request(my_func, [], [], True, 1)

        assert len(_SERIALIZED_FUNCTION_CACHE) == 1
        hash1 = list(_SERIALIZED_FUNCTION_CACHE.keys())[0]

        # Second call: WITH a dependency (simulates config change)
        dep = RemoteDependency(
            name="helper",
            endpoint_id="ep-helper-1",
            source="async def helper(x): return x\n",
            dependencies=[],
            system_dependencies=[],
        )

        with patch(
            "runpod_flash.stubs.dependency_resolver.resolve_dependencies",
            new_callable=AsyncMock,
            return_value=[dep],
        ):
            await stub.prepare_request(my_func, [], [], True, 1)

        # Should have 2 cache entries now (different hashes)
        assert len(_SERIALIZED_FUNCTION_CACHE) == 2
        hash2 = [k for k in _SERIALIZED_FUNCTION_CACHE.keys() if k != hash1][0]
        assert hash1 != hash2

    @pytest.mark.asyncio
    async def test_cache_key_changes_when_dep_endpoint_changes(self):
        """Same dep name but different endpoint_id produces different cache key."""
        mock_server = MagicMock()
        stub = LiveServerlessStub(mock_server)

        def my_func(x: int) -> int:
            return x * 2

        dep_v1 = RemoteDependency(
            name="helper",
            endpoint_id="ep-helper-v1",
            source="async def helper(x): return x\n",
            dependencies=[],
            system_dependencies=[],
        )
        dep_v2 = RemoteDependency(
            name="helper",
            endpoint_id="ep-helper-v2",
            source="async def helper(x): return x\n",
            dependencies=[],
            system_dependencies=[],
        )

        with patch(
            "runpod_flash.stubs.dependency_resolver.resolve_dependencies",
            new_callable=AsyncMock,
            return_value=[dep_v1],
        ):
            await stub.prepare_request(my_func, [], [], True, 1)

        with patch(
            "runpod_flash.stubs.dependency_resolver.resolve_dependencies",
            new_callable=AsyncMock,
            return_value=[dep_v2],
        ):
            await stub.prepare_request(my_func, [], [], True, 1)

        assert len(_SERIALIZED_FUNCTION_CACHE) == 2


# ---------------------------------------------------------------------------
# Integration: detect_remote_dependencies misses in-body imports (the actual bug)
# ---------------------------------------------------------------------------
class TestDetectRemoteDependenciesMissesInBody:
    """Demonstrate that detect_remote_dependencies alone cannot find in-body imports.

    This documents the root cause of the PR #224 bug: detect_remote_dependencies
    checks func.__globals__ which does NOT include names from in-body imports.
    resolve_in_function_imports must be called first to augment the globals.
    """

    def test_detect_misses_in_body_import_without_augmentation(self):
        """Without resolve_in_function_imports, in-body deps are invisible."""
        from runpod_flash.stubs.dependency_resolver import detect_remote_dependencies

        source = textwrap.dedent("""\
        async def classify(text: str) -> dict:
            from gpu_worker import gpu_inference
            return await gpu_inference({"text": text})
        """)

        # Empty globals — gpu_inference is NOT at module level
        result = detect_remote_dependencies(source, {})
        assert result == [], "detect_remote_dependencies cannot see in-body imports"

    def test_detect_finds_dep_after_augmentation(self):
        """With resolve_in_function_imports augmenting globals, dep IS found."""
        from runpod_flash.stubs.dependency_resolver import detect_remote_dependencies

        source = textwrap.dedent("""\
        async def classify(text: str) -> dict:
            from gpu_worker import gpu_inference
            return await gpu_inference({"text": text})
        """)

        gpu_func = _make_remote_func("gpu_inference", _gpu_inference_source)
        augmented_globals = {"gpu_inference": gpu_func}

        result = detect_remote_dependencies(source, augmented_globals)
        assert result == ["gpu_inference"]


# ---------------------------------------------------------------------------
# Both stubs call resolve_in_function_imports (not just resolve_dependencies)
# ---------------------------------------------------------------------------
class TestStubsCallResolveInFunctionImports:
    """Verify both stubs call resolve_in_function_imports before resolve_dependencies."""

    @pytest.mark.asyncio
    async def test_live_serverless_stub_calls_resolve_in_function_imports(self):
        """LiveServerlessStub.prepare_request calls resolve_in_function_imports."""
        mock_server = MagicMock()
        stub = LiveServerlessStub(mock_server)

        def my_func(x: int) -> int:
            return x

        with (
            patch(
                "runpod_flash.stubs.dependency_resolver.resolve_in_function_imports",
                return_value=my_func.__globals__,
            ) as mock_resolve_ifn,
            patch(
                "runpod_flash.stubs.dependency_resolver.resolve_dependencies",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            await stub.prepare_request(my_func, [], [], True, 1)

        mock_resolve_ifn.assert_called_once()

    @pytest.mark.asyncio
    async def test_lb_stub_calls_resolve_in_function_imports(self):
        """LoadBalancerSlsStub._prepare_request calls resolve_in_function_imports."""
        mock_server = MagicMock()
        stub = LoadBalancerSlsStub(mock_server)

        def my_func(x: int) -> int:
            return x

        with (
            patch(
                "runpod_flash.stubs.dependency_resolver.resolve_in_function_imports",
                return_value=my_func.__globals__,
            ) as mock_resolve_ifn,
            patch(
                "runpod_flash.stubs.dependency_resolver.resolve_dependencies",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            await stub._prepare_request(my_func, [], [], True, 1)

        mock_resolve_ifn.assert_called_once()

    @pytest.mark.asyncio
    async def test_resolve_in_function_imports_result_passed_to_resolve_dependencies(
        self,
    ):
        """The augmented globals from resolve_in_function_imports are passed to resolve_dependencies."""
        mock_server = MagicMock()
        stub = LiveServerlessStub(mock_server)

        def my_func(x: int) -> int:
            return x

        sentinel_globals = {"__sentinel__": True, **my_func.__globals__}

        with (
            patch(
                "runpod_flash.stubs.dependency_resolver.resolve_in_function_imports",
                return_value=sentinel_globals,
            ),
            patch(
                "runpod_flash.stubs.dependency_resolver.resolve_dependencies",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_resolve_deps,
        ):
            await stub.prepare_request(my_func, [], [], True, 1)

        # resolve_dependencies should receive the augmented globals, not the original
        call_args = mock_resolve_deps.call_args
        actual_globals = call_args[0][1]
        assert "__sentinel__" in actual_globals
