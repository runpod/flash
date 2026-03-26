"""
Unit tests for class serialization caching functionality.

These tests verify the caching behavior of remote class execution including:
- Cache key generation
- Cache hit/miss scenarios
- Error handling for unserializable arguments
"""

import tempfile
from unittest.mock import patch

from runpod_flash.core.resources import ServerlessResource
from runpod_flash.execute_class import (
    _SERIALIZED_CLASS_CACHE,
    create_remote_class,
    get_class_cache_key,
)


class TestGetClassCacheKey:
    """Test cache key generation functionality."""

    def setup_method(self):
        """Clear cache before each test."""
        _SERIALIZED_CLASS_CACHE.clear()

    def test_cache_key_generation_basic(self):
        """Test basic cache key generation."""

        class SimpleClass:
            def __init__(self, value):
                self.value = value

        cache_key = get_class_cache_key(SimpleClass, (42,), {})
        # Extract class code separately for verification
        from runpod_flash.execute_class import extract_class_code_simple

        class_code = extract_class_code_simple(SimpleClass)

        assert cache_key.startswith("SimpleClass_")
        assert len(cache_key.split("_")) == 3  # class_name_class_hash_args_hash
        assert "class SimpleClass:" in class_code
        assert len(class_code) > 0

    def test_cache_key_consistency(self):
        """Test that same inputs produce same cache key."""

        class TestClass:
            def __init__(self, x, y=None):
                self.x = x
                self.y = y

        key1 = get_class_cache_key(TestClass, (1, 2), {"y": 3})
        key2 = get_class_cache_key(TestClass, (1, 2), {"y": 3})

        assert key1 == key2

    def test_cache_key_different_for_different_args(self):
        """Test that different args produce different cache keys."""

        class TestClass:
            def __init__(self, value):
                self.value = value

        key1 = get_class_cache_key(TestClass, (42,), {})
        key2 = get_class_cache_key(TestClass, (99,), {})

        assert key1 != key2

    def test_cache_key_different_for_different_class(self):
        """Test that different classes produce different cache keys."""

        class ClassA:
            def __init__(self, value):
                self.value = value

        class ClassB:
            def __init__(self, value):
                self.value = value

        key1 = get_class_cache_key(ClassA, (42,), {})
        key2 = get_class_cache_key(ClassB, (42,), {})

        assert key1 != key2
        assert key1.startswith("ClassA_")
        assert key2.startswith("ClassB_")

    def test_cache_key_fallback_on_unserializable_args(self):
        """Test fallback to UUID when args can't be serialized."""

        class TestClass:
            def __init__(self, file_handle):
                self.file_handle = file_handle

        with tempfile.NamedTemporaryFile() as temp_file:
            # This should trigger the fallback due to unserializable file handle
            key1 = get_class_cache_key(TestClass, (temp_file,), {})
            key2 = get_class_cache_key(TestClass, (temp_file,), {})

            # Keys should be different (UUID-based)
            assert key1 != key2
            assert key1.startswith("TestClass_")
            assert key2.startswith("TestClass_")

    def test_cache_key_with_complex_args(self):
        """Test cache key generation with complex constructor arguments."""

        class ComplexClass:
            def __init__(self, data, config=None, **kwargs):
                self.data = data
                self.config = config
                self.kwargs = kwargs

        complex_data = {"nested": {"list": [1, 2, 3]}, "string": "test"}
        config = {"setting1": True, "setting2": 42}

        key = get_class_cache_key(
            ComplexClass, (complex_data,), {"config": config, "extra": "value"}
        )

        assert key.startswith("ComplexClass_")


class TestClassCaching:
    """Test end-to-end class caching functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        _SERIALIZED_CLASS_CACHE.clear()
        self.mock_resource_config = ServerlessResource(
            name="cache-test-resource",
            image="python:3.9-slim",
            cpu=1,
            memory=512,
        )

    def test_cache_miss_and_hit(self):
        """Test cache miss on first instance, hit on second."""

        class CacheTestClass:
            def __init__(self, value):
                self.value = value

        RemoteCacheTestClass = create_remote_class(
            CacheTestClass, self.mock_resource_config, [], [], True
        )

        # First instance - should be cache miss
        assert len(_SERIALIZED_CLASS_CACHE) == 0
        instance1 = RemoteCacheTestClass(42)
        assert len(_SERIALIZED_CLASS_CACHE) == 1

        # Get the cache key from the instance
        cache_key = instance1._cache_key
        assert cache_key in _SERIALIZED_CLASS_CACHE

        # Verify cache contents
        cached_data = _SERIALIZED_CLASS_CACHE[cache_key]
        assert "class_code" in cached_data
        assert "constructor_args" in cached_data
        assert "constructor_kwargs" in cached_data
        assert cached_data["constructor_args"] is not None
        assert cached_data["constructor_kwargs"] is not None

        # Second instance with same args - should be cache hit
        instance2 = RemoteCacheTestClass(42)
        assert len(_SERIALIZED_CLASS_CACHE) == 1  # No new entry
        assert instance2._cache_key == cache_key  # Same cache key

    def test_cache_different_args_create_different_entries(self):
        """Test that different constructor args create separate cache entries."""

        class MultiArgClass:
            def __init__(self, x, y=None):
                self.x = x
                self.y = y

        RemoteMultiArgClass = create_remote_class(
            MultiArgClass, self.mock_resource_config, [], [], True
        )

        # Different args should create different cache entries
        instance1 = RemoteMultiArgClass(1, y=2)
        instance2 = RemoteMultiArgClass(3, y=4)
        instance3 = RemoteMultiArgClass(1, y=2)  # Same as instance1

        assert len(_SERIALIZED_CLASS_CACHE) == 2  # Two unique combinations
        assert instance1._cache_key == instance3._cache_key  # Same args
        assert instance1._cache_key != instance2._cache_key  # Different args

    def test_cache_with_unserializable_args(self):
        """Test graceful handling of unserializable constructor arguments."""

        class FileHandlerClass:
            def __init__(self, file_handle, name="default"):
                self.file_handle = file_handle
                self.name = name

        RemoteFileHandlerClass = create_remote_class(
            FileHandlerClass, self.mock_resource_config, [], [], True
        )

        with tempfile.NamedTemporaryFile() as temp_file:
            # This should not crash, but fall back to no constructor arg caching
            instance = RemoteFileHandlerClass(temp_file, name="test")

            assert len(_SERIALIZED_CLASS_CACHE) == 1
            cached_data = _SERIALIZED_CLASS_CACHE[instance._cache_key]

            # Class code should still be cached
            assert cached_data["class_code"] is not None
            assert "class FileHandlerClass:" in cached_data["class_code"]

            # But constructor args should be None (couldn't serialize)
            assert cached_data["constructor_args"] is None
            assert cached_data["constructor_kwargs"] is None

    def test_cache_class_code_extraction_called_appropriately(self):
        """Test that class code extraction is called for cache operations."""

        class OptimizationTestClass:
            def __init__(self, value):
                self.value = value

        RemoteOptimizationTestClass = create_remote_class(
            OptimizationTestClass, self.mock_resource_config, [], [], True
        )

        with patch(
            "runpod_flash.execute_class.extract_class_code_simple"
        ) as mock_extract:
            mock_extract.return_value = "class OptimizationTestClass:\n    pass"

            # Create instance - should call extract_class_code_simple for caching
            instance = RemoteOptimizationTestClass(42)

            # Should be called at least once for cache operations
            assert mock_extract.call_count >= 1
            assert (
                instance._clean_class_code == "class OptimizationTestClass:\n    pass"
            )

    def test_cache_preserves_class_code_across_instances(self):
        """Test that cached class code is consistent across instances."""

        class ConsistencyTestClass:
            def __init__(self, value):
                self.value = value

            def get_value(self):
                return self.value

        RemoteConsistencyTestClass = create_remote_class(
            ConsistencyTestClass, self.mock_resource_config, [], [], True
        )

        instance1 = RemoteConsistencyTestClass(1)
        instance2 = RemoteConsistencyTestClass(1)  # Same args - cache hit
        instance3 = RemoteConsistencyTestClass(2)  # Different args - cache miss

        # All instances should have the same class code
        assert instance1._clean_class_code == instance2._clean_class_code
        assert instance1._clean_class_code == instance3._clean_class_code

        # Verify the class code contains expected content
        assert "class ConsistencyTestClass:" in instance1._clean_class_code
        assert "def get_value(self):" in instance1._clean_class_code

    def test_cache_key_uuid_fallback_different_each_time(self):
        """Test that UUID fallback produces different keys each time."""

        class UUIDFallbackClass:
            def __init__(self, file_handle):
                self.file_handle = file_handle

        RemoteUUIDFallbackClass = create_remote_class(
            UUIDFallbackClass, self.mock_resource_config, [], [], True
        )

        with (
            tempfile.NamedTemporaryFile() as temp_file1,
            tempfile.NamedTemporaryFile() as temp_file2,
        ):
            instance1 = RemoteUUIDFallbackClass(temp_file1)
            instance2 = RemoteUUIDFallbackClass(temp_file2)

            # Should create separate cache entries due to UUID fallback
            assert len(_SERIALIZED_CLASS_CACHE) == 2
            assert instance1._cache_key != instance2._cache_key

            # But both should start with class name
            assert instance1._cache_key.startswith("UUIDFallbackClass_")
            assert instance2._cache_key.startswith("UUIDFallbackClass_")

    def test_cache_memory_efficiency(self):
        """Test that cache doesn't grow unnecessarily."""

        class MemoryTestClass:
            def __init__(self, value):
                self.value = value

        RemoteMemoryTestClass = create_remote_class(
            MemoryTestClass, self.mock_resource_config, [], [], True
        )

        # Create many instances with same args - should only create one cache entry
        instances = [RemoteMemoryTestClass(42) for _ in range(10)]

        assert len(_SERIALIZED_CLASS_CACHE) == 1

        # All instances should share the same cache key
        cache_keys = [instance._cache_key for instance in instances]
        assert all(key == cache_keys[0] for key in cache_keys)

    def test_cache_different_classes_separate_entries(self):
        """Test that different classes create separate cache entries."""

        class ClassTypeA:
            def __init__(self, value):
                self.value = value

        class ClassTypeB:
            def __init__(self, value):
                self.value = value

        RemoteClassTypeA = create_remote_class(
            ClassTypeA, self.mock_resource_config, [], [], True
        )
        RemoteClassTypeB = create_remote_class(
            ClassTypeB, self.mock_resource_config, [], [], True
        )

        instanceA = RemoteClassTypeA(42)
        instanceB = RemoteClassTypeB(42)  # Same args, different class

        assert len(_SERIALIZED_CLASS_CACHE) == 2
        assert instanceA._cache_key != instanceB._cache_key
        assert instanceA._cache_key.startswith("ClassTypeA_")
        assert instanceB._cache_key.startswith("ClassTypeB_")


class TestCacheDataStructure:
    """Test the structure and content of cached data."""

    def setup_method(self):
        """Clear cache before each test."""
        _SERIALIZED_CLASS_CACHE.clear()

    def test_cached_data_structure(self):
        """Test that cached data has the expected structure."""

        class StructureTestClass:
            def __init__(self, value, config=None):
                self.value = value
                self.config = config

        resource_config = ServerlessResource(
            name="structure-test", image="python:3.9-slim"
        )

        RemoteStructureTestClass = create_remote_class(
            StructureTestClass, resource_config, [], [], True
        )

        instance = RemoteStructureTestClass(42, config={"key": "value"})
        cached_data = _SERIALIZED_CLASS_CACHE[instance._cache_key]

        # Verify structure
        assert isinstance(cached_data, dict)
        assert set(cached_data.keys()) == {
            "class_code",
            "constructor_args",
            "constructor_kwargs",
        }

        # Verify class_code
        assert isinstance(cached_data["class_code"], str)
        assert "class StructureTestClass:" in cached_data["class_code"]

        # Verify constructor_args (should be base64-encoded strings)
        assert isinstance(cached_data["constructor_args"], list)
        assert len(cached_data["constructor_args"]) == 1
        assert isinstance(cached_data["constructor_args"][0], str)

        # Verify constructor_kwargs
        assert isinstance(cached_data["constructor_kwargs"], dict)
        assert "config" in cached_data["constructor_kwargs"]
        assert isinstance(cached_data["constructor_kwargs"]["config"], str)

    def test_cached_data_serialization_format(self):
        """Test that cached data is properly base64-encoded."""
        import base64

        import cloudpickle

        class SerializationTestClass:
            def __init__(self, data):
                self.data = data

        resource_config = ServerlessResource(
            name="serialization-test", image="python:3.9-slim"
        )

        RemoteSerializationTestClass = create_remote_class(
            SerializationTestClass, resource_config, [], [], True
        )

        test_data = {"test": [1, 2, 3]}
        instance = RemoteSerializationTestClass(test_data)
        cached_data = _SERIALIZED_CLASS_CACHE[instance._cache_key]

        # Verify we can decode the cached constructor args
        encoded_arg = cached_data["constructor_args"][0]
        decoded_arg = cloudpickle.loads(base64.b64decode(encoded_arg))

        assert decoded_arg == test_data
