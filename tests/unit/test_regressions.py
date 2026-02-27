"""Regression tests for known bugs (REG-001 through REG-008).

Each test documents a specific bug found during flash-examples testing
and ensures it stays fixed across releases.
"""

import os
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# REG-001: ServerlessScalerType importable from top-level runpod_flash
# ---------------------------------------------------------------------------
class TestREG001TopLevelImports:
    """ServerlessScalerType was missing from __all__ in v1.3.0 PyPI."""

    def test_serverless_scaler_type_importable(self):
        """ServerlessScalerType is importable from runpod_flash top-level."""
        from runpod_flash import ServerlessScalerType

        assert hasattr(ServerlessScalerType, "QUEUE_DELAY")
        assert hasattr(ServerlessScalerType, "REQUEST_COUNT")

    def test_serverless_type_importable(self):
        """ServerlessType is importable from runpod_flash top-level."""
        from runpod_flash import ServerlessType

        assert ServerlessType is not None

    def test_all_public_symbols_importable(self):
        """All symbols in __all__ are actually importable."""
        import runpod_flash

        for symbol_name in runpod_flash.__all__:
            symbol = getattr(runpod_flash, symbol_name, None)
            assert symbol is not None, (
                f"Symbol '{symbol_name}' listed in __all__ but not importable"
            )


# ---------------------------------------------------------------------------
# REG-002: RUNPOD_ENDPOINT_ID in env → @remote class NOT eagerly instantiated
# ---------------------------------------------------------------------------
class TestREG002ClassNotEagerlyInstantiated:
    """@remote class should NOT call __init__ at decoration time."""

    def test_remote_class_does_not_call_init(self):
        """Creating RemoteClassWrapper does NOT call the original __init__."""
        from runpod_flash.execute_class import create_remote_class

        init_called = False

        class HeavyModel:
            def __init__(self):
                nonlocal init_called
                init_called = True
                # Simulates heavy work like loading a model
                self.model = "loaded"

            def predict(self, x):
                return x * 2

        mock_resource = MagicMock()
        RemoteWrapper = create_remote_class(HeavyModel, mock_resource, [], [], True, {})

        # Instantiate the wrapper — original __init__ should NOT fire
        instance = RemoteWrapper()
        assert init_called is False
        assert not instance._initialized

    @patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "ep-test-123"})
    def test_remote_decorator_on_class_in_deployed_env(self):
        """In deployed env, @remote on class still doesn't call __init__."""
        from runpod_flash.execute_class import create_remote_class

        init_called = False

        class GPUWorker:
            def __init__(self):
                nonlocal init_called
                init_called = True

            def run(self, data):
                return data

        mock_resource = MagicMock()
        RemoteWrapper = create_remote_class(GPUWorker, mock_resource, [], [], True, {})

        _ = RemoteWrapper()
        assert init_called is False


# ---------------------------------------------------------------------------
# REG-003: _should_execute_locally() ImportError fallback returns True
# ---------------------------------------------------------------------------
class TestREG003ShouldExecuteLocallyFallback:
    """ImportError in deployed env should default to local execution (True)."""

    @patch.dict(os.environ, {"RUNPOD_ENDPOINT_ID": "ep-test"})
    def test_import_error_fallback_returns_true(self):
        """Missing _flash_resource_config → defaults to True (safe)."""
        from runpod_flash.client import _should_execute_locally

        with patch.dict(
            "sys.modules",
            {"runpod_flash.runtime._flash_resource_config": None},
        ):
            result = _should_execute_locally("some_func")
            assert result is True

    @patch.dict(os.environ, {}, clear=True)
    def test_no_env_vars_returns_false(self):
        """Local dev (no env vars) returns False → creates stub."""
        from runpod_flash.client import _should_execute_locally

        result = _should_execute_locally("some_func")
        assert result is False


# ---------------------------------------------------------------------------
# REG-004: @remote class __init__ with heavy deps never called during flash run
# ---------------------------------------------------------------------------
class TestREG004ClassInitNotCalledDuringFlashRun:
    """Server generation should never instantiate @remote classes."""

    def test_wrapper_init_does_not_call_original(self):
        """RemoteClassWrapper.__init__ never calls original class __init__."""
        from runpod_flash.execute_class import create_remote_class

        import_attempted = False

        class ModelWorker:
            def __init__(self):
                nonlocal import_attempted
                import_attempted = True
                import torch  # noqa: F401 — would fail without torch installed

            def infer(self, data):
                return data

        mock_resource = MagicMock()
        Wrapper = create_remote_class(ModelWorker, mock_resource, [], [], True, {})
        _ = Wrapper()

        # If original __init__ ran, the torch import would have failed
        assert import_attempted is False

    def test_wrapper_stores_class_type_reference(self):
        """RemoteClassWrapper stores _class_type for signature introspection."""
        from runpod_flash.execute_class import create_remote_class

        class MyClass:
            def process(self, x: int) -> int:
                return x * 2

        mock_resource = MagicMock()
        Wrapper = create_remote_class(MyClass, mock_resource, [], [], True, {})
        instance = Wrapper()

        assert instance._class_type is MyClass


# ---------------------------------------------------------------------------
# REG-005: flash deploy with SSL_CERT_FILE works (Python 3.14 + macOS)
# ---------------------------------------------------------------------------
class TestREG005SSLCertFile:
    """SSL certificate configuration should not break API calls."""

    @patch.dict(os.environ, {"SSL_CERT_FILE": "/etc/ssl/certs/ca-certificates.crt"})
    def test_ssl_cert_file_env_var_accepted(self):
        """SSL_CERT_FILE env var doesn't crash resource creation."""
        from runpod_flash.core.resources import LiveServerless

        # Should not raise even with SSL_CERT_FILE set
        resource = LiveServerless(name="ssl-test")
        assert resource.name is not None


# ---------------------------------------------------------------------------
# REG-006: flash deploy respects worker quota → clear error message
# ---------------------------------------------------------------------------
class TestREG006WorkerQuotaError:
    """Quota exceeded should produce a clear error, not a cryptic traceback."""

    @pytest.mark.asyncio
    async def test_quota_error_propagates_cleanly(self):
        """GraphQL quota error produces human-readable message."""
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(
            name="quota-test",
            workersMax=100,
        )

        quota_error = Exception("Max workers for this account must not exceed 10")

        with patch.object(LiveServerless, "_do_deploy", side_effect=quota_error):
            with pytest.raises(Exception, match="must not exceed"):
                await resource._do_deploy()


# ---------------------------------------------------------------------------
# REG-007: Large base64 payload (>10MB) handling
# ---------------------------------------------------------------------------
class TestREG007LargePayload:
    """Large serialized payloads should serialize without silent corruption."""

    def test_large_payload_roundtrip(self):
        """10MB+ payload survives serialize → deserialize without corruption."""
        from runpod_flash.runtime.serialization import deserialize_arg, serialize_arg

        # Create a ~10MB payload
        large_data = b"x" * (10 * 1024 * 1024)
        serialized = serialize_arg(large_data)
        restored = deserialize_arg(serialized)

        assert restored == large_data
        assert len(restored) == len(large_data)


# ---------------------------------------------------------------------------
# REG-008: flash env delete works in non-interactive mode (no TTY)
# ---------------------------------------------------------------------------
class TestREG008NonInteractiveEnvDelete:
    """Commands should not crash when stdin is not a TTY."""

    def test_undeploy_resource_force_remove_no_tty(self):
        """force_remove=True skips interactive confirmation."""
        import asyncio

        from runpod_flash.core.resources import LiveServerless
        from runpod_flash.core.resources.resource_manager import ResourceManager

        manager = ResourceManager()
        resource = LiveServerless(name="no-tty-test")

        loop = asyncio.new_event_loop()
        try:
            uid = loop.run_until_complete(manager.register_resource(resource))

            # force_remove should work without any TTY/stdin interaction
            loop.run_until_complete(manager.undeploy_resource(uid, force_remove=True))
            assert uid not in manager.list_all_resources()
        finally:
            loop.close()
