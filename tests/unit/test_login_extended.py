"""Extended tests for flash login command and auth GraphQL methods.

Covers gaps in test_login.py:
- open_browser=True path (typer.launch)
- CONSUMED status with and without apiKey
- expiresAt deadline capping
- Timeout branch
- login_command CLI wrapper
- create_flash_auth_request and get_flash_auth_request_status direct tests
- GraphQL session without API key (Authorization header omission)
"""

import datetime as dt
import os
from unittest.mock import AsyncMock, patch

import pytest
import typer

from runpod_flash.cli.commands.login import (
    _login,
    login_command,
)


def _make_mock_client(**status_return):
    """Build an AsyncMock that works as an async context manager."""
    client = AsyncMock()
    client.create_flash_auth_request.return_value = {
        "id": "req-123",
        "expiresAt": None,
    }
    client.get_flash_auth_request_status.return_value = status_return
    client.__aenter__.return_value = client
    return client


# ── _login flow gaps ─────────────────────────────────────────────────────


class TestLoginOpenBrowser:
    """Test the open_browser=True path."""

    @pytest.mark.asyncio
    async def test_open_browser_calls_typer_launch(self, tmp_path):
        """When open_browser=True, typer.launch is called with the auth URL."""
        creds = tmp_path / "credentials.toml"
        mock_client = _make_mock_client(status="APPROVED", apiKey="key-123")

        with (
            patch(
                "runpod_flash.cli.commands.login.RunpodGraphQLClient",
                return_value=mock_client,
            ),
            patch("runpod_flash.cli.commands.login.typer.launch") as mock_launch,
            patch.dict(
                os.environ,
                {"RUNPOD_CREDENTIALS_FILE": str(creds)},
                clear=True,
            ),
            patch("runpod_flash.cli.commands.login.console"),
        ):
            await _login(open_browser=True, timeout_seconds=5)

        mock_launch.assert_called_once()
        url = mock_launch.call_args[0][0]
        assert "req-123" in url


class TestLoginConsumedStatus:
    """Test CONSUMED status handling."""

    @pytest.mark.asyncio
    async def test_consumed_with_api_key_saves_key(self, tmp_path):
        """CONSUMED with a valid apiKey saves credentials and succeeds."""
        creds = tmp_path / "credentials.toml"
        mock_client = _make_mock_client(status="CONSUMED", apiKey="consumed-key")

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
            patch("runpod_flash.cli.commands.login.console"),
        ):
            await _login(open_browser=False, timeout_seconds=5)

        assert creds.exists()
        assert "consumed-key" in creds.read_text()

    @pytest.mark.asyncio
    async def test_consumed_without_api_key_raises(self):
        """CONSUMED without an apiKey raises RuntimeError."""
        mock_client = _make_mock_client(status="CONSUMED", apiKey=None)

        with (
            patch(
                "runpod_flash.cli.commands.login.RunpodGraphQLClient",
                return_value=mock_client,
            ),
            patch("runpod_flash.cli.commands.login.console"),
        ):
            with pytest.raises(RuntimeError, match="login failed: consumed"):
                await _login(open_browser=False, timeout_seconds=5)


class TestLoginExpiresAtDeadline:
    """Test expiresAt deadline capping."""

    @pytest.mark.asyncio
    async def test_expires_at_caps_deadline(self, tmp_path):
        """When expiresAt is earlier than timeout, deadline uses expiresAt."""
        # Set expiresAt to 1 second in the past so we immediately timeout
        past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)).isoformat()
        mock_client = AsyncMock()
        mock_client.create_flash_auth_request.return_value = {
            "id": "req-456",
            "expiresAt": past,
        }
        # Status returns PENDING so we enter the polling loop
        mock_client.get_flash_auth_request_status.return_value = {
            "status": "PENDING",
            "apiKey": None,
        }
        mock_client.__aenter__.return_value = mock_client

        with (
            patch(
                "runpod_flash.cli.commands.login.RunpodGraphQLClient",
                return_value=mock_client,
            ),
            patch(
                "runpod_flash.cli.commands.login.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                "runpod_flash.cli.commands.login.console",
            ),
        ):
            with pytest.raises(RuntimeError, match="login timed out"):
                await _login(open_browser=False, timeout_seconds=600)


class TestLoginTimeout:
    """Test timeout branch."""

    @pytest.mark.asyncio
    async def test_timeout_raises_runtime_error(self):
        """When deadline is reached, RuntimeError is raised."""
        # Use expiresAt set in the past to force immediate timeout
        past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)).isoformat()
        mock_client = AsyncMock()
        mock_client.create_flash_auth_request.return_value = {
            "id": "req-789",
            "expiresAt": past,
        }
        mock_client.get_flash_auth_request_status.return_value = {
            "status": "PENDING",
            "apiKey": None,
        }
        mock_client.__aenter__.return_value = mock_client

        with (
            patch(
                "runpod_flash.cli.commands.login.RunpodGraphQLClient",
                return_value=mock_client,
            ),
            patch(
                "runpod_flash.cli.commands.login.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                "runpod_flash.cli.commands.login.console",
            ),
        ):
            with pytest.raises(RuntimeError, match="login timed out"):
                await _login(open_browser=False, timeout_seconds=600)


# ── login_command CLI wrapper ────────────────────────────────────────────


class TestLoginCommand:
    """Test the login_command Typer wrapper."""

    def test_login_command_raises_exit_on_error(self):
        """login_command raises typer.Exit(1) when _login raises RuntimeError."""
        with patch(
            "runpod_flash.cli.commands.login.asyncio.run",
            side_effect=RuntimeError("auth failed"),
        ):
            with pytest.raises(typer.Exit) as exc_info:
                login_command(no_open=True, timeout=5.0)

            assert exc_info.value.exit_code == 1

    def test_login_command_succeeds(self):
        """login_command succeeds when _login completes normally."""
        with patch("runpod_flash.cli.commands.login.asyncio.run"):
            # Should not raise
            login_command(no_open=True, timeout=5.0)


# ── GraphQL auth methods ────────────────────────────────────────────────


class TestGraphQLAuthMethods:
    """Direct tests for create_flash_auth_request and get_flash_auth_request_status."""

    @pytest.mark.asyncio
    async def test_create_flash_auth_request(self):
        """create_flash_auth_request sends mutation and returns result."""
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "test-key"}, clear=True):
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

            # Verify the mutation string
            mutation = client._execute_graphql.call_args[0][0]
            assert "createFlashAuthRequest" in mutation

    @pytest.mark.asyncio
    async def test_create_flash_auth_request_empty_response(self):
        """create_flash_auth_request returns empty dict when key missing."""
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "test-key"}, clear=True):
            from runpod_flash.core.api.runpod import RunpodGraphQLClient

            client = RunpodGraphQLClient()
            client._execute_graphql = AsyncMock(return_value={})

            result = await client.create_flash_auth_request()
            assert result == {}

    @pytest.mark.asyncio
    async def test_get_flash_auth_request_status(self):
        """get_flash_auth_request_status sends query with request_id."""
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "test-key"}, clear=True):
            from runpod_flash.core.api.runpod import RunpodGraphQLClient

            client = RunpodGraphQLClient()
            client._execute_graphql = AsyncMock(
                return_value={
                    "flashAuthRequestStatus": {
                        "id": "req-xyz",
                        "status": "APPROVED",
                        "apiKey": "new-key",
                        "expiresAt": None,
                    }
                }
            )

            result = await client.get_flash_auth_request_status("req-xyz")

            assert result["status"] == "APPROVED"
            assert result["apiKey"] == "new-key"

            # Verify variables passed
            call_args = client._execute_graphql.call_args
            variables = call_args[0][1]
            assert variables["flashAuthRequestId"] == "req-xyz"

    @pytest.mark.asyncio
    async def test_get_flash_auth_request_status_empty_response(self):
        """get_flash_auth_request_status returns empty dict when key missing."""
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "test-key"}, clear=True):
            from runpod_flash.core.api.runpod import RunpodGraphQLClient

            client = RunpodGraphQLClient()
            client._execute_graphql = AsyncMock(return_value={})

            result = await client.get_flash_auth_request_status("req-missing")
            assert result == {}


# ── GraphQL session without API key ──────────────────────────────────────


class TestGraphQLSessionWithoutApiKey:
    """Test that _get_session omits Authorization when api_key is None."""

    @pytest.mark.asyncio
    async def test_session_omits_auth_header_when_no_key(self):
        """Session created without Authorization header when api_key is None."""
        from runpod_flash.core.api.runpod import RunpodGraphQLClient

        client = RunpodGraphQLClient(require_api_key=False)
        assert client.api_key is None

        session = await client._get_session()
        try:
            # Default headers should NOT have Authorization
            assert "Authorization" not in session.headers
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_session_includes_auth_header_when_key_set(self):
        """Session created with Authorization header when api_key is provided."""
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "my-key"}, clear=True):
            from runpod_flash.core.api.runpod import RunpodGraphQLClient

            client = RunpodGraphQLClient()
            assert client.api_key == "my-key"

            session = await client._get_session()
            try:
                assert "Authorization" in session.headers
                assert "my-key" in session.headers["Authorization"]
            finally:
                await session.close()
