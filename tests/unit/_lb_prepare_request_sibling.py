"""Sibling module used by test_load_balancer_sls_stub.py to exercise local-module
resolution through LoadBalancerSlsStub._prepare_request. Not a test module itself."""


def sibling_value() -> int:
    return 42
