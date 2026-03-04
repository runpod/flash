"""
Integration tests for runpod_flash remote class execution functionality.

These tests verify end-to-end functionality of remote class execution including:
- Remote class decorator integration
- Multiple method calls on the same instance
- Complex constructor arguments
- Error handling in remote class execution
"""

import asyncio
import base64
import os
from unittest.mock import AsyncMock, patch

import cloudpickle
import pytest
from runpod_flash.client import remote
from runpod_flash.core.resources import ServerlessResource
from runpod_flash.execute_class import create_remote_class


@patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "", "RUNPOD_POD_ID": ""})
class TestRemoteClassDecoratorIntegration:
    """Test remote class decorator integration."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_resource_config = ServerlessResource(
            name="integration-test-resource",
            image="python:3.9-slim",
            cpu=2,
            memory=1024,
        )
        self.dependencies = ["numpy>=1.21.0", "pandas>=1.3.0"]
        self.system_dependencies = ["curl", "git"]

    @pytest.mark.asyncio
    async def test_remote_decorator_on_class(self):
        """Test @remote decorator integration with class."""

        @remote(
            resource_config=self.mock_resource_config,
            dependencies=self.dependencies,
            system_dependencies=self.system_dependencies,
            timeout=60,
        )
        class RemoteCalculator:
            def __init__(self, initial_value=0):
                self.value = initial_value
                self.history = []

            def add(self, x):
                self.value += x
                self.history.append(f"add({x})")
                return self.value

            def multiply(self, x):
                self.value *= x
                self.history.append(f"multiply({x})")
                return self.value

            def get_history(self):
                return self.history.copy()

        # Verify decorator returns a class (RemoteClassWrapper)
        assert hasattr(RemoteCalculator, "__call__")

        # Create instance
        calc = RemoteCalculator(10)

        # Verify wrapper properties
        assert calc._class_type.__name__ == "RemoteCalculator"
        assert calc._constructor_args == (10,)
        assert calc._dependencies == self.dependencies
        assert calc._system_dependencies == self.system_dependencies
        assert not calc._initialized

        # Verify class code extraction
        assert "class RemoteCalculator:" in calc._clean_class_code
        assert "def add(self, x):" in calc._clean_class_code
        assert "def multiply(self, x):" in calc._clean_class_code

        # Mock the stub for method execution
        mock_stub = AsyncMock()
        mock_stub.execute_class_method.return_value = 15

        async def mock_ensure_initialized():
            if calc._initialized:
                return
            calc._stub = mock_stub
            calc._initialized = True

        with patch.object(
            calc, "_ensure_initialized", side_effect=mock_ensure_initialized
        ):
            result = await calc.add(5)
            assert result == 15

            # Verify correct request construction
            call_args = mock_stub.execute_class_method.call_args[0][0]
            assert call_args.class_name == "RemoteCalculator"
            assert call_args.method_name == "add"
            assert call_args.dependencies == self.dependencies
            assert call_args.system_dependencies == self.system_dependencies

    @pytest.mark.asyncio
    async def test_remote_decorator_with_complex_class_structure(self):
        """Test remote decorator with a complex class including properties and class methods."""

        @remote(
            resource_config=self.mock_resource_config,
            dependencies=["scikit-learn"],
        )
        class DataProcessor:
            CLASS_CONSTANT = "DATA_PROCESSOR_V1"

            def __init__(self, name, config=None, *args, **kwargs):
                self.name = name
                self.config = config or {}
                self.extra_args = args
                self.extra_kwargs = kwargs
                self._processed_count = 0

            @classmethod
            def create_default(cls):
                return cls("default_processor", {"mode": "standard"})

            @staticmethod
            def validate_data(data):
                return isinstance(data, (list, tuple)) and len(data) > 0

            @property
            def status(self):
                return f"{self.name}: processed {self._processed_count} items"

            def process(self, data):
                if not self.validate_data(data):
                    raise ValueError("Invalid data format")
                self._processed_count += len(data)
                return f"Processed {len(data)} items"

        # Create instance with complex arguments
        processor = DataProcessor(
            "test_processor",
            {"batch_size": 32, "verbose": True},
            "extra_arg1",
            "extra_arg2",
            extra_param="extra_value",
            debug=True,
        )

        # Verify complex initialization
        assert processor._constructor_args == (
            "test_processor",
            {"batch_size": 32, "verbose": True},
            "extra_arg1",
            "extra_arg2",
        )
        assert processor._constructor_kwargs == {
            "extra_param": "extra_value",
            "debug": True,
        }

        # Verify class code preserves complex structure
        class_code = processor._clean_class_code
        assert 'CLASS_CONSTANT = "DATA_PROCESSOR_V1"' in class_code
        assert "def create_default(cls):" in class_code
        assert "def validate_data(data):" in class_code
        assert "def status(self):" in class_code


class TestMultipleMethodCallsOnSameInstance:
    """Test multiple method calls on the same remote class instance."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_resource_config = ServerlessResource(
            name="multi-call-test", image="python:3.9", cpu=1, memory=512
        )

    @pytest.mark.asyncio
    async def test_multiple_method_calls_maintain_state(self):
        """Test that multiple method calls on same instance maintain state."""

        class StatefulCounter:
            def __init__(self, start=0):
                self.count = start
                self.operation_log = []

            def increment(self, by=1):
                self.count += by
                self.operation_log.append(f"increment({by})")
                return self.count

            def decrement(self, by=1):
                self.count -= by
                self.operation_log.append(f"decrement({by})")
                return self.count

            def get_state(self):
                return {
                    "count": self.count,
                    "operations": len(self.operation_log),
                    "last_op": self.operation_log[-1] if self.operation_log else None,
                }

        RemoteCounter = create_remote_class(
            StatefulCounter, self.mock_resource_config, [], [], True, {}
        )

        counter = RemoteCounter(5)

        # Mock stub responses for multiple calls
        mock_stub = AsyncMock()

        # Simulate maintaining state across calls
        call_responses = [
            10,
            8,
            {"count": 8, "operations": 2, "last_op": "decrement(2)"},
        ]
        mock_stub.execute_class_method.side_effect = call_responses

        async def mock_ensure_initialized():
            if counter._initialized:
                return
            counter._stub = mock_stub
            counter._initialized = True

        with patch.object(
            counter, "_ensure_initialized", side_effect=mock_ensure_initialized
        ):
            # First call
            result1 = await counter.increment(5)
            assert result1 == 10

            # Second call
            result2 = await counter.decrement(2)
            assert result2 == 8

            # Third call
            result3 = await counter.get_state()
            assert result3["count"] == 8
            assert result3["operations"] == 2

            # Verify all calls used the same instance_id
            calls = mock_stub.execute_class_method.call_args_list
            assert len(calls) == 3

            instance_ids = [call[0][0].instance_id for call in calls]
            assert all(id == instance_ids[0] for id in instance_ids), (
                "All calls should use same instance_id"
            )

            # Verify create_new_instance is False after first call
            assert (
                calls[0][0][0].create_new_instance is False
            )  # First call after initialization
            assert calls[1][0][0].create_new_instance is False
            assert calls[2][0][0].create_new_instance is False

    @pytest.mark.asyncio
    async def test_parallel_method_calls_same_instance(self):
        """Test parallel method calls on the same instance."""

        class AsyncWorker:
            def __init__(self):
                self.tasks_completed = 0

            async def work_task(self, task_id, duration=0.1):
                # Simulate async work
                await asyncio.sleep(duration)
                self.tasks_completed += 1
                return f"Task {task_id} completed"

            def get_completed_count(self):
                return self.tasks_completed

        RemoteWorker = create_remote_class(
            AsyncWorker, self.mock_resource_config, [], [], True, {}
        )

        worker = RemoteWorker()

        # Mock responses for parallel calls
        mock_stub = AsyncMock()
        mock_stub.execute_class_method.side_effect = [
            "Task 1 completed",
            "Task 2 completed",
            "Task 3 completed",
            3,  # Final count
        ]

        async def mock_ensure_initialized():
            if worker._initialized:
                return
            worker._stub = mock_stub
            worker._initialized = True

        with patch.object(
            worker, "_ensure_initialized", side_effect=mock_ensure_initialized
        ):
            # Execute parallel tasks
            tasks = [worker.work_task(1), worker.work_task(2), worker.work_task(3)]

            results = await asyncio.gather(*tasks)
            final_count = await worker.get_completed_count()

            assert results == [
                "Task 1 completed",
                "Task 2 completed",
                "Task 3 completed",
            ]
            assert final_count == 3

            # Verify all calls used same instance
            calls = mock_stub.execute_class_method.call_args_list
            instance_ids = [call[0][0].instance_id for call in calls]
            assert all(id == instance_ids[0] for id in instance_ids)


class TestComplexConstructorArguments:
    """Test remote class execution with complex constructor arguments."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_resource_config = ServerlessResource(
            name="complex-args-test", image="python:3.9", cpu=1, memory=512
        )

    @pytest.mark.asyncio
    async def test_complex_object_serialization(self):
        """Test complex object serialization in constructor."""

        class ConfigurableModel:
            def __init__(self, model_config, data_sources, metadata=None, **options):
                self.config = model_config
                self.sources = data_sources
                self.metadata = metadata or {}
                self.options = options
                self.initialized = True

            def get_config_summary(self):
                return {
                    "config_type": type(self.config).__name__,
                    "sources_count": len(self.sources),
                    "has_metadata": bool(self.metadata),
                    "options_count": len(self.options),
                }

            def process_with_config(self, input_data):
                return (
                    f"Processed {len(input_data)} items with {self.config['algorithm']}"
                )

        # Complex constructor arguments
        model_config = {
            "algorithm": "random_forest",
            "parameters": {"n_estimators": 100, "max_depth": 10},
            "preprocessing": ["normalize", "scale"],
        }

        data_sources = [
            {"type": "database", "connection": "postgresql://..."},
            {"type": "file", "path": "/data/training.csv"},
        ]

        metadata = {
            "version": "1.0.0",
            "created_by": "data_team",
            "tags": ["production", "ml_model"],
        }

        RemoteModel = create_remote_class(
            ConfigurableModel,
            self.mock_resource_config,
            ["scikit-learn", "pandas"],
            [],  # system_dependencies
            True,  # accelerate_downloads
            {},  # extra
        )

        model = RemoteModel(
            model_config,
            data_sources,
            metadata=metadata,
            debug=True,
            cache_enabled=False,
            timeout=300,
        )

        # Verify complex arguments are properly stored
        assert model._constructor_args == (model_config, data_sources)
        assert model._constructor_kwargs == {
            "metadata": metadata,
            "debug": True,
            "cache_enabled": False,
            "timeout": 300,
        }

        # Mock execution and verify serialization
        mock_stub = AsyncMock()
        mock_stub.execute_class_method.return_value = {
            "config_type": "dict",
            "sources_count": 2,
            "has_metadata": True,
            "options_count": 3,
        }

        async def mock_ensure_initialized():
            if model._initialized:
                return
            model._stub = mock_stub
            model._initialized = True

        with patch.object(
            model, "_ensure_initialized", side_effect=mock_ensure_initialized
        ):
            await model.get_config_summary()

            # Verify method call
            call_args = mock_stub.execute_class_method.call_args[0][0]

            # Verify constructor arguments are properly serialized
            assert len(call_args.constructor_args) == 2
            deserialized_config = cloudpickle.loads(
                base64.b64decode(call_args.constructor_args[0])
            )
            assert deserialized_config == model_config

            deserialized_sources = cloudpickle.loads(
                base64.b64decode(call_args.constructor_args[1])
            )
            assert deserialized_sources == data_sources

            # Verify constructor kwargs
            assert len(call_args.constructor_kwargs) == 4
            deserialized_metadata = cloudpickle.loads(
                base64.b64decode(call_args.constructor_kwargs["metadata"])
            )
            assert deserialized_metadata == metadata

    @pytest.mark.asyncio
    async def test_nested_class_instances_as_arguments(self):
        """Test passing instances of other classes as constructor arguments."""

        class DatabaseConnection:
            def __init__(self, host, port, database):
                self.host = host
                self.port = port
                self.database = database

            def get_connection_string(self):
                return f"{self.host}:{self.port}/{self.database}"

        class CacheConfig:
            def __init__(self, enabled=True, ttl=3600):
                self.enabled = enabled
                self.ttl = ttl

        class DataService:
            def __init__(self, db_connection, cache_config, api_keys=None):
                self.db = db_connection
                self.cache = cache_config
                self.api_keys = api_keys or []

            def get_service_info(self):
                return {
                    "db_connection": self.db.get_connection_string(),
                    "cache_enabled": self.cache.enabled,
                    "cache_ttl": self.cache.ttl,
                    "api_keys_count": len(self.api_keys),
                }

        # Create complex nested objects
        db_conn = DatabaseConnection("localhost", 5432, "testdb")
        cache_conf = CacheConfig(enabled=True, ttl=7200)
        api_keys = ["key1", "key2", "key3"]

        RemoteDataService = create_remote_class(
            DataService, self.mock_resource_config, ["psycopg2"], [], True, {}
        )

        service = RemoteDataService(db_conn, cache_conf, api_keys=api_keys)

        # Mock execution
        mock_stub = AsyncMock()
        mock_stub.execute_class_method.return_value = {
            "db_connection": "localhost:5432/testdb",
            "cache_enabled": True,
            "cache_ttl": 7200,
            "api_keys_count": 3,
        }

        async def mock_ensure_initialized():
            if service._initialized:
                return
            service._stub = mock_stub
            service._initialized = True

        with patch.object(
            service, "_ensure_initialized", side_effect=mock_ensure_initialized
        ):
            await service.get_service_info()

            # Verify serialization of complex nested objects
            call_args = mock_stub.execute_class_method.call_args[0][0]

            # Test deserialization of db_connection
            deserialized_db = cloudpickle.loads(
                base64.b64decode(call_args.constructor_args[0])
            )
            assert isinstance(deserialized_db, DatabaseConnection)
            assert deserialized_db.host == "localhost"
            assert deserialized_db.port == 5432

            # Test deserialization of cache_config
            deserialized_cache = cloudpickle.loads(
                base64.b64decode(call_args.constructor_args[1])
            )
            assert isinstance(deserialized_cache, CacheConfig)
            assert deserialized_cache.enabled is True
            assert deserialized_cache.ttl == 7200


class TestErrorHandlingInRemoteClassExecution:
    """Test error handling scenarios in remote class execution."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_resource_config = ServerlessResource(
            name="error-test", image="python:3.9", cpu=1, memory=512
        )

    @pytest.mark.asyncio
    async def test_remote_method_execution_error(self):
        """Test error handling when remote method execution fails."""

        class ErrorProneClass:
            def __init__(self, should_fail=False):
                self.should_fail = should_fail

            def risky_method(self, data):
                if self.should_fail:
                    raise ValueError("Intentional failure for testing")
                return f"Processed: {data}"

            def safe_method(self):
                return "This always works"

        RemoteErrorProneClass = create_remote_class(
            ErrorProneClass, self.mock_resource_config, [], [], True, {}
        )

        error_instance = RemoteErrorProneClass(should_fail=True)

        # Mock stub that raises an exception
        mock_stub = AsyncMock()
        mock_stub.execute_class_method.side_effect = Exception(
            "Remote execution failed: ValueError: Intentional failure for testing"
        )

        async def mock_ensure_initialized():
            if error_instance._initialized:
                return
            error_instance._stub = mock_stub
            error_instance._initialized = True

        with patch.object(
            error_instance, "_ensure_initialized", side_effect=mock_ensure_initialized
        ):
            # Test that the exception is properly propagated
            with pytest.raises(Exception, match="Remote execution failed"):
                await error_instance.risky_method("test_data")

    @pytest.mark.asyncio
    async def test_resource_initialization_error(self):
        """Test error handling when resource initialization fails."""

        class SimpleClass:
            def __init__(self):
                pass

            def simple_method(self):
                return "hello"

        RemoteSimpleClass = create_remote_class(
            SimpleClass, self.mock_resource_config, [], [], True, {}
        )

        instance = RemoteSimpleClass()

        # Mock initialization failure
        async def mock_failing_ensure_initialized():
            if instance._initialized:
                return
            raise ConnectionError("Failed to connect to remote resource")

        with patch.object(
            instance, "_ensure_initialized", side_effect=mock_failing_ensure_initialized
        ):
            # Test that initialization errors are properly propagated
            with pytest.raises(
                ConnectionError, match="Failed to connect to remote resource"
            ):
                await instance.simple_method()

    @pytest.mark.asyncio
    async def test_serialization_error_handling(self):
        """Test error handling for serialization issues."""

        class UnserializableClass:
            def __init__(self, file_handle=None):
                self.file_handle = file_handle  # File handles can't be pickled

            def process_file(self):
                return "Processing file"

        # Create instance with unserializable object
        import tempfile

        with tempfile.NamedTemporaryFile() as temp_file:
            RemoteUnserializableClass = create_remote_class(
                UnserializableClass, self.mock_resource_config, [], [], True, {}
            )

            # This should not fail during initialization (lazy serialization)
            instance = RemoteUnserializableClass(temp_file)

            # Mock ensure_initialized to avoid actual resource calls
            mock_stub = AsyncMock()

            async def mock_ensure_initialized():
                if instance._initialized:
                    return
                instance._stub = mock_stub
                instance._initialized = True

            with patch.object(
                instance, "_ensure_initialized", side_effect=mock_ensure_initialized
            ):
                # The error should occur during method call when trying to serialize
                # Mock cloudpickle.dumps to raise an error
                from runpod_flash.runtime.exceptions import SerializationError

                with patch(
                    "runpod_flash.runtime.serialization.cloudpickle.dumps",
                    side_effect=TypeError("Can't pickle file objects"),
                ):
                    with pytest.raises(
                        SerializationError, match="Can't pickle file objects"
                    ):
                        await instance.process_file()

    @pytest.mark.asyncio
    async def test_timeout_error_handling(self):
        """Test timeout error handling in remote execution."""

        class SlowClass:
            def __init__(self):
                pass

            def slow_method(self, duration):
                # Simulate a slow operation
                import time

                time.sleep(duration)
                return f"Completed after {duration} seconds"

        RemoteSlowClass = create_remote_class(
            SlowClass,
            self.mock_resource_config,
            [],
            [],
            True,
            {"timeout": 5},  # 5 second timeout
        )

        instance = RemoteSlowClass()

        # Mock stub that simulates timeout
        mock_stub = AsyncMock()
        mock_stub.execute_class_method.side_effect = asyncio.TimeoutError(
            "Operation timed out after 5 seconds"
        )

        async def mock_ensure_initialized():
            if instance._initialized:
                return
            instance._stub = mock_stub
            instance._initialized = True

        with patch.object(
            instance, "_ensure_initialized", side_effect=mock_ensure_initialized
        ):
            # Test timeout error handling
            with pytest.raises(asyncio.TimeoutError, match="Operation timed out"):
                await instance.slow_method(10)  # Request 10 seconds but timeout at 5

    def test_invalid_class_type_error(self):
        """Test error handling for invalid class types."""

        # Test with non-class object
        with pytest.raises(TypeError, match="Expected a class"):
            create_remote_class(
                "not_a_class",  # String instead of class
                self.mock_resource_config,
                [],
                [],
                True,
                {},
            )

        # Test with function instead of class
        def not_a_class():
            pass

        with pytest.raises(TypeError, match="Expected a class"):
            create_remote_class(
                not_a_class, self.mock_resource_config, [], [], True, {}
            )

        # Note: Testing class without __name__ is not practically possible
        # since Python classes always have __name__ attribute

    @pytest.mark.asyncio
    async def test_dependency_installation_error(self):
        """Test error handling when dependency installation fails."""

        class DependentClass:
            def __init__(self):
                pass

            def use_dependency(self):
                return "Using numpy successfully"

        RemoteDependentClass = create_remote_class(
            DependentClass,
            self.mock_resource_config,
            ["nonexistent-package==999.999.999"],  # Invalid package
            [],
            True,
            {},
        )

        instance = RemoteDependentClass()

        # Mock stub that simulates dependency installation failure
        mock_stub = AsyncMock()
        mock_stub.execute_class_method.side_effect = Exception(
            "Failed to install dependencies: nonexistent-package==999.999.999 not found"
        )

        async def mock_ensure_initialized():
            if instance._initialized:
                return
            instance._stub = mock_stub
            instance._initialized = True

        with patch.object(
            instance, "_ensure_initialized", side_effect=mock_ensure_initialized
        ):
            # Test dependency installation error
            with pytest.raises(Exception, match="Failed to install dependencies"):
                await instance.use_dependency()
