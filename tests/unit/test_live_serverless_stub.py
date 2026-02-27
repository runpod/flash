"""Unit tests for live_serverless stub functionality."""

import ast
from runpod_flash.stubs.live_serverless import get_function_source
from runpod_flash import remote, LiveServerless


def _fresh_config():
    return LiveServerless(name="test-endpoint")


class TestGetFunctionSource:
    """Test suite for get_function_source function."""

    def test_sync_function_without_decorator(self):
        """Test extraction of synchronous function source without decorator."""

        def simple_function(x: int) -> int:
            return x * 2

        source, src_hash = get_function_source(simple_function)

        assert "def simple_function" in source
        assert "return x * 2" in source
        assert len(src_hash) == 64  # SHA256 hash length

    def test_async_function_without_decorator(self):
        """Test extraction of async function source without decorator."""

        async def async_function(x: int) -> int:
            return x * 2

        source, src_hash = get_function_source(async_function)

        assert "async def async_function" in source
        assert "return x * 2" in source
        assert len(src_hash) == 64

    def test_sync_function_with_remote_decorator(self):
        """Test extraction of decorated synchronous function source."""

        # Create a real decorated function for testing
        def real_sync_function(x: int) -> int:
            """A real sync function."""
            return x * 3

        decorated_real = remote(resource_config=_fresh_config())(real_sync_function)

        source, src_hash = get_function_source(decorated_real)

        # Should find the function definition
        assert "def real_sync_function" in source
        assert "return x * 3" in source

    def test_async_function_with_remote_decorator(self):
        """Test extraction of decorated async function source."""

        @remote(resource_config=_fresh_config())
        async def decorated_async(x: int) -> int:
            """A decorated async function."""
            return x * 4

        source, src_hash = get_function_source(decorated_async)

        # Should find the async function definition
        assert "async def decorated_async" in source
        assert "return x * 4" in source

    def test_function_source_excludes_decorator_line(self):
        """Test that source extraction correctly excludes decorator lines."""

        @remote(resource_config=_fresh_config())
        async def function_with_decorator(x: int) -> int:
            """Function with decorator."""
            return x * 5

        source, src_hash = get_function_source(function_with_decorator)

        # Source should NOT include the decorator line (it's stripped)
        assert "@remote" not in source
        # But should include the function definition
        assert "async def function_with_decorator" in source
        assert "return x * 5" in source

    def test_ast_parsing_handles_async_function(self):
        """Test that AST parsing correctly identifies async functions."""

        @remote(resource_config=_fresh_config())
        async def async_test_function(x: int) -> int:
            """Async function for AST test."""
            result = x * 6
            return result

        source, src_hash = get_function_source(async_test_function)

        # Parse the source to verify it's valid Python with async function
        module = ast.parse(source)

        # Find the async function definition
        async_func_found = False
        for node in ast.walk(module):
            if (
                isinstance(node, ast.AsyncFunctionDef)
                and node.name == "async_test_function"
            ):
                async_func_found = True
                break

        assert async_func_found, "AsyncFunctionDef node should be found in AST"

    def test_hash_consistency(self):
        """Test that same function produces same hash."""

        def consistent_function(x: int) -> int:
            return x * 7

        source1, hash1 = get_function_source(consistent_function)
        source2, hash2 = get_function_source(consistent_function)

        assert hash1 == hash2
        assert source1 == source2

    def test_different_functions_different_hashes(self):
        """Test that different functions produce different hashes."""

        def function_one(x: int) -> int:
            return x * 8

        def function_two(x: int) -> int:
            return x * 9

        _, hash1 = get_function_source(function_one)
        _, hash2 = get_function_source(function_two)

        assert hash1 != hash2
