"""Sibling module used by test_stub_live_serverless.py to exercise local-module
resolution through LiveServerlessStub.prepare_request. Not a test module itself."""


def sibling_value() -> int:
    return 99
