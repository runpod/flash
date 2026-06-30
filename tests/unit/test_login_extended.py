"""Extended tests for flash login command and auth GraphQL methods.

Covers:
- open_browser=True path (typer.launch)
- login_command CLI wrapper
- create_flash_auth_request direct test
- GraphQL session without API key (Authorization header omission)
"""

import os
from unittest.mock import AsyncMock, patch

import pytest
import typer

import importlib


def _fresh_login_module():
    """Get the current login module from sys.modules to survive reloads."""
    return importlib.import_module("runpod_flash.cli.commands.login")


def _make_mock_client():
    """Build an AsyncMock that works as an async context manager."""
    client = AsyncMock()
    client.create_flash_auth_request.return_value = {
        "id": "req-123",
        "expiresAt": None,
    }
    client.__aenter__.return_value = client
    return client


# -- _login flow gaps --


@pytest.mark.serial
class TestLoginOpenBrowser:
    """Test the open_browser=True path."""

    @pytest.mark.asyncio
    async def test_open_browser_calls_typer_launch(self, isolate_credentials_file):
        """When open_browser=True, typer.launch is called with the auth URL."""
        mock_client = _make_mock_client()

        with (
            patch(
                "runpod_flash.cli.commands.login.RunpodGraphQLClient",
                return_value=mock_client,
            ),
            patch("runpod_flash.cli.commands.login.typer.launch") as mock_launch,
            patch("runpod_flash.cli.commands.login.console") as mock_console,
        ):
            mock_console.input.return_value = "key-123"
            await _fresh_login_module()._login(open_browser=True)

        mock_launch.assert_called_once()
        url = mock_launch.call_args[0][0]
        assert "req-123" in url


# -- login_command CLI wrapper --


@pytest.mark.serial
class TestLoginCommand:
    """Test the login_command Typer wrapper."""

    def test_login_command_raises_exit_on_error(self):
        """login_command raises typer.Exit(1) when _login raises RuntimeError."""
        with patch(
            "runpod_flash.cli.commands.login.asyncio.run",
            side_effect=RuntimeError("auth failed"),
        ):
            with pytest.raises(typer.Exit) as exc_info:
                _fresh_login_module().login_command(no_open=True)

            assert exc_info.value.exit_code == 1

    def test_login_command_succeeds(self):
        """login_command succeeds when _login completes normally."""
        with patch("runpod_flash.cli.commands.login.asyncio.run"):
            _fresh_login_module().login_command(no_open=True)


# -- GraphQL auth methods --


@pytest.mark.serial
class TestGraphQLAuthMethods:
    """Direct tests for create_flash_auth_request."""

    @pytest.mark.asyncio
    async def test_create_flash_auth_request(self):
        """create_flash_auth_request sends mutation and returns result."""
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "test-key"}):
            from runpod_flash.core.api.runpod import RunpodGraphQLClient

            client = RunpodGraphQLClient()
            client._execute_graphql = AsyncMock(
                return_value={
                    "createFlashAuthRequest": {
                        "id": "req-abc",
                        "status": "PENDING",
                        "expiresAt": "2026-03-01T00:00:00Z",
                    }
                }
            )

            result = await client.create_flash_auth_request()

            assert result["id"] == "req-abc"
            assert result["status"] == "PENDING"
            client._execute_graphql.assert_called_once()

            mutation = client._execute_graphql.call_args[0][0]
            assert "createFlashAuthRequest" in mutation

    @pytest.mark.asyncio
    async def test_create_flash_auth_request_empty_response(self):
        """create_flash_auth_request returns empty dict when key missing."""
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "test-key"}):
            from runpod_flash.core.api.runpod import RunpodGraphQLClient

            client = RunpodGraphQLClient()
            client._execute_graphql = AsyncMock(return_value={})

            result = await client.create_flash_auth_request()
            assert result == {}


# -- GraphQL session without API key --


@pytest.mark.serial
class TestGraphQLSessionWithoutApiKey:
    """Test that _get_session omits Authorization when api_key is None."""

    @pytest.mark.asyncio
    async def test_fresh_user_no_key_anywhere(self):
        from runpod_flash.core.api.runpod import RunpodGraphQLClient

        client = RunpodGraphQLClient(require_api_key=False)
        assert client.api_key is None

        session = await client._get_session()
        try:
            assert "Authorization" not in session.headers
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_session_includes_auth_header_when_key_set(self):
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "my-key"}):
            from runpod_flash.core.api.runpod import RunpodGraphQLClient

            client = RunpodGraphQLClient()
            assert client.api_key == "my-key"

            session = await client._get_session()
            try:
                assert "Authorization" in session.headers
                assert "my-key" in session.headers["Authorization"]
            finally:
                await session.close()

    @pytest.mark.asyncio
    async def test_no_auth_header_when_require_api_key_false_despite_env_var(self):
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "existing-key"}):
            from runpod_flash.core.api.runpod import RunpodGraphQLClient

            client = RunpodGraphQLClient(require_api_key=False)
            assert client.api_key is None

            session = await client._get_session()
            try:
                assert "Authorization" not in session.headers
            finally:
                await session.close()

    @pytest.mark.asyncio
    async def test_no_auth_header_when_credentials_file_has_key(
        self, isolate_credentials_file
    ):
        isolate_credentials_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_credentials_file.write_text(
            '[default]\napi_key = "previously-saved-key"\n'
        )

        from runpod_flash.core.api.runpod import RunpodGraphQLClient

        client = RunpodGraphQLClient(require_api_key=False)
        assert client.api_key is None

        session = await client._get_session()
        try:
            assert "Authorization" not in session.headers
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_no_auth_header_when_both_env_var_and_credentials_file(
        self, isolate_credentials_file
    ):
        isolate_credentials_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_credentials_file.write_text('[default]\napi_key = "file-key"\n')

        with patch.dict(os.environ, {"RUNPOD_API_KEY": "env-key"}):
            from runpod_flash.core.api.runpod import RunpodGraphQLClient

            client = RunpodGraphQLClient(require_api_key=False)
            assert client.api_key is None

            session = await client._get_session()
            try:
                assert "Authorization" not in session.headers
            finally:
                await session.close()
