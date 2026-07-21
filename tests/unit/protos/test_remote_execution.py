from runpod_flash.protos.remote_execution import FunctionRequest


def test_modules_defaults_to_empty_dict():
    req = FunctionRequest(function_name="f", function_code="def f(): pass")
    assert req.modules == {}


def test_modules_round_trips_through_model_dump():
    req = FunctionRequest(
        function_name="f",
        function_code="def f(): import utils; return utils.x()",
        modules={"utils.py": "def x():\n    return 1\n"},
    )
    payload = req.model_dump(exclude_none=True)
    assert payload["modules"] == {"utils.py": "def x():\n    return 1\n"}
    rebuilt = FunctionRequest(**payload)
    assert rebuilt.modules == req.modules
