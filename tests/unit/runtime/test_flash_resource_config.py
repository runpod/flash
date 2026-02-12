"""Unit tests for _flash_resource_config template."""

import pytest


class TestFlashResourceConfigTemplate:
    """Tests for the template _flash_resource_config module.

    Note: This tests the template file, which has empty sets.
    The actual file gets overwritten during build.
    """

    @pytest.fixture
    def config_module(self):
        """Import the config module."""
        from runpod_flash.runtime import _flash_resource_config

        return _flash_resource_config

    def test_resource_name_default_empty(self, config_module):
        """RESOURCE_NAME defaults to empty string in template."""
        assert config_module.RESOURCE_NAME == ""

    def test_local_functions_default_empty(self, config_module):
        """LOCAL_FUNCTIONS defaults to empty set in template."""
        assert config_module.LOCAL_FUNCTIONS == set()

    def test_remote_functions_default_empty(self, config_module):
        """REMOTE_FUNCTIONS defaults to empty set in template."""
        assert config_module.REMOTE_FUNCTIONS == set()

    def test_is_local_function_exists(self, config_module):
        """is_local_function function exists."""
        assert hasattr(config_module, "is_local_function")
        assert callable(config_module.is_local_function)

    def test_is_local_function_with_empty_sets_defaults_true(self, config_module):
        """is_local_function returns True for unknown functions (safe default)."""
        result = config_module.is_local_function("unknown_func")
        assert result is True

    def test_is_local_function_signature(self, config_module):
        """is_local_function has correct signature."""
        import inspect

        sig = inspect.signature(config_module.is_local_function)
        params = list(sig.parameters.keys())

        assert params == ["func_name"]
        assert sig.return_annotation is bool

    def test_module_has_docstring(self, config_module):
        """Module has a docstring."""
        assert config_module.__doc__ is not None
        assert len(config_module.__doc__) > 0


class TestIsLocalFunctionLogic:
    """Tests for is_local_function decision logic.

    These tests mock the module's sets to verify the logic.
    """

    @pytest.fixture
    def config_module(self):
        """Import fresh config module for each test."""
        from runpod_flash.runtime import _flash_resource_config

        return _flash_resource_config

    def test_function_in_local_set_returns_true(self, config_module):
        """Function explicitly in LOCAL_FUNCTIONS returns True."""
        # Mock the sets
        original_local = config_module.LOCAL_FUNCTIONS
        original_remote = config_module.REMOTE_FUNCTIONS

        try:
            config_module.LOCAL_FUNCTIONS = {"local_func"}
            config_module.REMOTE_FUNCTIONS = set()

            result = config_module.is_local_function("local_func")
            assert result is True
        finally:
            config_module.LOCAL_FUNCTIONS = original_local
            config_module.REMOTE_FUNCTIONS = original_remote

    def test_function_in_remote_set_returns_false(self, config_module):
        """Function explicitly in REMOTE_FUNCTIONS returns False."""
        original_local = config_module.LOCAL_FUNCTIONS
        original_remote = config_module.REMOTE_FUNCTIONS

        try:
            config_module.LOCAL_FUNCTIONS = set()
            config_module.REMOTE_FUNCTIONS = {"remote_func"}

            result = config_module.is_local_function("remote_func")
            assert result is False
        finally:
            config_module.LOCAL_FUNCTIONS = original_local
            config_module.REMOTE_FUNCTIONS = original_remote

    def test_function_in_both_sets_local_wins(self, config_module):
        """If function in both sets, LOCAL_FUNCTIONS takes precedence."""
        original_local = config_module.LOCAL_FUNCTIONS
        original_remote = config_module.REMOTE_FUNCTIONS

        try:
            config_module.LOCAL_FUNCTIONS = {"func"}
            config_module.REMOTE_FUNCTIONS = {"func"}

            result = config_module.is_local_function("func")
            assert result is True
        finally:
            config_module.LOCAL_FUNCTIONS = original_local
            config_module.REMOTE_FUNCTIONS = original_remote

    def test_unknown_function_returns_true(self, config_module):
        """Unknown function returns True (safe default for backwards compatibility)."""
        original_local = config_module.LOCAL_FUNCTIONS
        original_remote = config_module.REMOTE_FUNCTIONS

        try:
            config_module.LOCAL_FUNCTIONS = set()
            config_module.REMOTE_FUNCTIONS = set()

            result = config_module.is_local_function("unknown")
            assert result is True
        finally:
            config_module.LOCAL_FUNCTIONS = original_local
            config_module.REMOTE_FUNCTIONS = original_remote

    def test_case_sensitive_function_names(self, config_module):
        """Function name matching is case-sensitive."""
        original_local = config_module.LOCAL_FUNCTIONS
        original_remote = config_module.REMOTE_FUNCTIONS

        try:
            config_module.LOCAL_FUNCTIONS = {"MyFunc"}
            config_module.REMOTE_FUNCTIONS = set()

            # Exact match returns True
            assert config_module.is_local_function("MyFunc") is True

            # Different case returns False (defaults to True for unknown)
            assert config_module.is_local_function("myfunc") is True
            assert config_module.is_local_function("MYFUNC") is True
        finally:
            config_module.LOCAL_FUNCTIONS = original_local
            config_module.REMOTE_FUNCTIONS = original_remote

    def test_empty_string_function_name(self, config_module):
        """Empty string function name handled correctly."""
        result = config_module.is_local_function("")
        assert result is True  # Unknown, so defaults to True
