"""Tests for HTTP utilities for RunPod API communication."""

import requests
from runpod_flash.core.utils.http import (
    get_authenticated_httpx_client,
    get_authenticated_requests_session,
)


class TestGetAuthenticatedHttpxClient:
    """Test the get_authenticated_httpx_client utility function."""

    def test_get_authenticated_httpx_client_with_api_key(self, monkeypatch):
        """Test client includes auth header when API key is set."""
        monkeypatch.setenv("RUNPOD_API_KEY", "test-api-key-123")

        client = get_authenticated_httpx_client()

        assert client is not None
        assert "Authorization" in client.headers
        assert client.headers["Authorization"] == "Bearer test-api-key-123"

    def test_get_authenticated_httpx_client_without_api_key(self, monkeypatch):
        """Test client works without API key (no auth header)."""
        monkeypatch.delenv("RUNPOD_API_KEY", raising=False)

        client = get_authenticated_httpx_client()

        assert client is not None
        assert "Authorization" not in client.headers

    def test_get_authenticated_httpx_client_custom_timeout(self, monkeypatch):
        """Test client respects custom timeout."""
        monkeypatch.setenv("RUNPOD_API_KEY", "test-key")

        client = get_authenticated_httpx_client(timeout=60.0)

        assert client is not None
        assert client.timeout.read == 60.0

    def test_get_authenticated_httpx_client_default_timeout(self, monkeypatch):
        """Test client uses default timeout when not specified."""
        monkeypatch.setenv("RUNPOD_API_KEY", "test-key")

        client = get_authenticated_httpx_client()

        assert client is not None
        assert client.timeout.read == 30.0

    def test_get_authenticated_httpx_client_timeout_none_uses_default(
        self, monkeypatch
    ):
        """Test client uses default timeout when explicitly passed None."""
        monkeypatch.setenv("RUNPOD_API_KEY", "test-key")

        client = get_authenticated_httpx_client(timeout=None)

        assert client is not None
        assert client.timeout.read == 30.0

    def test_get_authenticated_httpx_client_empty_api_key_no_header(self, monkeypatch):
        """Test that empty API key doesn't add Authorization header."""
        monkeypatch.setenv("RUNPOD_API_KEY", "")

        client = get_authenticated_httpx_client()

        assert client is not None
        # Empty string is falsy, so no auth header should be added
        assert "Authorization" not in client.headers

    def test_get_authenticated_httpx_client_zero_timeout(self, monkeypatch):
        """Test client handles zero timeout correctly."""
        monkeypatch.setenv("RUNPOD_API_KEY", "test-key")

        client = get_authenticated_httpx_client(timeout=0.0)

        assert client is not None
        assert client.timeout.read == 0.0

    def test_get_authenticated_httpx_client_includes_user_agent(self, monkeypatch):
        """Test client includes User-Agent header."""
        monkeypatch.delenv("RUNPOD_API_KEY", raising=False)

        client = get_authenticated_httpx_client()

        assert client is not None
        assert "User-Agent" in client.headers
        assert client.headers["User-Agent"].startswith("Runpod Flash/")

    def test_get_authenticated_httpx_client_user_agent_with_auth(self, monkeypatch):
        """Test client includes both User-Agent and Authorization headers."""
        monkeypatch.setenv("RUNPOD_API_KEY", "test-key")

        client = get_authenticated_httpx_client()

        assert client is not None
        assert "User-Agent" in client.headers
        assert "Authorization" in client.headers
        assert client.headers["User-Agent"].startswith("Runpod Flash/")
        assert client.headers["Authorization"] == "Bearer test-key"


class TestGetAuthenticatedRequestsSession:
    """Test the get_authenticated_requests_session utility function."""

    def test_get_authenticated_requests_session_with_api_key(self, monkeypatch):
        """Test session includes auth header when API key is set."""
        monkeypatch.setenv("RUNPOD_API_KEY", "test-api-key-123")

        session = get_authenticated_requests_session()

        assert session is not None
        assert "Authorization" in session.headers
        assert session.headers["Authorization"] == "Bearer test-api-key-123"
        session.close()

    def test_get_authenticated_requests_session_without_api_key(self, monkeypatch):
        """Test session works without API key (no auth header)."""
        monkeypatch.delenv("RUNPOD_API_KEY", raising=False)

        session = get_authenticated_requests_session()

        assert session is not None
        assert "Authorization" not in session.headers
        session.close()

    def test_get_authenticated_requests_session_empty_api_key_no_header(
        self, monkeypatch
    ):
        """Test that empty API key doesn't add Authorization header."""
        monkeypatch.setenv("RUNPOD_API_KEY", "")

        session = get_authenticated_requests_session()

        assert session is not None
        # Empty string is falsy, so no auth header should be added
        assert "Authorization" not in session.headers
        session.close()

    def test_get_authenticated_requests_session_is_valid_session(self, monkeypatch):
        """Test returned object is a valid requests.Session."""
        monkeypatch.setenv("RUNPOD_API_KEY", "test-key")

        session = get_authenticated_requests_session()

        assert isinstance(session, requests.Session)
        session.close()

    def test_get_authenticated_requests_session_includes_user_agent(self, monkeypatch):
        """Test session includes User-Agent header."""
        monkeypatch.delenv("RUNPOD_API_KEY", raising=False)

        session = get_authenticated_requests_session()

        assert session is not None
        assert "User-Agent" in session.headers
        assert session.headers["User-Agent"].startswith("Runpod Flash/")
        session.close()

    def test_get_authenticated_requests_session_user_agent_with_auth(self, monkeypatch):
        """Test session includes both User-Agent and Authorization headers."""
        monkeypatch.setenv("RUNPOD_API_KEY", "test-key")

        session = get_authenticated_requests_session()

        assert session is not None
        assert "User-Agent" in session.headers
        assert "Authorization" in session.headers
        assert session.headers["User-Agent"].startswith("Runpod Flash/")
        assert session.headers["Authorization"] == "Bearer test-key"
        session.close()
