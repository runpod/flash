"""Tests for API key validation and error handling.

Verifies that RunpodAPIKeyError provides helpful error messages
with documentation URLs and setup instructions.
"""

import pytest

from runpod_flash.core.exceptions import RunpodAPIKeyError
from runpod_flash.core.validation import validate_api_key, validate_api_key_with_context


class TestRunpodAPIKeyError:
    """Test custom RunpodAPIKeyError exception."""

    def test_default_error_message_contains_url(self):
        """Test that default error message includes documentation URL."""
        error = RunpodAPIKeyError()
        error_message = str(error)

        assert "https://docs.runpod.io/get-started/api-keys" in error_message

    def test_default_error_message_contains_setup_methods(self):
        """Test that default error message includes setup instructions."""
        error = RunpodAPIKeyError()
        error_message = str(error)

        assert "export RUNPOD_API_KEY" in error_message
        assert ".env" in error_message
        assert "flash login" in error_message

    def test_default_error_message_explains_requirement(self):
        """Test that error message explains missing API key."""
        error = RunpodAPIKeyError()
        error_message = str(error)

        assert "RUNPOD_API_KEY" in error_message
        assert "No RunPod API key found" in error_message

    def test_custom_error_message(self):
        """Test that custom error messages can be provided."""
        custom_msg = "Custom error message"
        error = RunpodAPIKeyError(custom_msg)

        assert str(error) == custom_msg


class TestValidateAPIKey:
    """Test validate_api_key function."""

    def test_validate_api_key_success(self, mock_env_vars):
        """Test that validate_api_key returns key when present."""
        api_key = validate_api_key()

        assert api_key == "test_api_key_123"

    def test_validate_api_key_missing_raises_error(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that validate_api_key raises RunpodAPIKeyError when key missing."""
        monkeypatch.delenv("RUNPOD_API_KEY", raising=False)

        with pytest.raises(RunpodAPIKeyError) as exc_info:
            validate_api_key()

        assert "RUNPOD_API_KEY" in str(exc_info.value)

    def test_validate_api_key_empty_raises_error(self, monkeypatch: pytest.MonkeyPatch):
        """Test that validate_api_key raises error when key is empty string."""
        monkeypatch.setenv("RUNPOD_API_KEY", "")

        with pytest.raises(RunpodAPIKeyError):
            validate_api_key()

    def test_validate_api_key_whitespace_raises_error(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that validate_api_key raises error when key is only whitespace."""
        monkeypatch.setenv("RUNPOD_API_KEY", "   ")

        with pytest.raises(RunpodAPIKeyError):
            validate_api_key()


class TestValidateAPIKeyWithContext:
    """Test validate_api_key_with_context function."""

    def test_validate_with_context_success(self, mock_env_vars):
        """Test that validation succeeds when key is present."""
        api_key = validate_api_key_with_context("deploy resource")

        assert api_key == "test_api_key_123"

    def test_validate_with_context_adds_operation_context(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that error message includes operation context."""
        monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
        operation = "deploy GPU worker"

        with pytest.raises(RunpodAPIKeyError) as exc_info:
            validate_api_key_with_context(operation)

        error_message = str(exc_info.value)
        assert "Cannot deploy GPU worker" in error_message

    def test_validate_with_context_preserves_helpful_message(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that contextual error still includes helpful setup instructions."""
        monkeypatch.delenv("RUNPOD_API_KEY", raising=False)

        with pytest.raises(RunpodAPIKeyError) as exc_info:
            validate_api_key_with_context("test operation")

        error_message = str(exc_info.value)
        # Should include original helpful message
        assert "RUNPOD_API_KEY" in error_message


class TestAPIClientValidation:
    """Test that API clients properly validate API key."""

    def test_graphql_client_raises_on_missing_key(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that RunpodGraphQLClient raises RunpodAPIKeyError."""
        from runpod_flash.core.api.runpod import RunpodGraphQLClient

        monkeypatch.delenv("RUNPOD_API_KEY", raising=False)

        with pytest.raises(RunpodAPIKeyError) as exc_info:
            RunpodGraphQLClient()

        assert "https://docs.runpod.io/get-started/api-keys" in str(exc_info.value)

    def test_rest_client_raises_on_missing_key(self, monkeypatch: pytest.MonkeyPatch):
        """Test that RunpodRestClient raises RunpodAPIKeyError."""
        from runpod_flash.core.api.runpod import RunpodRestClient

        monkeypatch.delenv("RUNPOD_API_KEY", raising=False)

        with pytest.raises(RunpodAPIKeyError) as exc_info:
            RunpodRestClient()

        assert "https://docs.runpod.io/get-started/api-keys" in str(exc_info.value)

    def test_graphql_client_accepts_explicit_key(self):
        """Test that RunpodGraphQLClient accepts API key parameter."""
        from runpod_flash.core.api.runpod import RunpodGraphQLClient

        client = RunpodGraphQLClient(api_key="explicit_test_key")

        assert client.api_key == "explicit_test_key"

    def test_rest_client_accepts_explicit_key(self):
        """Test that RunpodRestClient accepts API key parameter."""
        from runpod_flash.core.api.runpod import RunpodRestClient

        client = RunpodRestClient(api_key="explicit_test_key")

        assert client.api_key == "explicit_test_key"
