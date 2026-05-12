"""Unit tests for the flash login command."""

import os
from unittest.mock import AsyncMock, patch

import pytest

from runpod_flash.cli.commands.login import _login


class TestGraphQLClientNoKeyForLogin:
    """Login mutations must not send stored credentials."""

    def test_require_api_key_false_does_not_load_stored_key(
        self, isolate_credentials_file
    ):
        isolate_credentials_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_credentials_file.write_text(
            '[default]\napi_key = "stale-expired-key"\n'
        )

        from runpod_flash.core.api.runpod import RunpodGraphQLClient

        client = RunpodGraphQLClient(require_api_key=False)
        assert client.api_key is None

    def test_require_api_key_false_does_not_load_env_var(self):
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "env-key"}):
            from runpod_flash.core.api.runpod import RunpodGraphQLClient

            client = RunpodGraphQLClient(require_api_key=False)
            assert client.api_key is None

    def test_require_api_key_false_allows_explicit_key(self):
        from runpod_flash.core.api.runpod import RunpodGraphQLClient

        client = RunpodGraphQLClient(api_key="explicit", require_api_key=False)
        assert client.api_key == "explicit"

    def test_require_api_key_true_loads_key(self):
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "loaded-key"}):
            from runpod_flash.core.api.runpod import RunpodGraphQLClient

            client = RunpodGraphQLClient(require_api_key=True)
            assert client.api_key == "loaded-key"


def _make_mock_client():
    """Build an AsyncMock that works as an async context manager."""
    client = AsyncMock()
    client.create_flash_auth_request.return_value = {
        "id": "req-123",
        "expiresAt": None,
    }
    client.__aenter__.return_value = client
    return client


def _get_login_fn():
    """Import _login fresh to survive sys.modules clearing by other tests."""
    import importlib

    mod = importlib.import_module("runpod_flash.cli.commands.login")
    importlib.reload(mod)
    return mod._login


class TestLoginFlow:
    async def test_login_saves_pasted_key(self, isolate_credentials_file):
        mock_client = _make_mock_client()
        _login = _get_login_fn()

        with (
            patch(
                "runpod_flash.cli.commands.login.RunpodGraphQLClient",
                return_value=mock_client,
            ),
            patch(
                "runpod_flash.cli.commands.login.console"
            ) as mock_console,
        ):
            mock_console.input.return_value = "pasted-api-key"
            await _login(open_browser=False)
            assert isolate_credentials_file.exists()
            assert "pasted-api-key" in isolate_credentials_file.read_text()

    async def test_login_empty_key_raises(self):
        mock_client = _make_mock_client()
        _login = _get_login_fn()

        with (
            patch(
                "runpod_flash.cli.commands.login.RunpodGraphQLClient",
                return_value=mock_client,
            ),
            patch(
                "runpod_flash.cli.commands.login.console"
            ) as mock_console,
        ):
            mock_console.input.return_value = "  "
            with pytest.raises(RuntimeError, match="no api key provided"):
                await _login(open_browser=False)

    async def test_no_request_id_raises(self):
        mock_client = _make_mock_client()
        mock_client.create_flash_auth_request.return_value = {}
        _login = _get_login_fn()

        with patch(
            "runpod_flash.cli.commands.login.RunpodGraphQLClient",
            return_value=mock_client,
        ):
            with pytest.raises(RuntimeError, match="auth request failed"):
                await _login(open_browser=False)
