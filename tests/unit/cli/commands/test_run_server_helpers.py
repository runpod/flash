"""Tests for _run_server_helpers: make_input_model, make_wrapped_model, call_with_body, to_dict."""

from typing import Any

import pytest
from pydantic import BaseModel

from runpod_flash.cli.commands._run_server_helpers import (
    call_with_body,
    make_input_model,
    make_wrapped_model,
    to_dict,
)


# --- make_input_model ---


def test_make_input_model_basic():
    """Function with typed params produces a Pydantic model with correct fields."""

    async def process(text: str, count: int):
        pass

    Model = make_input_model("process_Input", process)
    assert Model is not None
    assert issubclass(Model, BaseModel)
    fields = Model.model_fields
    assert "text" in fields
    assert "count" in fields
    assert fields["text"].annotation is str
    assert fields["count"].annotation is int


def test_make_input_model_with_defaults():
    """Default values are preserved in the generated model."""

    async def transform(text: str, mode: str = "default", limit: int = 10):
        pass

    Model = make_input_model("transform_Input", transform)
    assert Model is not None
    fields = Model.model_fields
    assert fields["text"].is_required()
    assert not fields["mode"].is_required()
    assert fields["mode"].default == "default"
    assert fields["limit"].default == 10


def test_make_input_model_zero_params():
    """Zero-param function returns None."""

    async def health():
        pass

    result = make_input_model("health_Input", health)
    assert result is None


def test_make_input_model_skips_self():
    """Self parameter is excluded from the model (class methods)."""

    class Worker:
        def generate(self, prompt: str):
            pass

    Model = make_input_model("generate_Input", Worker().generate)
    assert Model is not None
    assert "self" not in Model.model_fields
    assert "prompt" in Model.model_fields


def test_make_input_model_untyped_params():
    """Untyped params get Any annotation."""

    async def process(data):
        pass

    Model = make_input_model("process_Input", process)
    assert Model is not None
    assert Model.model_fields["data"].annotation is Any


def test_make_input_model_skips_var_positional_and_keyword():
    """Proxy-style (*args, **kwargs) signatures return None, not a model with args/kwargs fields."""

    async def method_proxy(*args, **kwargs):
        pass

    result = make_input_model("proxy_Input", method_proxy)
    assert result is None


def test_make_input_model_mixed_regular_and_var_keyword():
    """Regular params are kept, **kwargs is skipped."""

    async def process(text: str, **extra):
        pass

    Model = make_input_model("process_Input", process)
    assert Model is not None
    assert "text" in Model.model_fields
    assert "extra" not in Model.model_fields


def test_make_input_model_failure_graceful():
    """Bad input returns None instead of raising."""
    result = make_input_model("bad_Input", 42)
    assert result is None


# --- make_wrapped_model ---


def test_make_wrapped_model_wraps_input_field():
    """Wrapped model has a single required 'input' field of the inner type."""

    async def process(text: str, count: int):
        pass

    Inner = make_input_model("process_Input", process)
    Wrapped = make_wrapped_model("process_Request", Inner)
    assert issubclass(Wrapped, BaseModel)
    fields = Wrapped.model_fields
    assert "input" in fields
    assert len(fields) == 1
    assert fields["input"].is_required()


def test_make_wrapped_model_roundtrip():
    """Wrapped model can be instantiated and inner data extracted via .input."""

    async def process(text: str, count: int):
        pass

    Inner = make_input_model("process_Input", process)
    Wrapped = make_wrapped_model("process_Request", Inner)
    instance = Wrapped(input={"text": "hello", "count": 5})
    assert instance.input.text == "hello"
    assert instance.input.count == 5


def test_make_wrapped_model_with_dict_inner():
    """Wrapped model works with dict as the inner type (fallback case)."""
    Wrapped = make_wrapped_model("fallback_Request", dict)
    instance = Wrapped(input={"key": "value"})
    assert instance.input == {"key": "value"}


# --- call_with_body ---


@pytest.mark.asyncio
async def test_call_with_body_pydantic():
    """Pydantic model body is spread as kwargs via model_dump()."""
    received = {}

    async def process(text: str, count: int):
        received.update(text=text, count=count)
        return {"ok": True}

    Model = make_input_model("process_Input", process)
    body = Model(text="hello", count=5)
    result = await call_with_body(process, body)
    assert result == {"ok": True}
    assert received == {"text": "hello", "count": 5}


@pytest.mark.asyncio
async def test_call_with_body_dict_fallback():
    """Plain dict body uses _map_body_to_params path."""
    received = {}

    async def process(data):
        received["data"] = data
        return {"ok": True}

    result = await call_with_body(process, {"data": "value"})
    assert result == {"ok": True}
    assert received == {"data": "value"}


@pytest.mark.asyncio
async def test_call_with_body_dict_with_input_wrapper():
    """Dict body with 'input' key unwraps correctly."""
    received = {}

    async def process(text: str):
        received["text"] = text
        return text

    result = await call_with_body(process, {"input": {"text": "hello"}})
    assert result == "hello"
    assert received == {"text": "hello"}


# --- to_dict ---


def test_to_dict_pydantic():
    """Pydantic model is converted to plain dict."""

    async def process(text: str, count: int):
        pass

    Model = make_input_model("process_Input", process)
    body = Model(text="hello", count=5)
    result = to_dict(body)
    assert result == {"text": "hello", "count": 5}
    assert isinstance(result, dict)


def test_to_dict_plain_dict():
    """Plain dict passes through unchanged."""
    body = {"text": "hello", "count": 5}
    result = to_dict(body)
    assert result == body
    assert result is body
