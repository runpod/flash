"""Extended credential tests covering edge cases.

Gaps from existing test_credentials.py:
- _read_credentials with OSError (permissions)
- get_api_key with non-string stored value
- RunpodAPIKeyError._default_message content
- validate_api_key and validate_api_key_with_context direct tests
- Credentials-file fallback in http.py helpers
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from runpod_flash.core.credentials import get_api_key, _read_credentials
from runpod_flash.core.exceptions import RunpodAPIKeyError
from runpod_flash.core.validation import validate_api_key, validate_api_key_with_context


# ── _read_credentials edge cases ─────────────────────────────────────────


class TestReadCredentialsEdgeCases:
    """Edge cases for _read_credentials."""

    def test_returns_empty_on_os_error(self, tmp_path):
        """Returns {} when file exists but can't be opened (OSError)."""
        creds = tmp_path / "credentials.toml"
        creds.write_text('api_key = "test"\n')

        with (
            patch.dict(os.environ, {"RUNPOD_CREDENTIALS_FILE": str(creds)}, clear=True),
            patch.object(Path, "open", side_effect=OSError("Permission denied")),
        ):
            # path.exists() returns True, but path.open() raises
            # _read_credentials should catch OSError and return {}
            result = _read_credentials()

        assert result == {}


class TestGetApiKeyEdgeCases:
    """Edge cases for get_api_key."""

    def test_non_string_stored_value(self, tmp_path):
        """Returns None when stored api_key is not a string (e.g. integer)."""
        creds = tmp_path / "credentials.toml"
        creds.write_text("api_key = 12345\n")

        with patch.dict(
            os.environ, {"RUNPOD_CREDENTIALS_FILE": str(creds)}, clear=True
        ):
            result = get_api_key()

        assert result is None

    def test_list_stored_value(self, tmp_path):
        """Returns None when stored api_key is a list."""
        creds = tmp_path / "credentials.toml"
        creds.write_text('api_key = ["not", "a", "key"]\n')

        with patch.dict(
            os.environ, {"RUNPOD_CREDENTIALS_FILE": str(creds)}, clear=True
        ):
            result = get_api_key()

        assert result is None


# ── RunpodAPIKeyError message ────────────────────────────────────────────


class TestRunpodAPIKeyErrorMessage:
    """Test error message content includes new features."""

    def test_default_message_includes_flash_login(self):
        """Error message mentions 'flash login' as a setup method."""
        err = RunpodAPIKeyError()
        assert "flash login" in str(err)

    def test_default_message_includes_credentials_path(self):
        """Error message includes the credentials file path."""
        err = RunpodAPIKeyError()
        message = str(err)
        # Should include some reference to credentials.toml
        assert "credentials" in message.lower()

    def test_default_message_includes_env_var_instructions(self):
        """Error message includes RUNPOD_API_KEY instructions."""
        err = RunpodAPIKeyError()
        assert "RUNPOD_API_KEY" in str(err)
        assert "export" in str(err)

    def test_custom_message_overrides_default(self):
        """Custom message replaces default."""
        err = RunpodAPIKeyError("custom error message")
        assert str(err) == "custom error message"
        assert "flash login" not in str(err)


# ── validate_api_key direct tests ────────────────────────────────────────


class TestValidateApiKey:
    """Direct tests for validate_api_key."""

    def test_returns_key_when_set(self, tmp_path):
        """Returns the API key when available."""
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "valid-key"}, clear=True):
            result = validate_api_key()
            assert result == "valid-key"

    def test_raises_when_no_key(self, tmp_path):
        """Raises RunpodAPIKeyError when no key is available."""
        creds = tmp_path / "nonexistent.toml"
        with patch.dict(
            os.environ, {"RUNPOD_CREDENTIALS_FILE": str(creds)}, clear=True
        ):
            with pytest.raises(RunpodAPIKeyError):
                validate_api_key()

    def test_reads_from_credentials_file(self, tmp_path):
        """Returns key from credentials file when env var is unset."""
        creds = tmp_path / "credentials.toml"
        creds.write_text('api_key = "file-key"\n')

        with patch.dict(
            os.environ, {"RUNPOD_CREDENTIALS_FILE": str(creds)}, clear=True
        ):
            result = validate_api_key()
            assert result == "file-key"


class TestValidateApiKeyWithContext:
    """Direct tests for validate_api_key_with_context."""

    def test_returns_key_when_set(self):
        """Returns the API key when available."""
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "valid-key"}, clear=True):
            result = validate_api_key_with_context("deploy endpoints")
            assert result == "valid-key"

    def test_raises_with_operation_context(self, tmp_path):
        """Raises RunpodAPIKeyError with operation context in message."""
        creds = tmp_path / "nonexistent.toml"
        with patch.dict(
            os.environ, {"RUNPOD_CREDENTIALS_FILE": str(creds)}, clear=True
        ):
            with pytest.raises(RunpodAPIKeyError, match="Cannot deploy endpoints"):
                validate_api_key_with_context("deploy endpoints")

    def test_error_chains_from_original(self, tmp_path):
        """Error is chained from the original RunpodAPIKeyError."""
        creds = tmp_path / "nonexistent.toml"
        with patch.dict(
            os.environ, {"RUNPOD_CREDENTIALS_FILE": str(creds)}, clear=True
        ):
            with pytest.raises(RunpodAPIKeyError) as exc_info:
                validate_api_key_with_context("test operation")

            assert exc_info.value.__cause__ is not None
            assert isinstance(exc_info.value.__cause__, RunpodAPIKeyError)


# ── http.py credentials-file fallback ────────────────────────────────────


class TestHttpCredentialsFallback:
    """Test that http.py helpers use credentials file when env var is unset."""

    @pytest.mark.asyncio
    async def test_httpx_client_uses_credentials_file_key(self, tmp_path):
        """get_authenticated_httpx_client uses credentials file for auth."""
        creds = tmp_path / "credentials.toml"
        creds.write_text('api_key = "cred-file-key"\n')

        with patch.dict(
            os.environ, {"RUNPOD_CREDENTIALS_FILE": str(creds)}, clear=True
        ):
            from runpod_flash.core.utils.http import get_authenticated_httpx_client

            async with get_authenticated_httpx_client() as client:
                assert "Authorization" in client.headers
                assert "cred-file-key" in client.headers["Authorization"]

    @pytest.mark.asyncio
    async def test_httpx_client_no_auth_without_key(self, tmp_path):
        """get_authenticated_httpx_client omits auth when no key available."""
        creds = tmp_path / "nonexistent.toml"

        with patch.dict(
            os.environ, {"RUNPOD_CREDENTIALS_FILE": str(creds)}, clear=True
        ):
            from runpod_flash.core.utils.http import get_authenticated_httpx_client

            async with get_authenticated_httpx_client() as client:
                assert "Authorization" not in client.headers

    def test_requests_session_uses_credentials_file_key(self, tmp_path):
        """get_authenticated_requests_session uses credentials file for auth."""
        creds = tmp_path / "credentials.toml"
        creds.write_text('api_key = "cred-file-key"\n')

        with patch.dict(
            os.environ, {"RUNPOD_CREDENTIALS_FILE": str(creds)}, clear=True
        ):
            from runpod_flash.core.utils.http import get_authenticated_requests_session

            session = get_authenticated_requests_session()
            try:
                assert "Authorization" in session.headers
                assert "cred-file-key" in session.headers["Authorization"]
            finally:
                session.close()

    def test_requests_session_no_auth_without_key(self, tmp_path):
        """get_authenticated_requests_session omits auth when no key available."""
        creds = tmp_path / "nonexistent.toml"

        with patch.dict(
            os.environ, {"RUNPOD_CREDENTIALS_FILE": str(creds)}, clear=True
        ):
            from runpod_flash.core.utils.http import get_authenticated_requests_session

            session = get_authenticated_requests_session()
            try:
                assert "Authorization" not in session.headers
            finally:
                session.close()
