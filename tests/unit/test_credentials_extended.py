"""Extended credential tests covering edge cases.

Gaps from existing test_credentials.py:
- get_api_key with non-string stored value
- RunpodAPIKeyError._default_message content
- validate_api_key and validate_api_key_with_context direct tests
- Credentials-file fallback in http.py helpers
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from runpod_flash.core.credentials import get_api_key
from runpod_flash.core.exceptions import RunpodAPIKeyError
from runpod_flash.core.validation import validate_api_key, validate_api_key_with_context


def _write_config_toml(path: Path, api_key: str, profile: str = "default") -> None:
    """Write a runpod-python format config.toml."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'[{profile}]\napi_key = "{api_key}"\n')


# ── get_api_key edge cases ───────────────────────────────────────────────


class TestGetApiKeyEdgeCases:
    """Edge cases for get_api_key."""

    def test_non_string_stored_value(self, isolate_credentials_file):
        """Returns None when stored api_key is not a string (e.g. integer)."""
        isolate_credentials_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_credentials_file.write_text("[default]\napi_key = 12345\n")
        result = get_api_key()
        assert result is None

    def test_list_stored_value(self, isolate_credentials_file):
        """Returns None when stored api_key is a list."""
        isolate_credentials_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_credentials_file.write_text(
            '[default]\napi_key = ["not", "a", "key"]\n'
        )
        result = get_api_key()
        assert result is None


# ── RunpodAPIKeyError message ────────────────────────────────────────────


class TestRunpodAPIKeyErrorMessage:
    """Test error message content includes new features."""

    def test_default_message_includes_flash_login(self):
        """Error message mentions 'flash login' as a setup method."""
        err = RunpodAPIKeyError()
        assert "flash login" in str(err)

    def test_default_message_includes_docs_url(self):
        """Error message includes the API key docs URL."""
        err = RunpodAPIKeyError()
        message = str(err)
        assert "https://docs.runpod.io/get-started/api-keys" in message

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

    def test_returns_key_when_set(self):
        """Returns the API key when available."""
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "valid-key"}):
            result = validate_api_key()
            assert result == "valid-key"

    def test_raises_when_no_key(self):
        """Raises RunpodAPIKeyError when no key is available."""
        with pytest.raises(RunpodAPIKeyError):
            validate_api_key()

    def test_reads_from_credentials_file(self, isolate_credentials_file):
        """Returns key from credentials file when env var is unset."""
        _write_config_toml(isolate_credentials_file, "file-key")
        result = validate_api_key()
        assert result == "file-key"


class TestValidateApiKeyWithContext:
    """Direct tests for validate_api_key_with_context."""

    def test_returns_key_when_set(self):
        """Returns the API key when available."""
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "valid-key"}):
            result = validate_api_key_with_context("deploy endpoints")
            assert result == "valid-key"

    def test_raises_with_operation_context(self):
        """Raises RunpodAPIKeyError with operation context in message."""
        with pytest.raises(RunpodAPIKeyError, match="Cannot deploy endpoints"):
            validate_api_key_with_context("deploy endpoints")

    def test_error_chains_from_original(self):
        """Error is chained from the original RunpodAPIKeyError."""
        with pytest.raises(RunpodAPIKeyError) as exc_info:
            validate_api_key_with_context("test operation")

        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, RunpodAPIKeyError)


# ── http.py credentials-file fallback ────────────────────────────────────


class TestHttpCredentialsFallback:
    """Test that http.py helpers use credentials file when env var is unset."""

    @pytest.mark.asyncio
    async def test_httpx_client_uses_credentials_file_key(
        self, isolate_credentials_file
    ):
        """get_authenticated_httpx_client uses credentials file for auth."""
        _write_config_toml(isolate_credentials_file, "cred-file-key")

        from runpod_flash.core.utils.http import get_authenticated_httpx_client

        async with get_authenticated_httpx_client() as client:
            assert "Authorization" in client.headers
            assert "cred-file-key" in client.headers["Authorization"]

    @pytest.mark.asyncio
    async def test_httpx_client_no_auth_without_key(self):
        """get_authenticated_httpx_client omits auth when no key available."""
        from runpod_flash.core.utils.http import get_authenticated_httpx_client

        async with get_authenticated_httpx_client() as client:
            assert "Authorization" not in client.headers

    def test_requests_session_uses_credentials_file_key(self, isolate_credentials_file):
        """get_authenticated_requests_session uses credentials file for auth."""
        _write_config_toml(isolate_credentials_file, "cred-file-key")

        from runpod_flash.core.utils.http import get_authenticated_requests_session

        session = get_authenticated_requests_session()
        try:
            assert "Authorization" in session.headers
            assert "cred-file-key" in session.headers["Authorization"]
        finally:
            session.close()

    def test_requests_session_no_auth_without_key(self):
        """get_authenticated_requests_session omits auth when no key available."""
        from runpod_flash.core.utils.http import get_authenticated_requests_session

        session = get_authenticated_requests_session()
        try:
            assert "Authorization" not in session.headers
        finally:
            session.close()

    @pytest.mark.asyncio
    async def test_httpx_explicit_none_override_skips_env_key(self):
        """Passing api_key_override=None explicitly must NOT fall back to env var."""
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "env-key"}):
            from runpod_flash.core.utils.http import get_authenticated_httpx_client

            async with get_authenticated_httpx_client(api_key_override=None) as client:
                assert "Authorization" not in client.headers

    def test_requests_explicit_none_override_skips_env_key(self):
        """Passing api_key_override=None explicitly must NOT fall back to env var."""
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "env-key"}):
            from runpod_flash.core.utils.http import get_authenticated_requests_session

            session = get_authenticated_requests_session(api_key_override=None)
            try:
                assert "Authorization" not in session.headers
            finally:
                session.close()

    @pytest.mark.asyncio
    async def test_aiohttp_explicit_none_override_skips_env_key(self):
        """Passing api_key_override=None explicitly must NOT fall back to env var."""
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "env-key"}):
            from runpod_flash.core.utils.http import get_authenticated_aiohttp_session

            session = get_authenticated_aiohttp_session(api_key_override=None)
            try:
                assert "Authorization" not in session.headers
            finally:
                await session.close()
