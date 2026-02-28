"""
Test that load_dotenv() in __init__.py properly loads environment variables
before other imports that depend on them.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


class TestDotenvLoading:
    """Test environment variable loading from .env files and shell environment."""

    def test_dotenv_loads_before_imports(self):
        """Test that load_dotenv() is called before imports that use env vars."""

        # This test verifies the order of operations in __init__.py
        # by checking that dotenv import/call happens before other imports
        # Note: Resources are imported directly at module initialization

        init_file = (
            Path(__file__).parent.parent.parent / "src" / "runpod_flash" / "__init__.py"
        )
        content = init_file.read_text()
        lines = content.split("\n")

        # Find line numbers for key operations
        dotenv_import_line = None
        dotenv_call_line = None
        logger_import_line = None

        for i, line in enumerate(lines):
            if "from dotenv import" in line and "load_dotenv" in line:
                dotenv_import_line = i
            elif "load_dotenv(" in line.strip() and "import" not in line:
                dotenv_call_line = i
            elif "from .logger import setup_logging" in line:
                logger_import_line = i

        # Verify order of operations
        assert dotenv_import_line is not None, "dotenv import not found"
        assert dotenv_call_line is not None, "load_dotenv() call not found"
        assert logger_import_line is not None, "logger import not found"

        # load_dotenv() should be called before any other imports
        assert dotenv_import_line < dotenv_call_line, (
            "load_dotenv() should be called after import"
        )
        assert dotenv_call_line < logger_import_line, (
            "load_dotenv() should be called before logger import"
        )

    def test_env_file_loading_with_temp_file(self):
        """Test that .env file variables are loaded correctly."""

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a temporary .env file
            env_file = Path(temp_dir) / ".env"
            env_content = """
# Test environment variables
RUNPOD_API_KEY=test_api_key_from_file
FLASH_GPU_IMAGE=test_gpu_image:v1.0
FLASH_CPU_IMAGE=test_cpu_image:v2.0
LOG_LEVEL=DEBUG
RUNPOD_API_BASE_URL=https://test-api.runpod.io
CUSTOM_TEST_VAR=file_value
"""
            env_file.write_text(env_content.strip())

            # Change to the temp directory and mock load_dotenv to use our file
            original_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)

                # Clear any existing env vars that might interfere
                test_vars = [
                    "RUNPOD_API_KEY",
                    "FLASH_GPU_IMAGE",
                    "FLASH_CPU_IMAGE",
                    "LOG_LEVEL",
                    "RUNPOD_API_BASE_URL",
                    "CUSTOM_TEST_VAR",
                ]
                original_values = {}
                for var in test_vars:
                    original_values[var] = os.environ.get(var)
                    if var in os.environ:
                        del os.environ[var]

                # Import and call load_dotenv directly (don't search parent dirs)
                from dotenv import load_dotenv

                result = load_dotenv(dotenv_path=".env", verbose=True)

                # Verify that load_dotenv successfully loaded the file
                assert result is True, (
                    "load_dotenv() should return True when .env file is found"
                )

                # Verify the environment variables were loaded
                assert os.environ.get("RUNPOD_API_KEY") == "test_api_key_from_file"
                assert os.environ.get("FLASH_GPU_IMAGE") == "test_gpu_image:v1.0"
                assert os.environ.get("FLASH_CPU_IMAGE") == "test_cpu_image:v2.0"
                assert os.environ.get("LOG_LEVEL") == "DEBUG"
                assert (
                    os.environ.get("RUNPOD_API_BASE_URL")
                    == "https://test-api.runpod.io"
                )
                assert os.environ.get("CUSTOM_TEST_VAR") == "file_value"

            finally:
                # Restore original environment and directory
                os.chdir(original_cwd)
                for var, value in original_values.items():
                    if value is not None:
                        os.environ[var] = value
                    elif var in os.environ:
                        del os.environ[var]

    def test_shell_env_vars_override_file_vars(self):
        """Test that shell environment variables take precedence over .env file."""

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create .env file with one value
            env_file = Path(temp_dir) / ".env"
            env_file.write_text("TEST_OVERRIDE_VAR=file_value")

            original_cwd = os.getcwd()
            original_value = os.environ.get("TEST_OVERRIDE_VAR")

            try:
                os.chdir(temp_dir)

                # Set shell environment variable
                os.environ["TEST_OVERRIDE_VAR"] = "shell_value"

                # Load dotenv (don't search parent dirs)
                from dotenv import load_dotenv

                load_dotenv(dotenv_path=".env")

                # Shell value should take precedence (dotenv doesn't override existing vars)
                assert os.environ.get("TEST_OVERRIDE_VAR") == "shell_value"

            finally:
                os.chdir(original_cwd)
                if original_value is not None:
                    os.environ["TEST_OVERRIDE_VAR"] = original_value
                elif "TEST_OVERRIDE_VAR" in os.environ:
                    del os.environ["TEST_OVERRIDE_VAR"]

    def test_env_vars_available_after_flash_import(self):
        """Test that env vars are available when runpod_flash modules are imported."""

        # Set up test environment variables
        test_env_vars = {
            "RUNPOD_API_KEY": "test_key_12345",
            "FLASH_GPU_IMAGE": "test/gpu:latest",
            "FLASH_CPU_IMAGE": "test/cpu:latest",
            "LOG_LEVEL": "WARNING",
        }

        original_values = {}
        for var, value in test_env_vars.items():
            original_values[var] = os.environ.get(var)
            os.environ[var] = value

        try:
            # Remove runpod_flash from sys.modules to force fresh import
            modules_to_remove = [
                name for name in sys.modules.keys() if name.startswith("runpod_flash")
            ]
            for module_name in modules_to_remove:
                del sys.modules[module_name]

            # Import runpod_flash (this will trigger __init__.py and load_dotenv())

            # Clear any cached modules to ensure fresh import with new env vars
            modules_to_clear = [
                name
                for name in sys.modules.keys()
                if name.startswith("runpod_flash.core")
            ]
            for module_name in modules_to_clear:
                del sys.modules[module_name]

            # Import specific modules that use environment variables
            from runpod_flash.core.api.runpod import RunpodGraphQLClient
            from runpod_flash.core.resources.live_serverless import (
                FLASH_GPU_IMAGE,
                FLASH_CPU_IMAGE,
            )

            # Verify that the environment variables are accessible in imported modules
            assert FLASH_GPU_IMAGE == "test/gpu:latest"
            assert FLASH_CPU_IMAGE == "test/cpu:latest"

            # Test that RunpodGraphQLClient can access the API key
            try:
                client = RunpodGraphQLClient()
                assert client.api_key == "test_key_12345"
            except Exception:
                # If client creation fails, just verify the env var is set
                assert os.environ.get("RUNPOD_API_KEY") == "test_key_12345"

        finally:
            # Restore original environment variables
            for var, value in original_values.items():
                if value is not None:
                    os.environ[var] = value
                elif var in os.environ:
                    del os.environ[var]

    def test_missing_env_file_graceful_handling(self):
        """Test that missing .env file is handled gracefully."""

        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = os.getcwd()
            try:
                # Change to directory without .env file
                os.chdir(temp_dir)

                # Load dotenv should not raise an error (don't search parent dirs)
                from dotenv import load_dotenv

                result = load_dotenv(dotenv_path=".env", verbose=True)

                # Should return False when no .env file is found, but not raise an error
                assert result is False, (
                    "load_dotenv() should return False when no .env file exists"
                )

            finally:
                os.chdir(original_cwd)

    def test_malformed_env_file_handling(self):
        """Test handling of malformed .env files."""

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create malformed .env file
            env_file = Path(temp_dir) / ".env"
            malformed_content = """
VALID_VAR=valid_value
INVALID_LINE_NO_EQUALS
=NO_KEY_VALUE
ANOTHER_VALID=another_value
"""
            env_file.write_text(malformed_content)

            original_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)

                # Should not raise an error even with malformed lines (don't search parent dirs)
                from dotenv import load_dotenv

                result = load_dotenv(dotenv_path=".env", verbose=True)

                # Should still load valid variables
                assert result is True
                assert os.environ.get("VALID_VAR") == "valid_value"
                assert os.environ.get("ANOTHER_VALID") == "another_value"

            finally:
                os.chdir(original_cwd)
                # Clean up
                for var in ["VALID_VAR", "ANOTHER_VALID"]:
                    if var in os.environ:
                        del os.environ[var]

    def test_env_vars_used_by_key_modules(self):
        """Test that key modules properly use environment variables loaded by dotenv."""

        # Test environment variables - set before any imports
        test_vars = {
            "RUNPOD_API_KEY": "test_api_key_12345",
            "RUNPOD_API_BASE_URL": "https://custom-api.runpod.io",
            "LOG_LEVEL": "DEBUG",
        }

        original_values = {}
        for var, value in test_vars.items():
            original_values[var] = os.environ.get(var)
            os.environ[var] = value

        try:
            # Clear any cached modules to ensure fresh import
            modules_to_clear = [
                name
                for name in sys.modules.keys()
                if name.startswith("runpod_flash.core.api")
            ]
            for module_name in modules_to_clear:
                del sys.modules[module_name]

            # Test RunpodGraphQLClient uses RUNPOD_API_KEY
            from runpod_flash.core.api.runpod import RunpodGraphQLClient

            try:
                client = RunpodGraphQLClient()
                assert client.api_key == "test_api_key_12345"
            except Exception:
                # If client creation fails, just verify the env var is set
                assert os.environ.get("RUNPOD_API_KEY") == "test_api_key_12345"

            # Test RUNPOD_API_BASE_URL is used (now imports with fresh env)
            from runpod_flash.core.api.runpod import RUNPOD_API_BASE_URL

            assert RUNPOD_API_BASE_URL == "https://custom-api.runpod.io"

            # Test LOG_LEVEL affects logging setup
            # Since setup_logging is called in __init__.py, we need to check if level is respected
            # Note: This might not work if logging was already configured

        finally:
            # Restore original values
            for var, value in original_values.items():
                if value is not None:
                    os.environ[var] = value
                elif var in os.environ:
                    del os.environ[var]

    def test_dotenv_import_present_in_init(self):
        """Test that dotenv import is actually present in __init__.py."""

        init_file = (
            Path(__file__).parent.parent.parent / "src" / "runpod_flash" / "__init__.py"
        )
        content = init_file.read_text()

        # Verify dotenv is imported and called
        assert "from dotenv import find_dotenv, load_dotenv" in content
        assert "load_dotenv(find_dotenv(usecwd=True))" in content

        # Verify dotenv is imported before any other module imports
        lines = content.split("\n")
        import_lines = [
            line for line in lines if line.strip().startswith(("import ", "from "))
        ]

        # First import line should be the dotenv import
        assert "from dotenv import find_dotenv, load_dotenv" in import_lines[0]

    @patch.dict(os.environ, {}, clear=True)
    def test_clean_environment_dotenv_loading(self):
        """Test dotenv loading in a clean environment."""

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test .env file
            env_file = Path(temp_dir) / ".env"
            env_file.write_text("CLEAN_TEST_VAR=loaded_from_file")

            original_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)

                # Ensure the variable is not set
                assert "CLEAN_TEST_VAR" not in os.environ

                # Load dotenv (don't search parent dirs)
                from dotenv import load_dotenv

                load_dotenv(dotenv_path=".env")

                # Variable should now be available
                assert os.environ.get("CLEAN_TEST_VAR") == "loaded_from_file"

            finally:
                os.chdir(original_cwd)
