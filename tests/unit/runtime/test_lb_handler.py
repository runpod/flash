"""Unit tests for LoadBalancer handler factory."""

import inspect
from typing import Any

from fastapi.testclient import TestClient
from pydantic import BaseModel

from runpod_flash.runtime.lb_handler import (
    _make_input_model,
    _wrap_handler_with_body_model,
    create_lb_handler,
)


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


class TestMakeInputModel:
    """Unit tests for _make_input_model."""

    def test_typed_params_become_fields(self):
        def classify(text: str, threshold: float) -> str: ...

        model = _make_input_model("ClassifyBody", classify)
        assert model is not None
        assert "text" in model.model_fields
        assert "threshold" in model.model_fields

    def test_default_values_preserved(self):
        def classify(text: str, threshold: float = 0.5) -> str: ...

        model = _make_input_model("ClassifyBody", classify)
        assert model is not None
        assert model.model_fields["threshold"].default == 0.5

    def test_zero_param_returns_none(self):
        def health() -> str: ...

        model = _make_input_model("HealthBody", health)
        assert model is None

    def test_exclude_set_removes_params(self):
        def handler(item_id: int, name: str) -> str: ...

        model = _make_input_model("HandlerBody", handler, exclude={"item_id"})
        assert model is not None
        assert "item_id" not in model.model_fields
        assert "name" in model.model_fields

    def test_var_positional_and_var_keyword_skipped(self):
        def handler(*args: Any, **kwargs: Any) -> str: ...

        model = _make_input_model("HandlerBody", handler)
        assert model is None

    def test_unannotated_params_default_to_any(self):
        def handler(text): ...

        model = _make_input_model("HandlerBody", handler)
        assert model is not None
        assert "text" in model.model_fields


class TestWrapHandlerWithBodyModel:
    """Unit tests for _wrap_handler_with_body_model."""

    def test_wraps_async_handler(self):
        async def classify(text: str) -> str:
            return text

        wrapped = _wrap_handler_with_body_model(classify, "/classify")
        assert wrapped is not classify
        sig = inspect.signature(wrapped)
        assert "body" in sig.parameters

    def test_wraps_sync_handler(self):
        def classify(text: str) -> str:
            return text

        wrapped = _wrap_handler_with_body_model(classify, "/classify")
        assert wrapped is not classify
        sig = inspect.signature(wrapped)
        assert "body" in sig.parameters

    def test_skips_pydantic_typed_param(self):
        class MyInput(BaseModel):
            text: str

        async def classify(body: MyInput) -> str:
            return body.text

        wrapped = _wrap_handler_with_body_model(classify, "/classify")
        assert wrapped is classify

    def test_skips_zero_param_handler(self):
        async def health() -> str:
            return "ok"

        wrapped = _wrap_handler_with_body_model(health, "/health")
        assert wrapped is health

    def test_handles_path_params(self):
        async def get_item(item_id: int, name: str) -> dict:
            return {"id": item_id, "name": name}

        wrapped = _wrap_handler_with_body_model(get_item, "/items/{item_id}")
        sig = inspect.signature(wrapped)
        assert "body" in sig.parameters
        # item_id excluded from body model, only name remains
        body_type = sig.parameters["body"].annotation
        assert "name" in body_type.model_fields
        assert "item_id" not in body_type.model_fields


class TestCreateLbHandlerBodyParsing:
    """Integration tests via TestClient for body parsing."""

    def test_post_json_body_parsed(self):
        async def classify(text: str) -> dict:
            return {"label": text}

        app = create_lb_handler({("POST", "/classify"): classify})
        client = TestClient(app)

        resp = client.post("/classify", json={"text": "hello"})
        assert resp.status_code == 200
        assert resp.json() == {"label": "hello"}

    def test_missing_field_error_references_body(self):
        async def classify(text: str) -> dict:
            return {"label": text}

        app = create_lb_handler({("POST", "/classify"): classify})
        client = TestClient(app)

        resp = client.post("/classify", json={})
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        locations = [e["loc"] for e in detail]
        # Must reference "body", not "query"
        assert any("body" in loc for loc in locations)
        assert not any("query" in loc for loc in locations)

    def test_get_still_uses_query_params(self):
        async def search(q: str) -> dict:
            return {"query": q}

        app = create_lb_handler({("GET", "/search"): search})
        client = TestClient(app)

        resp = client.get("/search", params={"q": "hello"})
        assert resp.status_code == 200
        assert resp.json() == {"query": "hello"}

    def test_zero_param_post_works(self):
        async def health() -> dict:
            return {"status": "ok"}

        app = create_lb_handler({("POST", "/health"): health})
        client = TestClient(app)

        resp = client.post("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_path_params_and_body_params_coexist(self):
        async def update_item(item_id: int, name: str) -> dict:
            return {"id": item_id, "name": name}

        app = create_lb_handler({("POST", "/items/{item_id}"): update_item})
        client = TestClient(app)

        resp = client.post("/items/42", json={"name": "widget"})
        assert resp.status_code == 200
        assert resp.json() == {"id": 42, "name": "widget"}

    def test_handler_with_defaults(self):
        async def classify(text: str, threshold: float = 0.5) -> dict:
            return {"text": text, "threshold": threshold}

        app = create_lb_handler({("POST", "/classify"): classify})
        client = TestClient(app)

        # Only required field
        resp = client.post("/classify", json={"text": "hello"})
        assert resp.status_code == 200
        assert resp.json() == {"text": "hello", "threshold": 0.5}

        # Override default
        resp = client.post("/classify", json={"text": "hello", "threshold": 0.9})
        assert resp.status_code == 200
        assert resp.json() == {"text": "hello", "threshold": 0.9}

    def test_put_method_also_wrapped(self):
        async def update(name: str) -> dict:
            return {"name": name}

        app = create_lb_handler({("PUT", "/update"): update})
        client = TestClient(app)

        resp = client.put("/update", json={"name": "test"})
        assert resp.status_code == 200
        assert resp.json() == {"name": "test"}

    def test_pydantic_model_param_not_double_wrapped(self):
        class MyInput(BaseModel):
            text: str

        async def classify(body: MyInput) -> dict:
            return {"label": body.text}

        app = create_lb_handler({("POST", "/classify"): classify})
        client = TestClient(app)

        resp = client.post("/classify", json={"text": "hello"})
        assert resp.status_code == 200
        assert resp.json() == {"label": "hello"}
