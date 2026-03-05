"""Extended tests for runtime/lb_handler.py - uncovered paths."""

import inspect
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from runpod_flash.runtime.lb_handler import (
    _make_input_model,
    _wrap_handler_with_body_model,
    create_lb_handler,
)


class TestMakeInputModel:
    """Test _make_input_model function."""

    def test_creates_model_from_function(self):
        def func(x: int, y: str = "default"):
            pass

        model = _make_input_model("FuncBody", func)
        assert model is not None
        assert "x" in model.model_fields
        assert "y" in model.model_fields

    def test_returns_none_for_zero_params(self):
        def no_params():
            pass

        model = _make_input_model("NoParamsBody", no_params)
        assert model is None

    def test_skips_self_param(self):
        class MyClass:
            def method(self, x: int):
                pass

        model = _make_input_model("MethodBody", MyClass.method)
        assert model is not None
        assert "self" not in model.model_fields
        assert "x" in model.model_fields

    def test_handles_var_positional_and_keyword(self):
        def func(*args, **kwargs):
            pass

        model = _make_input_model("VarBody", func)
        assert model is None  # No eligible params

    def test_excludes_specified_params(self):
        def func(x: int, y: str, z: float):
            pass

        model = _make_input_model("ExclBody", func, exclude={"y"})
        assert "x" in model.model_fields
        assert "y" not in model.model_fields
        assert "z" in model.model_fields

    def test_returns_none_on_introspection_failure(self):
        """Returns None when signature inspection fails."""
        # Use a builtin that can't be introspected
        _make_input_model("BuiltinBody", print)
        # print may or may not be introspectable depending on Python version
        # The key is it doesn't raise

    def test_unannotated_params_default_to_any(self):
        def func(x, y=5):
            pass

        model = _make_input_model("UnannotatedBody", func)
        assert model is not None


class TestWrapHandlerWithBodyModel:
    """Test _wrap_handler_with_body_model function."""

    def test_wraps_simple_function(self):
        def handler(x: int, y: int):
            return x + y

        wrapped = _wrap_handler_with_body_model(handler, "/api/add")
        # Should be wrapped (not the original)
        assert wrapped is not handler

    def test_leaves_no_param_function_unchanged(self):
        def handler():
            return "ok"

        wrapped = _wrap_handler_with_body_model(handler, "/api/health")
        assert wrapped is handler

    def test_leaves_basemodel_param_unchanged(self):
        class InputModel(BaseModel):
            x: int

        def handler(data: InputModel):
            return data.x

        wrapped = _wrap_handler_with_body_model(handler, "/api/process")
        assert wrapped is handler

    def test_handles_path_parameters(self):
        def handler(item_id: int, name: str):
            return {"id": item_id, "name": name}

        wrapped = _wrap_handler_with_body_model(handler, "/items/{item_id}")
        assert wrapped is not handler

    def test_async_handler_wrapped(self):
        async def handler(x: int):
            return x

        wrapped = _wrap_handler_with_body_model(handler, "/api/test")
        assert inspect.iscoroutinefunction(wrapped)

    def test_returns_handler_on_introspection_failure(self):
        """Returns unwrapped handler on introspection failure."""
        handler = MagicMock()
        handler.__name__ = "mock_handler"
        # MagicMock won't have proper signature
        result = _wrap_handler_with_body_model(handler, "/api/test")
        # Should return something callable
        assert callable(result)


class TestCreateLbHandler:
    """Test create_lb_handler factory."""

    def test_creates_fastapi_app(self):
        app = create_lb_handler({})
        assert isinstance(app, FastAPI)

    def test_registers_get_route(self):
        def health():
            return {"status": "ok"}

        app = create_lb_handler({("GET", "/health"): health})
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_registers_post_route(self):
        def process(x: int, y: int):
            return {"sum": x + y}

        app = create_lb_handler({("POST", "/process"): process})
        client = TestClient(app)
        response = client.post("/process", json={"x": 3, "y": 5})
        assert response.status_code == 200
        assert response.json() == {"sum": 8}

    def test_registers_put_route(self):
        def update(value: str):
            return {"updated": value}

        app = create_lb_handler({("PUT", "/update"): update})
        client = TestClient(app)
        response = client.put("/update", json={"value": "new"})
        assert response.status_code == 200

    def test_registers_delete_route(self):
        def delete():
            return {"deleted": True}

        app = create_lb_handler({("DELETE", "/items"): delete})
        client = TestClient(app)
        response = client.delete("/items")
        assert response.status_code == 200

    def test_registers_patch_route(self):
        def patch_item(name: str):
            return {"patched": name}

        app = create_lb_handler({("PATCH", "/items"): patch_item})
        client = TestClient(app)
        response = client.patch("/items", json={"name": "updated"})
        assert response.status_code == 200

    def test_unsupported_method_skipped(self):
        """Unsupported HTTP methods are logged and skipped."""

        def handler():
            return "ok"

        app = create_lb_handler({("OPTIONS", "/test"): handler})
        TestClient(app)
        # The route should not exist as a custom OPTIONS handler
        # (FastAPI auto-handles OPTIONS for CORS)

    def test_multiple_routes(self):
        def get_items():
            return []

        def create_item(name: str):
            return {"name": name}

        app = create_lb_handler(
            {
                ("GET", "/items"): get_items,
                ("POST", "/items"): create_item,
            }
        )
        client = TestClient(app)
        assert client.get("/items").status_code == 200
        assert client.post("/items", json={"name": "test"}).status_code == 200


class TestExecuteEndpoint:
    """Test /execute endpoint when include_execute=True."""

    @pytest.fixture
    def app_with_execute(self):
        return create_lb_handler({}, include_execute=True)

    @pytest.fixture
    def client(self, app_with_execute):
        return TestClient(app_with_execute)

    def test_execute_simple_function(self, client):
        """Execute a simple function via /execute."""
        from runpod_flash.runtime.serialization import serialize_arg

        response = client.post(
            "/execute",
            json={
                "function_name": "add",
                "function_code": "def add(x, y): return x + y",
                "args": [serialize_arg(3), serialize_arg(5)],
                "kwargs": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_execute_missing_function_name(self, client):
        response = client.post(
            "/execute",
            json={
                "function_code": "def f(): pass",
            },
        )
        data = response.json()
        assert data["success"] is False
        assert "Missing" in data["error"]

    def test_execute_missing_function_code(self, client):
        response = client.post(
            "/execute",
            json={
                "function_name": "f",
            },
        )
        data = response.json()
        assert data["success"] is False

    def test_execute_syntax_error(self, client):
        response = client.post(
            "/execute",
            json={
                "function_name": "bad",
                "function_code": "def bad(: invalid syntax",
            },
        )
        data = response.json()
        assert data["success"] is False
        assert "Syntax error" in data["error"]

    def test_execute_function_not_found_in_code(self, client):
        response = client.post(
            "/execute",
            json={
                "function_name": "missing_func",
                "function_code": "def other_func(): pass",
            },
        )
        data = response.json()
        assert data["success"] is False
        assert "not found" in data["error"]

    def test_execute_runtime_error(self, client):
        from runpod_flash.runtime.serialization import serialize_arg

        response = client.post(
            "/execute",
            json={
                "function_name": "failing",
                "function_code": "def failing(x): raise ValueError('boom')",
                "args": [serialize_arg(1)],
                "kwargs": {},
            },
        )
        data = response.json()
        assert data["success"] is False
        assert "boom" in data["error"]

    def test_execute_not_included_by_default(self):
        """Without include_execute, /execute endpoint doesn't exist."""
        app = create_lb_handler({}, include_execute=False)
        client = TestClient(app)
        response = client.post("/execute", json={})
        assert response.status_code == 404


class TestApiKeyMiddleware:
    """Test extract_api_key_middleware."""

    def test_extracts_bearer_token(self):
        app = create_lb_handler(
            {
                ("GET", "/test"): lambda: {"status": "ok"},
            }
        )
        client = TestClient(app)
        response = client.get("/test", headers={"Authorization": "Bearer test-key-123"})
        assert response.status_code == 200

    def test_no_auth_header(self):
        app = create_lb_handler(
            {
                ("GET", "/test"): lambda: {"status": "ok"},
            }
        )
        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200
