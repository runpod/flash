"""Tests for runtime/api_key_context.py - context variable API key propagation."""

import asyncio

import pytest

from runpod_flash.runtime.api_key_context import clear_api_key, get_api_key, set_api_key


class TestSetApiKey:
    """Test set_api_key function."""

    def test_set_returns_token(self):
        """set_api_key returns a context variable token."""
        token = set_api_key("test-key-123")
        assert token is not None
        # Cleanup
        clear_api_key(token)

    def test_set_none_value(self):
        """set_api_key accepts None."""
        token = set_api_key(None)
        assert get_api_key() is None
        clear_api_key(token)


class TestGetApiKey:
    """Test get_api_key function."""

    def test_get_returns_set_value(self):
        """get_api_key returns the value set by set_api_key."""
        token = set_api_key("my-api-key")
        assert get_api_key() == "my-api-key"
        clear_api_key(token)

    def test_get_returns_none_when_not_set(self):
        """get_api_key returns None when no key has been set."""
        # Reset to default
        token = set_api_key(None)
        assert get_api_key() is None
        clear_api_key(token)


class TestClearApiKey:
    """Test clear_api_key function."""

    def test_clear_without_token_sets_none(self):
        """clear_api_key without token sets context to None."""
        set_api_key("some-key")
        clear_api_key()
        assert get_api_key() is None
        # Note: token is now stale, but that's fine for cleanup

    def test_clear_with_token_restores_previous(self):
        """clear_api_key with token restores previous value."""
        # Set initial value
        initial_token = set_api_key("outer-key")

        # Set nested value
        nested_token = set_api_key("inner-key")
        assert get_api_key() == "inner-key"

        # Reset with token - should restore to "outer-key"
        clear_api_key(nested_token)
        assert get_api_key() == "outer-key"

        # Cleanup
        clear_api_key(initial_token)


class TestAsyncContextIsolation:
    """Test API key context isolation across async tasks."""

    @pytest.mark.asyncio
    async def test_separate_tasks_have_isolated_contexts(self):
        """Different async tasks should have isolated context values."""
        results = {}

        async def task_with_key(task_id: str, key: str):
            token = set_api_key(key)
            await asyncio.sleep(0.01)  # Yield to other tasks
            results[task_id] = get_api_key()
            clear_api_key(token)

        await asyncio.gather(
            task_with_key("task1", "key-1"),
            task_with_key("task2", "key-2"),
            task_with_key("task3", "key-3"),
        )

        # Each task should have seen its own key
        assert results["task1"] == "key-1"
        assert results["task2"] == "key-2"
        assert results["task3"] == "key-3"

    @pytest.mark.asyncio
    async def test_nested_async_context(self):
        """Nested async calls maintain correct context."""
        outer_token = set_api_key("outer-key")

        async def inner():
            inner_token = set_api_key("inner-key")
            assert get_api_key() == "inner-key"
            clear_api_key(inner_token)
            return get_api_key()

        restored = await inner()
        assert restored == "outer-key"
        clear_api_key(outer_token)
