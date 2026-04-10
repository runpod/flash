"""
Unit tests for runpod_flash.execute_class module.
"""

import asyncio
import base64
import inspect
from unittest.mock import AsyncMock, Mock, patch

import cloudpickle
import pytest
from runpod_flash.core.resources import ServerlessResource
from runpod_flash.execute_class import (
    _SERIALIZED_CLASS_CACHE,
    create_remote_class,
    extract_class_code_simple,
)
from runpod_flash.protos.remote_execution import FunctionRequest


class TestExtractClassCodeSimple:
    """Test cases for extract_class_code_simple function."""

    def test_extract_simple_class(self):
        """Test extracting code from a simple class."""

        class SimpleClass:
            def __init__(self, value):
                self.value = value

            def get_value(self):
                return self.value

        result = extract_class_code_simple(SimpleClass)

        assert "class SimpleClass:" in result
        assert "def __init__(self, value):" in result
        assert "def get_value(self):" in result
        assert "self.value = value" in result
        assert "return self.value" in result

        # Verify the code compiles
        compile(result, "<string>", "exec")

    def test_extract_class_with_decorators(self):
        """Test extracting code from a class with decorators (should ignore decorators)."""

        def some_decorator(cls):
            return cls

        @some_decorator
        class DecoratedClass:
            def method(self):
                pass

        result = extract_class_code_simple(DecoratedClass)

        # Should start with class definition, not decorators
        lines = result.strip().split("\n")
        assert lines[0].startswith("class DecoratedClass:")
        assert "@" not in lines[0]  # No decorator in class line

        # Verify the code compiles
        compile(result, "<string>", "exec")

    def test_extract_indented_class(self):
        """Test extracting code from an indented class (nested)."""
        # Create a nested class by exec'ing it
        code = """
def create_nested():
    class NestedClass:
        def __init__(self):
            self.data = "nested"
        
        def get_data(self):
            return self.data
    return NestedClass
"""
        namespace = {}
        exec(code, namespace)
        NestedClass = namespace["create_nested"]()

        result = extract_class_code_simple(NestedClass)

        # Should be properly dedented
        lines = result.split("\n")
        assert lines[0] == "class NestedClass:"
        assert not lines[0].startswith(" ")  # Should not have leading whitespace

        # Verify the code compiles
        compile(result, "<string>", "exec")

    def test_extract_class_with_methods_and_properties(self):
        """Test extracting code from a class with various method types."""

        class ComplexClass:
            def __init__(self, name):
                self.name = name

            def instance_method(self):
                return f"Hello {self.name}"

            @classmethod
            def class_method(cls):
                return "class method"

            @staticmethod
            def static_method():
                return "static method"

            @property
            def name_property(self):
                return self.name.upper()

        result = extract_class_code_simple(ComplexClass)

        assert "class ComplexClass:" in result
        assert "def __init__(self, name):" in result
        assert "def instance_method(self):" in result
        assert "def class_method(cls):" in result
        assert "def static_method():" in result
        assert "def name_property(self):" in result

        # Verify the code compiles
        compile(result, "<string>", "exec")

    def test_extract_class_fallback_on_error(self):
        """Test fallback behavior when source extraction fails."""
        # Create a mock class that will cause inspect.getsource to fail
        mock_class = type(
            "MockClass",
            (),
            {
                "__name__": "MockClass",
                "method1": lambda self, x, y: None,
                "method2": lambda self, *args, **kwargs: None,
            },
        )

        # Mock inspect.getsource to raise an exception
        with patch(
            "runpod_flash.execute_class.inspect.getsource",
            side_effect=OSError("No source available"),
        ):
            with patch("runpod_flash.execute_class.log.warning") as mock_log_warning:
                result = extract_class_code_simple(mock_class)

                # Should use fallback
                assert "class MockClass:" in result
                assert "def __init__(self, *args, **kwargs):" in result
                assert "pass" in result

                # Verify fallback was triggered
                mock_log_warning.assert_any_call(
                    "Could not extract class code for MockClass: No source available"
                )
                mock_log_warning.assert_any_call(
                    "Falling back to basic class structure"
                )

    def test_extract_class_with_complex_signatures(self):
        """Test extracting class with complex method signatures."""

        class ClassWithComplexMethods:
            def method_with_defaults(self, a, b=10, c="default"):
                return a + b

            def method_with_varargs(self, *args, **kwargs):
                return len(args) + len(kwargs)

            def method_with_annotations(self, x: int, y: str = "hello") -> str:
                return f"{x}: {y}"

        result = extract_class_code_simple(ClassWithComplexMethods)

        assert 'def method_with_defaults(self, a, b=10, c="default"):' in result
        assert "def method_with_varargs(self, *args, **kwargs):" in result
        assert (
            'def method_with_annotations(self, x: int, y: str = "hello") -> str:'
            in result
        )

        # Verify the code compiles
        compile(result, "<string>", "exec")

    def test_extract_class_empty_methods(self):
        """Test extracting class with empty methods."""

        class EmptyMethodsClass:
            def empty_method(self):
                pass

            def another_empty(self):
                """Just a docstring."""
                pass

        result = extract_class_code_simple(EmptyMethodsClass)

        assert "class EmptyMethodsClass:" in result
        assert "def empty_method(self):" in result
        assert "def another_empty(self):" in result

        # Verify the code compiles
        compile(result, "<string>", "exec")

    def test_extract_class_with_trailing_whitespace(self):
        """Test that trailing empty lines are removed."""

        # This test ensures the extract function handles trailing whitespace properly
        class SimpleClass:
            def method(self):
                return "test"

        result = extract_class_code_simple(SimpleClass)

        # Should not end with multiple newlines
        assert not result.endswith("\n\n\n")
        lines = result.split("\n")
        # Last line should not be empty
        assert lines[-1].strip() != ""


class TestCreateRemoteClass:
    """Test cases for create_remote_class function and RemoteClassWrapper."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_resource_config = ServerlessResource(
            name="test-resource", image="test-image:latest", cpu=1, memory=512
        )
        self.dependencies = ["numpy", "pandas"]
        self.system_dependencies = ["git"]

    def test_create_remote_class_basic(self):
        """Test basic remote class creation."""

        class TestClass:
            def __init__(self, value):
                self.value = value

            def get_value(self):
                return self.value

        RemoteWrapper = create_remote_class(
            TestClass,
            self.mock_resource_config,
            self.dependencies,
            self.system_dependencies,
            True,
        )

        # Should return a class
        assert inspect.isclass(RemoteWrapper)
        assert RemoteWrapper.__name__ == "RemoteClassWrapper"

    def test_remote_class_wrapper_initialization(self):
        """Test RemoteClassWrapper initialization."""

        class TestClass:
            def __init__(self, value, name="default"):
                self.value = value
                self.name = name

        RemoteWrapper = create_remote_class(
            TestClass,
            self.mock_resource_config,
            self.dependencies,
            self.system_dependencies,
            True,
        )

        instance = RemoteWrapper(42, name="test")

        assert instance._class_type == TestClass
        assert instance._resource_config == self.mock_resource_config
        assert instance._dependencies == self.dependencies
        assert instance._system_dependencies == self.system_dependencies
        assert instance._constructor_args == (42,)
        assert instance._constructor_kwargs == {"name": "test"}
        assert instance._instance_id.startswith("TestClass_")
        assert not instance._initialized
        assert instance._clean_class_code is not None

    def test_remote_class_wrapper_initialization_defaults(self):
        """Test RemoteClassWrapper initialization with default values."""

        class TestClass:
            pass

        RemoteWrapper = create_remote_class(
            TestClass,
            self.mock_resource_config,
            None,  # dependencies
            None,  # system_dependencies
            True,  # accelerate_downloads
        )

        instance = RemoteWrapper()

        assert instance._dependencies == []
        assert instance._system_dependencies == []
        assert instance._constructor_args == ()
        assert instance._constructor_kwargs == {}

    @pytest.mark.asyncio
    async def test_ensure_initialized(self):
        """Test _ensure_initialized method."""

        class TestClass:
            pass

        RemoteWrapper = create_remote_class(
            TestClass,
            self.mock_resource_config,
            self.dependencies,
            self.system_dependencies,
            True,
        )

        instance = RemoteWrapper()

        # Mock the stub
        mock_stub = Mock()

        # Mock the entire _ensure_initialized method to avoid ResourceManager issues
        async def mock_ensure_initialized():
            if instance._initialized:
                return
            instance._stub = mock_stub
            instance._initialized = True

        with patch.object(
            instance, "_ensure_initialized", side_effect=mock_ensure_initialized
        ):
            await instance._ensure_initialized()

            assert instance._initialized
            assert instance._stub == mock_stub

    @pytest.mark.asyncio
    async def test_ensure_initialized_idempotent(self):
        """Test that _ensure_initialized is idempotent."""

        class TestClass:
            pass

        RemoteWrapper = create_remote_class(
            TestClass,
            self.mock_resource_config,
            self.dependencies,
            self.system_dependencies,
            True,
        )

        instance = RemoteWrapper()

        # Mock the stub
        mock_stub = Mock()

        # Mock the entire _ensure_initialized method to test idempotency
        call_count = 0

        async def mock_ensure_initialized():
            nonlocal call_count
            if instance._initialized:
                return
            call_count += 1
            instance._stub = mock_stub
            instance._initialized = True

        with patch.object(
            instance, "_ensure_initialized", side_effect=mock_ensure_initialized
        ):
            # Call twice
            await instance._ensure_initialized()
            await instance._ensure_initialized()

            # Should only initialize once
            assert call_count == 1

    def test_getattr_private_attributes(self):
        """Test that private attributes raise AttributeError."""

        class TestClass:
            pass

        RemoteWrapper = create_remote_class(
            TestClass,
            self.mock_resource_config,
            self.dependencies,
            self.system_dependencies,
            True,
        )

        instance = RemoteWrapper()

        with pytest.raises(
            AttributeError,
            match="'RemoteClassWrapper' object has no attribute '_private'",
        ):
            instance._private

    @pytest.mark.asyncio
    async def test_method_proxy_execution(self):
        """Test method proxy execution."""

        class TestClass:
            def __init__(self, value):
                self.value = value

            def get_value(self):
                return self.value

            def add(self, x, y=10):
                return x + y + self.value

        RemoteWrapper = create_remote_class(
            TestClass,
            self.mock_resource_config,
            self.dependencies,
            self.system_dependencies,
            True,
        )

        instance = RemoteWrapper(5)

        # Mock the initialization and stub
        mock_stub = AsyncMock()
        expected_result = "test_result"
        mock_stub.execute_class_method.return_value = expected_result

        # Mock the _ensure_initialized method to avoid ResourceManager issues
        async def mock_ensure_initialized():
            if instance._initialized:
                return
            instance._stub = mock_stub
            instance._initialized = True

        with patch.object(
            instance, "_ensure_initialized", side_effect=mock_ensure_initialized
        ):
            # Call a method
            result = await instance.add(20, y=30)

            assert result == expected_result
            assert instance._initialized

            # Verify the request was constructed correctly
            call_args = mock_stub.execute_class_method.call_args[0][0]
            assert isinstance(call_args, FunctionRequest)
            assert call_args.execution_type == "class"
            assert call_args.class_name == "TestClass"
            assert call_args.method_name == "add"
            assert call_args.instance_id == instance._instance_id
            assert call_args.dependencies == self.dependencies
            assert call_args.system_dependencies == self.system_dependencies

            # Verify serialized arguments
            assert len(call_args.args) == 1
            assert cloudpickle.loads(base64.b64decode(call_args.args[0])) == 20
            assert len(call_args.kwargs) == 1
            assert cloudpickle.loads(base64.b64decode(call_args.kwargs["y"])) == 30

            # Verify serialized constructor arguments
            assert len(call_args.constructor_args) == 1
            assert (
                cloudpickle.loads(base64.b64decode(call_args.constructor_args[0])) == 5
            )

    @pytest.mark.asyncio
    async def test_method_proxy_create_new_instance_flag(self):
        """Test create_new_instance flag behavior."""

        class TestClass:
            def method1(self):
                return "result1"

            def method2(self):
                return "result2"

        RemoteWrapper = create_remote_class(
            TestClass,
            self.mock_resource_config,
            self.dependencies,
            self.system_dependencies,
            True,
        )

        instance = RemoteWrapper()

        # Mock the initialization and stub
        mock_stub = AsyncMock()
        mock_stub.execute_class_method.return_value = "result"

        # Mock the _ensure_initialized method to avoid ResourceManager issues
        async def mock_ensure_initialized():
            if instance._initialized:
                return
            instance._stub = mock_stub
            instance._initialized = True

        with patch.object(
            instance, "_ensure_initialized", side_effect=mock_ensure_initialized
        ):
            # Test current behavior: create_new_instance is False after _ensure_initialized sets _stub
            await instance.method1()
            first_call_args = mock_stub.execute_class_method.call_args[0][0]
            # After _ensure_initialized, _stub exists, so create_new_instance is False
            assert first_call_args.create_new_instance is False

            # Subsequent calls also have create_new_instance as False
            await instance.method2()
            second_call_args = mock_stub.execute_class_method.call_args[0][0]
            assert second_call_args.create_new_instance is False

    @pytest.mark.asyncio
    async def test_method_proxy_no_args_no_kwargs(self):
        """Test method proxy with no arguments."""

        class TestClass:
            def simple_method(self):
                return "simple"

        RemoteWrapper = create_remote_class(
            TestClass, self.mock_resource_config, [], [], True
        )

        instance = RemoteWrapper()

        # Mock the initialization and stub
        mock_stub = AsyncMock()
        mock_stub.execute_class_method.return_value = "result"

        # Mock the _ensure_initialized method to avoid ResourceManager issues
        async def mock_ensure_initialized():
            if instance._initialized:
                return
            instance._stub = mock_stub
            instance._initialized = True

        with patch.object(
            instance, "_ensure_initialized", side_effect=mock_ensure_initialized
        ):
            await instance.simple_method()

            call_args = mock_stub.execute_class_method.call_args[0][0]
            assert call_args.args == []
            assert call_args.kwargs == {}
            assert call_args.constructor_args == []
            assert call_args.constructor_kwargs == {}

    def test_class_code_extraction_in_wrapper(self):
        """Test that class code is extracted during wrapper initialization."""

        class TestClass:
            def __init__(self):
                pass

            def test_method(self):
                return "test"

        RemoteWrapper = create_remote_class(
            TestClass,
            self.mock_resource_config,
            self.dependencies,
            self.system_dependencies,
            True,
        )

        instance = RemoteWrapper()

        # Verify class code was extracted
        assert instance._clean_class_code is not None
        assert "class TestClass:" in instance._clean_class_code
        assert "def test_method(self):" in instance._clean_class_code

        # Verify it compiles
        compile(instance._clean_class_code, "<string>", "exec")

    def test_uuid_generation(self):
        """Test that instance IDs are unique."""

        class TestClass:
            pass

        RemoteWrapper = create_remote_class(
            TestClass,
            self.mock_resource_config,
            self.dependencies,
            self.system_dependencies,
            True,
        )

        instance1 = RemoteWrapper()
        instance2 = RemoteWrapper()

        assert instance1._instance_id != instance2._instance_id
        assert instance1._instance_id.startswith("TestClass_")
        assert instance2._instance_id.startswith("TestClass_")

        # Verify UUID format (8 hex characters)
        id1_suffix = instance1._instance_id.split("_")[1]
        id2_suffix = instance2._instance_id.split("_")[1]
        assert len(id1_suffix) == 8
        assert len(id2_suffix) == 8
        assert all(c in "0123456789abcdef" for c in id1_suffix)
        assert all(c in "0123456789abcdef" for c in id2_suffix)


class TestExecuteClassIntegration:
    """Integration tests for execute_class module functionality."""

    def test_full_workflow_mock(self):
        """Test the complete workflow with mocked components."""

        class CalculatorClass:
            def __init__(self, initial_value=0):
                self.value = initial_value

            def add(self, x):
                self.value += x
                return self.value

            def multiply(self, x):
                self.value *= x
                return self.value

            def get_value(self):
                return self.value

        # Test that we can create a remote wrapper and it has the right structure
        resource_config = ServerlessResource(
            name="calculator-resource", image="python:3.9", cpu=1, memory=256
        )

        RemoteCalculator = create_remote_class(
            CalculatorClass, resource_config, ["numpy"], [], True
        )

        calculator = RemoteCalculator(10)

        # Verify the wrapper is set up correctly
        assert calculator._class_type == CalculatorClass
        assert calculator._constructor_args == (10,)
        assert "class CalculatorClass:" in calculator._clean_class_code
        assert "def add(self, x):" in calculator._clean_class_code
        assert not calculator._initialized

        # Verify method proxies are created dynamically
        add_method = calculator.add
        assert callable(add_method)
        assert asyncio.iscoroutinefunction(add_method)

    def test_class_code_preservation(self):
        """Test that complex class structures are preserved in extracted code."""

        class ComplexClass:
            CLASS_VAR = "class_variable"

            def __init__(self, name, *args, **kwargs):
                self.name = name
                self.args = args
                self.kwargs = kwargs

            @classmethod
            def create_default(cls):
                return cls("default")

            @staticmethod
            def static_helper(x, y):
                return x + y

            @property
            def display_name(self):
                return f"Complex: {self.name}"

            def complex_method(
                self, a: int, b: str = "default", *args, **kwargs
            ) -> str:
                return f"{a}-{b}-{len(args)}-{len(kwargs)}"

        RemoteWrapper = create_remote_class(
            ComplexClass,
            ServerlessResource(name="test", image="test:latest", cpu=1, memory=256),
            [],  # dependencies
            [],  # system_dependencies
            True,  # accelerate_downloads
        )

        instance = RemoteWrapper("test", extra_arg=True)
        code = instance._clean_class_code

        # Verify all elements are preserved
        assert 'CLASS_VAR = "class_variable"' in code
        assert "def __init__(self, name, *args, **kwargs):" in code
        assert "def create_default(cls):" in code
        assert "def static_helper(x, y):" in code
        assert "def display_name(self):" in code
        assert "def complex_method(" in code
        assert ") -> str:" in code

        # Verify the code compiles and can be executed
        namespace = {}
        exec(code, namespace)
        ReconstructedClass = namespace["ComplexClass"]

        # Test that the reconstructed class works
        obj = ReconstructedClass("test")
        assert obj.name == "test"
        assert obj.CLASS_VAR == "class_variable"


class TestRemoteClassWrapperPickle:
    """Test pickle support for RemoteClassWrapper (AE-2745).

    asyncio.Lock is not picklable. RemoteClassWrapper must implement
    __getstate__/__setstate__ so ResourceManager._save_resources() can
    persist state via cloudpickle without raising.
    """

    def setup_method(self):
        _SERIALIZED_CLASS_CACHE.clear()
        self.resource_config = ServerlessResource(
            name="test-resource", image="test-image:latest", cpu=1, memory=512
        )

    def test_pickle_roundtrip(self):
        """RemoteClassWrapper instances must survive cloudpickle roundtrip."""

        class MyModel:
            def predict(self, x):
                return x

        RemoteWrapper = create_remote_class(
            MyModel, self.resource_config, ["numpy"], ["git"], True
        )
        instance = RemoteWrapper(42, name="test")

        data = cloudpickle.dumps(instance)
        restored = cloudpickle.loads(data)

        assert restored._class_type == MyModel
        assert restored._constructor_args == (42,)
        assert restored._constructor_kwargs == {"name": "test"}
        assert restored._dependencies == ["numpy"]
        assert restored._system_dependencies == ["git"]
        assert restored._instance_id == instance._instance_id
        assert not restored._initialized
        assert type(restored._init_lock) is type(asyncio.Lock())

    def test_pickle_excludes_lock_and_stub(self):
        """Pickle state must not contain non-picklable fields."""

        class MyModel:
            def predict(self, x):
                return x

        RemoteWrapper = create_remote_class(MyModel, self.resource_config, [], [], True)
        instance = RemoteWrapper()

        state = instance.__getstate__()

        assert "_init_lock" not in state
        assert "_stub" not in state
        assert state["_initialized"] is False

    def test_pickle_resets_initialized_flag(self):
        """Unpickled instance must re-initialize on next use."""

        class MyModel:
            def predict(self, x):
                return x

        RemoteWrapper = create_remote_class(MyModel, self.resource_config, [], [], True)
        instance = RemoteWrapper()
        instance._initialized = True
        instance._stub = "fake_stub"

        data = cloudpickle.dumps(instance)
        restored = cloudpickle.loads(data)

        assert not restored._initialized
        assert not hasattr(restored, "_stub")
        assert type(restored._init_lock) is type(asyncio.Lock())

    def test_pickle_inside_tuple_like_save_resources(self):
        """Simulate ResourceManager._save_resources() pickle pattern."""

        class MyModel:
            def predict(self, x):
                return x

        RemoteWrapper = create_remote_class(MyModel, self.resource_config, [], [], True)
        instance = RemoteWrapper()

        resources = {"uid1": instance}
        configs = {"uid1": "some_hash"}
        payload = (resources, configs)

        data = cloudpickle.dumps(payload)
        restored_resources, restored_configs = cloudpickle.loads(data)

        assert "uid1" in restored_resources
        assert not restored_resources["uid1"]._initialized
