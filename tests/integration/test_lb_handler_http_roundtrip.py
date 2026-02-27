"""Integration tests for the LB handler FastAPI application.

Exercises /execute endpoint and custom routes with real serialized payloads
using FastAPI TestClient (no real server needed).
"""

import pytest
from fastapi.testclient import TestClient

from runpod_flash.runtime.api_key_context import get_api_key
from runpod_flash.runtime.lb_handler import create_lb_handler
from runpod_flash.runtime.serialization import (
    deserialize_arg,
    serialize_args,
    serialize_kwargs,
)


class TestExecuteEndpoint:
    """POST /execute with serialized function code and arguments."""

    def _make_app(self, routes=None):
        return create_lb_handler(
            route_registry=routes or {},
            include_execute=True,
        )

    def test_execute_endpoint_serialize_deserialize(self):
        """Full round-trip: serialize args → POST /execute → deserialize result."""
        app = self._make_app()
        client = TestClient(app)

        function_code = "def add(a, b):\n    return a + b"
        response = client.post(
            "/execute",
            json={
                "function_name": "add",
                "function_code": function_code,
                "args": serialize_args((3, 7)),
                "kwargs": serialize_kwargs({}),
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert deserialize_arg(body["result"]) == 10

    def test_execute_async_function(self):
        """Async function through /execute endpoint."""
        app = self._make_app()
        client = TestClient(app)

        function_code = (
            "import asyncio\nasync def async_multiply(x, y):\n    return x * y\n"
        )
        response = client.post(
            "/execute",
            json={
                "function_name": "async_multiply",
                "function_code": function_code,
                "args": serialize_args((6, 7)),
                "kwargs": {},
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert deserialize_arg(body["result"]) == 42

    def test_execute_with_kwargs(self):
        """Function with keyword arguments through /execute."""
        app = self._make_app()
        client = TestClient(app)

        function_code = (
            "def greet(name, greeting='Hello'):\n    return f'{greeting}, {name}!'"
        )
        response = client.post(
            "/execute",
            json={
                "function_name": "greet",
                "function_code": function_code,
                "args": [],
                "kwargs": serialize_kwargs({"name": "World", "greeting": "Hi"}),
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert deserialize_arg(body["result"]) == "Hi, World!"

    def test_execute_missing_function_name(self):
        """Missing function_name returns error."""
        app = self._make_app()
        client = TestClient(app)

        response = client.post(
            "/execute",
            json={"function_code": "def f(): pass"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is False
        assert "Missing" in body["error"]


class TestApiKeyMiddleware:
    """Bearer token is extracted and available in api_key_context."""

    def test_api_key_middleware_sets_context(self):
        """Authorization header is propagated to api_key_context."""
        captured_keys = []

        def capture_key():
            captured_keys.append(get_api_key())
            return {"status": "ok"}

        app = create_lb_handler(
            route_registry={("GET", "/check"): capture_key},
        )
        client = TestClient(app)

        response = client.get(
            "/check", headers={"Authorization": "Bearer test-key-123"}
        )
        assert response.status_code == 200
        assert captured_keys == ["test-key-123"]

    def test_api_key_cleared_after_request(self):
        """API key context is cleared after request completes."""

        def noop():
            return {"ok": True}

        app = create_lb_handler(route_registry={("GET", "/noop"): noop})
        client = TestClient(app)

        client.get("/noop", headers={"Authorization": "Bearer temp-key"})
        # After request, context should be cleared
        assert get_api_key() is None


class TestCustomRoutes:
    """User-defined routes with auto-generated Pydantic body models."""

    def test_custom_route_with_body_model(self):
        """POST route auto-generates Pydantic model from function signature."""

        def create_item(name: str, price: float, quantity: int = 1):
            return {"name": name, "total": price * quantity}

        app = create_lb_handler(
            route_registry={("POST", "/items"): create_item},
        )
        client = TestClient(app)

        response = client.post(
            "/items",
            json={"name": "Widget", "price": 9.99, "quantity": 3},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Widget"
        assert body["total"] == pytest.approx(29.97)

    def test_get_route_no_body(self):
        """GET route works without body model."""

        def health():
            return {"status": "healthy"}

        app = create_lb_handler(route_registry={("GET", "/health"): health})
        client = TestClient(app)

        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}
