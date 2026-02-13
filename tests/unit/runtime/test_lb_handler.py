"""Unit tests for LoadBalancer handler factory."""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from runpod_flash.runtime.lb_handler import (
    create_lb_handler,
    extract_api_key_middleware,
)
from runpod_flash.runtime.api_key_context import get_api_key


class TestExecuteEndpointStillWorks:
    """Tests to ensure /execute endpoint still works after manifest changes."""

    def test_execute_endpoint_still_available_with_live_load_balancer(self):
        """Verify /execute endpoint is still registered for LiveLoadBalancer."""
        app = create_lb_handler({}, include_execute=True)
        routes = [route.path for route in app.routes]

        assert "/execute" in routes

    def test_execute_endpoint_not_included_for_deployed(self):
        """Verify /execute endpoint is not registered for deployed LoadBalancer."""
        app = create_lb_handler({}, include_execute=False)
        routes = [route.path for route in app.routes]

        assert "/execute" not in routes


class TestAPIKeyMiddleware:
    """Tests for API key extraction middleware."""

    @pytest.mark.asyncio
    async def test_extract_api_key_from_authorization_header(self):
        """Verify API key is extracted from Bearer token."""
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            api_key = get_api_key()
            return {"api_key": api_key}

        app.middleware("http")(extract_api_key_middleware)

        client = TestClient(app)
        response = client.get("/test", headers={"Authorization": "Bearer test-key-123"})

        assert response.status_code == 200
        assert response.json()["api_key"] == "test-key-123"

    @pytest.mark.asyncio
    async def test_api_key_stored_in_request_state(self):
        """Verify API key is stored in request.state for explicit access."""
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint(request: Request):
            api_key = getattr(request.state, "api_key", None)
            return {"api_key": api_key}

        app.middleware("http")(extract_api_key_middleware)

        client = TestClient(app)
        response = client.get("/test", headers={"Authorization": "Bearer request-key"})

        assert response.status_code == 200
        assert response.json()["api_key"] == "request-key"

    @pytest.mark.asyncio
    async def test_no_api_key_when_header_missing(self):
        """Verify api_key is None when Authorization header is missing."""
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            api_key = get_api_key()
            return {"api_key": api_key}

        app.middleware("http")(extract_api_key_middleware)

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        assert response.json()["api_key"] is None

    @pytest.mark.asyncio
    async def test_no_api_key_when_header_not_bearer(self):
        """Verify api_key is None when Authorization header doesn't have Bearer token."""
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            api_key = get_api_key()
            return {"api_key": api_key}

        app.middleware("http")(extract_api_key_middleware)

        client = TestClient(app)
        response = client.get("/test", headers={"Authorization": "Basic credentials"})

        assert response.status_code == 200
        assert response.json()["api_key"] is None

    @pytest.mark.asyncio
    async def test_api_key_cleared_after_request(self):
        """Verify API key context is cleared after request completes."""
        app = FastAPI()

        api_key_after_request = None

        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        app.middleware("http")(extract_api_key_middleware)

        client = TestClient(app)
        response = client.get("/test", headers={"Authorization": "Bearer temp-key"})

        # After request completes, context should be cleared
        api_key_after_request = get_api_key()

        assert response.status_code == 200
        assert api_key_after_request is None
