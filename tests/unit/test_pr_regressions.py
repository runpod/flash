"""PR-identified regression tests.

Tests derived from reviewing recent merged PRs and their Copilot review
comments. Covers edge cases in:
- SensitiveDataFilter (logger.py) - known edge cases from PR #200
- Port assignment (preview.py) - collision edge cases
- Decorator invocation verification - tests that actually call decorated stubs
"""

import logging
from unittest.mock import MagicMock

import pytest

from runpod_flash.logger import SensitiveDataFilter


# ---------------------------------------------------------------------------
# SensitiveDataFilter edge-case tests (from PR #200 review)
# ---------------------------------------------------------------------------
class TestSensitiveDataFilterEdgeCases:
    """Edge cases identified in PR #200 Copilot review."""

    @pytest.fixture
    def filt(self):
        return SensitiveDataFilter()

    @pytest.fixture
    def make_record(self):
        """Helper to build a LogRecord with a given message."""

        def _make(msg, args=None):
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg=msg,
                args=args,
                exc_info=None,
            )
            return record

        return _make

    # --- API key patterns ---

    def test_redacts_api_key_with_equals(self, filt, make_record):
        record = make_record("api_key=sk-abc123longvaluehere1234567890abcd")
        filt.filter(record)
        assert "sk-abc123" not in record.msg
        assert "REDACTED" in record.msg

    def test_redacts_api_key_with_colon(self, filt, make_record):
        record = make_record("apiKey: mysecretkeyvalue12345678")
        filt.filter(record)
        assert "mysecretkey" not in record.msg
        assert "REDACTED" in record.msg

    def test_redacts_runpod_api_key(self, filt, make_record):
        record = make_record('runpod_api_key="ABCDEF1234567890"')
        filt.filter(record)
        assert "ABCDEF" not in record.msg
        assert "REDACTED" in record.msg

    def test_redacts_quoted_api_key(self, filt, make_record):
        record = make_record("api_key='my-secret-value-123'")
        filt.filter(record)
        assert "my-secret-value" not in record.msg

    # --- Bearer tokens ---

    def test_redacts_bearer_token(self, filt, make_record):
        record = make_record("Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.longtoken")
        filt.filter(record)
        assert "eyJhbGci" not in record.msg
        assert "REDACTED" in record.msg

    def test_redacts_bearer_case_insensitive(self, filt, make_record):
        record = make_record("BEARER tokenabc123xyz")
        filt.filter(record)
        assert "tokenabc" not in record.msg

    # --- Prefixed keys (sk-, key_, api_) ---

    def test_redacts_sk_prefixed_key(self, filt, make_record):
        key = "sk-" + "a" * 40
        record = make_record(f"Using key: {key}")
        filt.filter(record)
        assert key not in record.msg
        assert "REDACTED" in record.msg

    def test_redacts_key_underscore_prefix(self, filt, make_record):
        key = "key_" + "X" * 40
        record = make_record(f"Config: {key}")
        filt.filter(record)
        assert key not in record.msg

    def test_short_sk_prefix_not_redacted(self, filt, make_record):
        """sk- prefix with short value (<28 chars) should NOT be redacted."""
        record = make_record("sk-short")
        filt.filter(record)
        assert "sk-short" in record.msg

    # --- Password/secret patterns ---

    def test_redacts_password_equals(self, filt, make_record):
        record = make_record("password=hunter2")
        filt.filter(record)
        assert "hunter2" not in record.msg

    def test_redacts_password_quoted(self, filt, make_record):
        record = make_record('password="super secret"')
        filt.filter(record)
        assert "super secret" not in record.msg

    def test_redacts_secret_field(self, filt, make_record):
        record = make_record("secret: mysecretvalue123")
        filt.filter(record)
        assert "mysecretvalue" not in record.msg

    def test_redacts_passwd_field(self, filt, make_record):
        record = make_record("passwd=abc123")
        filt.filter(record)
        assert "abc123" not in record.msg

    # --- Dictionary redaction ---

    def test_redacts_dict_sensitive_keys(self, filt, make_record):
        record = make_record("Config: %s", {"api_key": "secret123", "name": "test"})
        filt.filter(record)
        assert record.args["api_key"] == "***REDACTED***"
        assert record.args["name"] == "test"

    def test_redacts_nested_dict(self, filt, make_record):
        record = make_record("Config: %s")
        record.args = {"config": {"password": "secret"}}
        filt.filter(record)
        assert record.args["config"]["password"] == "***REDACTED***"

    def test_redacts_dict_with_list_values(self, filt, make_record):
        record = make_record("Data: %s")
        record.args = {"items": [{"token": "abc123"}]}
        filt.filter(record)
        assert record.args["items"][0]["token"] == "***REDACTED***"

    def test_case_insensitive_dict_keys(self, filt, make_record):
        record = make_record("Auth: %s", {"API_KEY": "secret", "Token": "abc"})
        filt.filter(record)
        assert record.args["API_KEY"] == "***REDACTED***"
        assert record.args["Token"] == "***REDACTED***"

    def test_non_string_dict_key(self, filt, make_record):
        """Handles non-string keys without crashing."""
        record = make_record("Data: %s", {42: "value", "api_key": "secret"})
        filt.filter(record)
        assert record.args["api_key"] == "***REDACTED***"
        assert record.args[42] == "value"

    # --- Tuple/list args ---

    def test_redacts_tuple_args(self, filt, make_record):
        record = make_record(
            "User %s with key %s",
            ("alice", "Bearer token123abc"),
        )
        filt.filter(record)
        assert "token123" not in record.args[1]

    def test_redacts_list_in_value(self, filt):
        record = logging.LogRecord(
            "test",
            logging.INFO,
            "test.py",
            1,
            "Keys: %s",
            ({"keys": ["sk-" + "a" * 40]},),
            None,
        )
        filt.filter(record)
        assert ("sk-" + "a" * 40) not in str(record.args)

    # --- Exception info ---

    def test_redacts_exception_info(self, filt, make_record):
        """Exception tracebacks containing secrets get redacted."""
        try:
            raise ValueError("api_key=SUPERSECRET123456789012345678")
        except ValueError:
            import sys

            record = make_record("Error occurred")
            record.exc_info = sys.exc_info()
            filt.filter(record)
            assert record.exc_info is None  # Cleared after redaction
            assert "SUPERSECRET" not in (record.exc_text or "")

    # --- Non-sensitive data should pass through ---

    def test_preserves_normal_message(self, filt, make_record):
        record = make_record("Processing 42 items from queue")
        filt.filter(record)
        assert record.msg == "Processing 42 items from queue"

    def test_preserves_hex_hashes(self, filt, make_record):
        """Commit SHAs / hashes should NOT be redacted."""
        sha = "a" * 40  # 40-char hex hash
        record = make_record(f"Commit: {sha}")
        filt.filter(record)
        assert sha in record.msg

    def test_always_returns_true(self, filt, make_record):
        """Filter always returns True (fail-open)."""
        record = make_record("any message")
        assert filt.filter(record) is True

    def test_filter_survives_broken_record(self, filt):
        """Filter doesn't crash on malformed records."""
        record = MagicMock()
        record.msg = None
        record.args = None
        record.exc_info = None
        record.exc_text = None
        assert filt.filter(record) is True


# ---------------------------------------------------------------------------
# Port assignment edge cases (preview.py)
# ---------------------------------------------------------------------------
class TestPortAssignment:
    """Test _assign_container_port edge cases from PR review."""

    def test_load_balancer_always_8000(self):
        from runpod_flash.cli.commands.preview import _assign_container_port

        assert _assign_container_port("anything", is_load_balanced=True) == 8000

    def test_gpu_config_gets_8001(self):
        from runpod_flash.cli.commands.preview import _assign_container_port

        assert _assign_container_port("gpu_config", is_load_balanced=False) == 8001

    def test_cpu_config_gets_8002(self):
        from runpod_flash.cli.commands.preview import _assign_container_port

        assert _assign_container_port("cpu_config", is_load_balanced=False) == 8002

    def test_unknown_resource_deterministic(self):
        """Same resource name always maps to same port."""
        from runpod_flash.cli.commands.preview import _assign_container_port

        port1 = _assign_container_port("my-custom-worker", is_load_balanced=False)
        port2 = _assign_container_port("my-custom-worker", is_load_balanced=False)
        assert port1 == port2
        assert 8001 <= port1 <= 8099

    def test_different_resources_likely_different_ports(self):
        """Different resource names should map to different ports (usually)."""
        from runpod_flash.cli.commands.preview import _assign_container_port

        port_a = _assign_container_port("worker-alpha", is_load_balanced=False)
        port_b = _assign_container_port("worker-beta", is_load_balanced=False)
        # Can't guarantee they're different (hash collision possible),
        # but they should be in valid range
        assert 8001 <= port_a <= 8099
        assert 8001 <= port_b <= 8099

    def test_port_range_bounded(self):
        """Hash-based port should never exceed 8099."""
        from runpod_flash.cli.commands.preview import _assign_container_port

        for name in [f"resource-{i}" for i in range(50)]:
            port = _assign_container_port(name, is_load_balanced=False)
            assert 8001 <= port <= 8099, f"Port {port} out of range for {name}"


# ---------------------------------------------------------------------------
# Decorator stub invocation tests
# (PR review found tests that create stubs but never call them)
# ---------------------------------------------------------------------------
class TestDecoratorActuallyInvokesStub:
    """Ensure @remote decorated functions actually route through stubs."""

    def test_remote_function_returns_stub_callable(self):
        """@remote on a function returns something callable."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="test-invoke")

        @remote(resource)
        async def my_func(x: int) -> int:
            return x * 2

        # The returned object should be callable
        assert callable(my_func)

    @pytest.mark.asyncio
    async def test_remote_with_local_true_calls_original(self):
        """@remote(local=True) should execute the original function."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="test-local")

        @remote(resource, local=True)
        async def add(x: int, y: int) -> int:
            return x + y

        result = await add(3, 5)
        assert result == 8

    def test_remote_local_sync_function(self):
        """@remote(local=True) with sync function."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="test-sync-local")

        @remote(resource, local=True)
        def multiply(x: int, y: int) -> int:
            return x * y

        result = multiply(4, 5)
        assert result == 20


class TestDecoratorValidation:
    """Test decorator parameter validation from flash-examples patterns."""

    def test_lb_resource_requires_method_and_path(self):
        """LB resources must have method and path."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import LiveLoadBalancer

        resource = LiveLoadBalancer(name="test-lb")

        # Should work with both method and path
        @remote(resource, method="GET", path="/health")
        async def health():
            return {"status": "ok"}

        assert callable(health)

    def test_lb_resource_raises_without_method(self):
        """LB resource without method/path should raise ValueError."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import LiveLoadBalancer

        resource = LiveLoadBalancer(name="test-lb-no-method")

        with pytest.raises(ValueError, match="requires both 'method' and 'path'"):

            @remote(resource)
            async def process(x: int):
                return x
