"""Tests for cross-endpoint @remote dispatch integration.

Verifies that LiveServerlessStub.prepare_request and
LoadBalancerSlsStub._prepare_request correctly wire up
resolve_in_function_imports + strip_remote_imports + build_augmented_source
when the calling function has in-body imports of @remote-decorated functions.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runpod_flash.stubs.dependency_resolver import RemoteDependency
from runpod_flash.stubs.live_serverless import (
    LiveServerlessStub,
    _SERIALIZED_FUNCTION_CACHE,
)
from runpod_flash.stubs.load_balancer_sls import LoadBalancerSlsStub


@pytest.fixture(autouse=True)
def _clear_function_cache():
    _SERIALIZED_FUNCTION_CACHE.clear()
    yield
    _SERIALIZED_FUNCTION_CACHE.clear()


# ── Helper: fake @remote decorated function ──────────────────────────────


def _make_remote_func(name, endpoint_id):
    """Create a fake @remote-decorated function with __remote_config__."""

    async def _func(x):
        return x

    _func.__name__ = name
    _func.__qualname__ = name
    _func.__remote_config__ = {
        "resource_config": MagicMock(),
        "dependencies": [],
        "system_dependencies": [],
    }
    return _func


# ── Fake module for in-function import resolution ────────────────────────

_fake_remote_helper = _make_remote_func("helper_func", "ep-helper-123")


# ── LiveServerlessStub integration tests ─────────────────────────────────


class TestLiveServerlessStubCrossEndpointDispatch:
    """Integration: prepare_request discovers, strips, and augments cross-endpoint deps."""

    @pytest.fixture
    def stub(self):
        server = MagicMock()
        server.run = AsyncMock()
        return LiveServerlessStub(server)

    @pytest.mark.asyncio
    async def test_prepare_request_augments_source_with_stub_code(self, stub):
        """When a function calls a @remote dependency, source is augmented with stub."""

        def caller_func(x):
            return helper_func(x)  # noqa: F821 -- resolved at runtime

        dep = RemoteDependency(
            name="helper_func",
            endpoint_id="ep-helper-123",
            source="async def helper_func(x):\n    return x\n",
            dependencies=[],
            system_dependencies=[],
        )

        with (
            patch(
                "runpod_flash.stubs.dependency_resolver.resolve_in_function_imports",
                return_value=caller_func.__globals__,
            ),
            patch(
                "runpod_flash.stubs.dependency_resolver.resolve_dependencies",
                new_callable=AsyncMock,
                return_value=[dep],
            ),
        ):
            request = await stub.prepare_request(caller_func, [], [], True, 42)

        # Source should be augmented with stub code for helper_func
        assert "async def helper_func(" in request.function_code
        assert "ep-helper-123" in request.function_code
        # Original function should still be present
        assert "def caller_func" in request.function_code

    @pytest.mark.asyncio
    async def test_prepare_request_strips_remote_import(self, stub):
        """In-body `from X import remote_func` is stripped from the source."""

        def caller_with_import(x):
            from tests.unit.test_cross_endpoint_dispatch import _fake_remote_helper  # noqa: F401

            return _fake_remote_helper(x)  # noqa: F821

        dep = RemoteDependency(
            name="_fake_remote_helper",
            endpoint_id="ep-helper-456",
            source="async def _fake_remote_helper(x):\n    return x\n",
            dependencies=[],
            system_dependencies=[],
        )

        with patch(
            "runpod_flash.stubs.dependency_resolver.resolve_dependencies",
            new_callable=AsyncMock,
            return_value=[dep],
        ):
            request = await stub.prepare_request(caller_with_import, [], [], True, 99)

        # The import statement should be stripped
        assert (
            "from tests.unit.test_cross_endpoint_dispatch import"
            not in request.function_code
        )
        # The stub should be injected
        assert "ep-helper-456" in request.function_code

    @pytest.mark.asyncio
    async def test_prepare_request_no_deps_passes_through(self, stub):
        """When no @remote deps found, source is passed through unmodified."""

        def simple_func(x):
            return x + 1

        with patch(
            "runpod_flash.stubs.dependency_resolver.resolve_dependencies",
            new_callable=AsyncMock,
            return_value=[],
        ):
            request = await stub.prepare_request(simple_func, [], [], True, 5)

        assert "def simple_func" in request.function_code
        # No stub code injected
        assert (
            "async def " not in request.function_code
            or "async def simple_func" in request.function_code
        )

    @pytest.mark.asyncio
    async def test_prepare_request_recomputes_hash_with_deps(self, stub):
        """Cache key includes dependency endpoint IDs when deps are present."""

        def caller_func(x):
            return x

        dep = RemoteDependency(
            name="dep_func",
            endpoint_id="ep-dep-789",
            source="async def dep_func(x):\n    return x\n",
            dependencies=[],
            system_dependencies=[],
        )

        with (
            patch(
                "runpod_flash.stubs.dependency_resolver.resolve_in_function_imports",
                return_value=caller_func.__globals__,
            ),
            patch(
                "runpod_flash.stubs.dependency_resolver.resolve_dependencies",
                new_callable=AsyncMock,
                return_value=[dep],
            ),
        ):
            await stub.prepare_request(caller_func, [], [], True, 1)

        # Cache should have an entry whose source includes the endpoint ID
        assert len(_SERIALIZED_FUNCTION_CACHE) == 1
        cached_source = list(_SERIALIZED_FUNCTION_CACHE.values())[0]
        assert "ep-dep-789" in cached_source


# ── LoadBalancerSlsStub integration tests ────────────────────────────────


class TestLoadBalancerSlsStubCrossEndpointDispatch:
    """Integration: _prepare_request discovers, strips, and augments cross-endpoint deps."""

    @pytest.fixture
    def stub(self):
        server = MagicMock()
        server.endpoint_url = "http://localhost:8000"
        server.name = "test-lb"
        return LoadBalancerSlsStub(server)

    @pytest.mark.asyncio
    async def test_prepare_request_augments_source_with_stub_code(self, stub):
        """When a function calls a @remote dependency, source is augmented with stub."""

        def caller_func(x):
            return helper_func(x)  # noqa: F821

        dep = RemoteDependency(
            name="helper_func",
            endpoint_id="ep-helper-123",
            source="async def helper_func(x):\n    return x\n",
            dependencies=[],
            system_dependencies=[],
        )

        with (
            patch(
                "runpod_flash.stubs.dependency_resolver.resolve_in_function_imports",
                return_value=caller_func.__globals__,
            ),
            patch(
                "runpod_flash.stubs.dependency_resolver.resolve_dependencies",
                new_callable=AsyncMock,
                return_value=[dep],
            ),
        ):
            request = await stub._prepare_request(caller_func, [], [], True, 42)

        assert "async def helper_func(" in request["function_code"]
        assert "ep-helper-123" in request["function_code"]
        assert "def caller_func" in request["function_code"]

    @pytest.mark.asyncio
    async def test_prepare_request_strips_remote_import(self, stub):
        """In-body `from X import remote_func` is stripped from source."""

        def caller_with_import(x):
            from tests.unit.test_cross_endpoint_dispatch import _fake_remote_helper  # noqa: F401

            return _fake_remote_helper(x)  # noqa: F821

        dep = RemoteDependency(
            name="_fake_remote_helper",
            endpoint_id="ep-helper-456",
            source="async def _fake_remote_helper(x):\n    return x\n",
            dependencies=[],
            system_dependencies=[],
        )

        with patch(
            "runpod_flash.stubs.dependency_resolver.resolve_dependencies",
            new_callable=AsyncMock,
            return_value=[dep],
        ):
            request = await stub._prepare_request(caller_with_import, [], [], True, 99)

        assert (
            "from tests.unit.test_cross_endpoint_dispatch import"
            not in request["function_code"]
        )
        assert "ep-helper-456" in request["function_code"]

    @pytest.mark.asyncio
    async def test_prepare_request_no_deps_passes_through(self, stub):
        """When no @remote deps found, source is passed through unmodified."""

        def simple_func(x):
            return x + 1

        with patch(
            "runpod_flash.stubs.dependency_resolver.resolve_dependencies",
            new_callable=AsyncMock,
            return_value=[],
        ):
            request = await stub._prepare_request(simple_func, [], [], True, 5)

        assert "def simple_func" in request["function_code"]
        assert request["function_name"] == "simple_func"
