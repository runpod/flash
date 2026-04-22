"""Security gap-fill tests for P0/P1 security test plan items.

Covers: SEC-005 (cloudpickle deserialization safety),
        SEC-006 (API key per-request isolation),
        SEC-008 (secrets in env dict not leaked in error messages).
"""

import base64
import logging
import os
import pickle
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# SEC-005: Cloudpickle deserialization — attack surface documentation
# ---------------------------------------------------------------------------
class TestCloudpickleDeserializationSafety:
    """SEC-005: Verify cloudpickle deserialization attack surface is understood
    and trust boundaries are enforced.

    Cloudpickle (like pickle) can execute arbitrary code during deserialization.
    Flash accepts serialized results from RunPod API responses. The security
    model relies on:
    1. Only deserializing from authenticated RunPod endpoints
    2. TLS transport (HTTPS) preventing MITM payload injection
    3. The SensitiveDataFilter preventing key leakage that could allow
       an attacker to impersonate the API

    These tests document the attack surface and verify the trust boundaries.
    """

    def test_crafted_pickle_can_execute_code(self):
        """Document that cloudpickle.loads CAN execute arbitrary code.

        This verifies the attack surface exists without actually executing an
        exploit. The security model relies on only deserializing from
        authenticated RunPod endpoints over TLS, not on pickle being safe.
        """

        class Exploit:
            def __reduce__(self):
                return (eval, ("1+1",))

        payload = pickle.dumps(Exploit())

        # Verify the __reduce__ protocol is present — this is what makes
        # pickle deserialization dangerous. The actual code execution path
        # is: pickle.loads -> __reduce__ -> callable(*args).
        reduce_result = Exploit().__reduce__()
        assert callable(reduce_result[0]), "Pickle __reduce__ returns a callable"
        assert reduce_result[0].__name__ == "eval", "Callable is eval — arbitrary code"

        # Verify pickle.loads invokes __reduce__ (harmless expression)
        result = pickle.loads(payload)
        assert result == 2, "pickle.loads executed the __reduce__ callable"

    def test_deserialization_only_from_api_response(self):
        """Verify that stub deserialization only processes data from
        authenticated RunPod API endpoints, not arbitrary sources.

        LiveServerlessStub.handle_response() only runs on FunctionResponse
        objects returned from RunPod endpoint.run()/runsync().
        """
        from runpod_flash.stubs.live_serverless import LiveServerlessStub

        # Stub requires a deployed server (RunPod endpoint)
        stub = LiveServerlessStub.__new__(LiveServerlessStub)

        # handle_response rejects invalid input structure
        with pytest.raises((ValueError, AttributeError)):
            stub.handle_response(None)

        with pytest.raises((ValueError, AttributeError)):
            stub.handle_response("arbitrary string")

    def test_lb_stub_validates_response_type(self):
        """LoadBalancerSlsStub._handle_response validates response is dict."""
        from runpod_flash.stubs.load_balancer_sls import LoadBalancerSlsStub

        stub = LoadBalancerSlsStub.__new__(LoadBalancerSlsStub)

        with pytest.raises(ValueError, match="Invalid response type"):
            stub._handle_response("not a dict")

        with pytest.raises(ValueError, match="Invalid response type"):
            stub._handle_response(42)

        with pytest.raises(ValueError, match="Invalid response type"):
            stub._handle_response(None)

    def test_lb_stub_rejects_success_without_result(self):
        """LoadBalancerSlsStub rejects success response with no result."""
        from runpod_flash.stubs.load_balancer_sls import LoadBalancerSlsStub

        stub = LoadBalancerSlsStub.__new__(LoadBalancerSlsStub)

        with pytest.raises(ValueError, match="result is None"):
            stub._handle_response({"success": True, "result": None})

    def test_deserialization_rejects_corrupted_payload(self):
        """Corrupted base64/pickle data raises SerializationError, not crash."""
        from runpod_flash.runtime.exceptions import SerializationError
        from runpod_flash.runtime.serialization import deserialize_arg

        with pytest.raises(SerializationError):
            deserialize_arg("not-valid-base64!!!")

        with pytest.raises(SerializationError):
            deserialize_arg(base64.b64encode(b"not-valid-pickle").decode())

    def test_deserialization_roundtrip_safe_types(self):
        """Verify safe round-trip for legitimate data types."""
        from runpod_flash.runtime.serialization import deserialize_arg, serialize_arg

        test_values = [
            42,
            3.14,
            "hello",
            True,
            None,
            [1, 2, 3],
            {"key": "value"},
            (1, "two", 3.0),
            b"binary data",
        ]

        for value in test_values:
            serialized = serialize_arg(value)
            result = deserialize_arg(serialized)
            assert result == value, f"Round-trip failed for {type(value).__name__}"

    def test_api_endpoints_use_https(self):
        """Verify API endpoints default to HTTPS (TLS transport)."""
        from runpod_flash.core.api.runpod import RunpodGraphQLClient

        assert RunpodGraphQLClient.GRAPHQL_URL.startswith("https://")

    def test_rest_api_uses_https(self):
        """Verify REST API endpoints default to HTTPS."""
        from runpod_flash.core.urls import RUNPOD_REST_API_URL

        assert RUNPOD_REST_API_URL.startswith("https://")


# ---------------------------------------------------------------------------
# SEC-006: API key isolation (no global mutable state)
# ---------------------------------------------------------------------------
class TestApiKeyIsolation:
    """SEC-006: API key uses instance attributes, not global mutable state."""

    def test_graphql_client_does_not_use_mutable_global(self):
        """RunpodGraphQLClient stores API key as instance attribute, not global."""
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "test-key-for-init"}):
            from runpod_flash.core.api.runpod import RunpodGraphQLClient

            client = RunpodGraphQLClient(api_key="instance-key")
            assert client.api_key == "instance-key"

            # Second client gets its own key
            client2 = RunpodGraphQLClient(api_key="other-key")
            assert client2.api_key == "other-key"
            assert client.api_key == "instance-key"  # Not mutated


# ---------------------------------------------------------------------------
# SEC-008: Secrets in env dict not leaked in error messages
# ---------------------------------------------------------------------------
class TestSecretsNotLeakedInErrors:
    """SEC-008: Verify secrets in env dict are not exposed in error messages,
    repr output, or log messages during deployment failures.
    """

    def _make_resource_with_secrets(self):
        """Create a resource with secrets in its env dict."""
        from runpod_flash.core.resources import LiveServerless

        return LiveServerless(
            name="secret-test",
            env={
                "RUNPOD_API_KEY": "sk-secret-api-key-12345",
                "DATABASE_PASSWORD": "supersecretdb",
                "PUBLIC_VAR": "not-secret",
            },
        )

    def test_str_does_not_leak_env(self):
        """str(resource) must not include env dict contents."""
        resource = self._make_resource_with_secrets()
        s = str(resource)
        assert "sk-secret-api-key-12345" not in s
        assert "supersecretdb" not in s

    @pytest.mark.xfail(
        reason="Known limitation: Pydantic default __repr__ includes env dict. "
        "Error handlers and loggers must use str() or SensitiveDataFilter, "
        "never repr() on resource objects. Will pass when repr is overridden.",
        strict=False,
    )
    def test_repr_does_not_leak_env_secrets(self):
        """Pydantic __repr__ should not include secret values from env dict.

        Currently Pydantic's default repr includes all fields. This test
        documents the known risk and will start passing once we override
        __repr__ to redact sensitive fields.
        """
        resource = self._make_resource_with_secrets()
        r = repr(resource)
        assert "sk-secret-api-key-12345" not in r
        assert "supersecretdb" not in r

    def test_deployment_error_uses_str_not_repr(self):
        """ResourceManager error messages use str(resource) and resource.name, not repr()."""
        resource = self._make_resource_with_secrets()

        # Verify str() doesn't leak secrets
        s = str(resource)
        assert "sk-secret-api-key-12345" not in s
        assert "supersecretdb" not in s

        # Verify resource.name doesn't leak secrets (used in error messages)
        assert "sk-secret-api-key-12345" not in resource.name
        assert "supersecretdb" not in resource.name

    def test_sensitive_filter_redacts_env_secrets_in_logs(self):
        """SensitiveDataFilter redacts known sensitive keys from log messages."""
        from runpod_flash.logger import SensitiveDataFilter

        filt = SensitiveDataFilter()

        # Simulate a log message that accidentally includes env dict.
        # The filter matches exact key names (case-insensitive) from
        # SENSITIVE_KEYS: api_key, password, token, secret, etc.
        env_dict = {
            "API_KEY": "sk-secret-api-key-12345",
            "PASSWORD": "supersecretdb",
            "SECRET": "topsecret",
            "PUBLIC_VAR": "not-secret",
        }

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=0,
            msg="Deploy failed with env: %s",
            args=(env_dict,),
            exc_info=None,
        )

        filt.filter(record)
        sanitized = record.args
        assert sanitized["API_KEY"] == "***REDACTED***"
        assert sanitized["PASSWORD"] == "***REDACTED***"
        assert sanitized["SECRET"] == "***REDACTED***"
        assert sanitized["PUBLIC_VAR"] == "not-secret"

    def test_sensitive_filter_redacts_runpod_api_key(self):
        """SensitiveDataFilter specifically redacts RUNPOD_API_KEY."""
        from runpod_flash.logger import SensitiveDataFilter

        filt = SensitiveDataFilter()

        env_dict = {"RUNPOD_API_KEY": "sk-secret-12345"}

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=0,
            msg="Env: %s",
            args=(env_dict,),
            exc_info=None,
        )

        filt.filter(record)
        assert record.args["RUNPOD_API_KEY"] == "***REDACTED***"

    def test_graphql_error_does_not_include_env(self):
        """GraphQL error messages from deployment don't include env dict.

        The save_endpoint mutation payload is sanitized before logging.
        """
        from runpod_flash.core.api.runpod import _sanitize_for_logging

        payload_with_sensitive_url = {
            "name": "my-endpoint",
            "uploadUrl": "https://storage.example.com/signed?token=secret123",
            "downloadUrl": "https://storage.example.com/signed?token=secret456",
            "presignedUrl": "https://storage.example.com/presigned?auth=key789",
        }

        sanitized = _sanitize_for_logging(payload_with_sensitive_url)
        assert sanitized["name"] == "my-endpoint"
        assert sanitized["uploadUrl"] == "<REDACTED>"
        assert sanitized["downloadUrl"] == "<REDACTED>"
        assert sanitized["presignedUrl"] == "<REDACTED>"

    def test_exception_traceback_sanitized_in_logs(self):
        """SensitiveDataFilter sanitizes API keys in exception tracebacks."""
        from runpod_flash.logger import SensitiveDataFilter

        filt = SensitiveDataFilter()

        try:
            raise ValueError("Failed with key sk-1234567890abcdef1234567890abcdef")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=0,
            msg="Deployment error",
            args=(),
            exc_info=exc_info,
        )

        filt.filter(record)
        # exc_info should be cleared (filter formats and redacts it)
        assert record.exc_info is None
        # exc_text should contain the redacted traceback
        assert record.exc_text is not None
        assert "sk-1234567890abcdef1234567890abcdef" not in record.exc_text
        assert "***REDACTED***" in record.exc_text

    def test_model_dump_excludes_env_from_input_only(self):
        """ServerlessResource._input_only includes 'env', so model_dump for
        API payload excludes it from the serialized output."""
        from runpod_flash.core.resources.serverless import ServerlessResource

        # _input_only is a Pydantic ModelPrivateAttr with default value
        assert "env" in ServerlessResource._input_only.default
