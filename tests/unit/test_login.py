"""Unit tests for the flash login command."""

import os
from unittest.mock import AsyncMock, patch

import pytest

from runpod_flash.cli.commands.login import _parse_expires_at


class TestParseExpiresAt:
    def test_iso_format(self):
        result = _parse_expires_at("2026-03-01T12:00:00Z")
        assert result is not None
        assert result.year == 2026

    def test_none_input(self):
        assert _parse_expires_at(None) is None

    def test_empty_string(self):
        assert _parse_expires_at("") is None

    def test_invalid_string(self):
        assert _parse_expires_at("not-a-date") is None


class TestGraphQLClientNoKeyForLogin:
    """Login mutations must not send stored credentials."""

    def test_require_api_key_false_does_not_load_stored_key(self, tmp_path):
        creds = tmp_path / "credentials.toml"
        creds.write_text('api_key = "stale-expired-key"\n')

        with patch.dict(
            os.environ,
            {"RUNPOD_CREDENTIALS_FILE": str(creds)},
            clear=True,
        ):
            from runpod_flash.core.api.runpod import RunpodGraphQLClient

            client = RunpodGraphQLClient(require_api_key=False)
            assert client.api_key is None

    def test_require_api_key_false_does_not_load_env_var(self):
        with patch.dict(
            os.environ,
            {"RUNPOD_API_KEY": "env-key"},
            clear=True,
        ):
            from runpod_flash.core.api.runpod import RunpodGraphQLClient

            client = RunpodGraphQLClient(require_api_key=False)
            assert client.api_key is None

    def test_require_api_key_false_allows_explicit_key(self):
        from runpod_flash.core.api.runpod import RunpodGraphQLClient

        client = RunpodGraphQLClient(api_key="explicit", require_api_key=False)
        assert client.api_key == "explicit"

    def test_require_api_key_true_loads_key(self):
        with patch.dict(
            os.environ,
            {"RUNPOD_API_KEY": "loaded-key"},
            clear=True,
        ):
            from runpod_flash.core.api.runpod import RunpodGraphQLClient

            client = RunpodGraphQLClient(require_api_key=True)
            assert client.api_key == "loaded-key"


def _make_mock_client(**status_return):
    """Build an AsyncMock that works as an async context manager."""
    client = AsyncMock()
    client.create_flash_auth_request.return_value = {
        "id": "req-123",
        "expiresAt": None,
    }
    client.get_flash_auth_request_status.return_value = status_return
    # _login uses `async with RunpodGraphQLClient(...) as client:`,
    # so __aenter__ must return the same mock instance
    client.__aenter__.return_value = client
    return client


def _get_login_fn():
    """Import _login fresh to survive sys.modules clearing by other tests."""
    import importlib

    mod = importlib.import_module("runpod_flash.cli.commands.login")
    importlib.reload(mod)
    return mod._login


class TestLoginFlow:
    async def test_login_denied(self):
        mock_client = _make_mock_client(status="DENIED", apiKey=None)
        _login = _get_login_fn()

        with patch(
            "runpod_flash.cli.commands.login.RunpodGraphQLClient",
            return_value=mock_client,
        ):
            with pytest.raises(RuntimeError, match="login failed: denied"):
                await _login(open_browser=False, timeout_seconds=5)

    async def test_login_approved_saves_key(self, tmp_path):
        creds = tmp_path / "credentials.toml"
        mock_client = _make_mock_client(status="APPROVED", apiKey="fresh-api-key")
        _login = _get_login_fn()

        with (
            patch(
                "runpod_flash.cli.commands.login.RunpodGraphQLClient",
                return_value=mock_client,
            ),
            patch.dict(
                os.environ,
                {"RUNPOD_CREDENTIALS_FILE": str(creds)},
                clear=True,
            ),
        ):
            await _login(open_browser=False, timeout_seconds=5)
            assert creds.exists()
            assert "fresh-api-key" in creds.read_text()

    async def test_login_expired(self):
        mock_client = _make_mock_client(status="EXPIRED", apiKey=None)
        _login = _get_login_fn()

        with patch(
            "runpod_flash.cli.commands.login.RunpodGraphQLClient",
            return_value=mock_client,
        ):
            with pytest.raises(RuntimeError, match="login failed: expired"):
                await _login(open_browser=False, timeout_seconds=5)

    async def test_no_request_id_raises(self):
        mock_client = _make_mock_client(status="APPROVED", apiKey="key")
        mock_client.create_flash_auth_request.return_value = {}
        _login = _get_login_fn()

        with patch(
            "runpod_flash.cli.commands.login.RunpodGraphQLClient",
            return_value=mock_client,
        ):
            with pytest.raises(RuntimeError, match="auth request failed"):
                await _login(open_browser=False, timeout_seconds=5)
