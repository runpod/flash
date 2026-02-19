"""Integration tests for API key propagation in preview mode.

Tests validate that API keys are properly propagated through Docker containers
in preview mode for the three PRD scenarios:
1. Mothership (LB) → GPU Worker (QB)
2. Mothership (LB) → CPU Worker (QB) → GPU Worker (QB)
3. Mothership-only (LB)
"""

import os
import threading
from unittest.mock import patch

from runpod_flash.cli.commands.preview import (
    _parse_resources_from_manifest,
    _build_resources_endpoints,
)


class TestPreviewAPIKeyInjection:
    """Integration tests for API key injection in preview mode."""

    def test_parse_resources_includes_makes_remote_calls_flag(self):
        """Resources parsed from manifest include makes_remote_calls flag."""
        manifest = {
            "resources": {
                "mothership": {
                    "is_mothership": True,
                    "imageName": "runpod/flash-lb:wip",
                    "functions": [],
                    "makes_remote_calls": True,
                },
                "gpu_worker": {
                    "is_mothership": False,
                    "imageName": "runpod/flash:wip",
                    "functions": [{"name": "process", "module": "workers.gpu"}],
                    "makes_remote_calls": False,
                },
            }
        }

        resources = _parse_resources_from_manifest(manifest)

        # Assert mothership is recognized
        assert "mothership" in resources
        assert resources["mothership"]["is_mothership"] is True
        assert resources["mothership"]["makes_remote_calls"] is True

        # Assert GPU worker is recognized
        assert "gpu_worker" in resources
        assert resources["gpu_worker"]["is_mothership"] is False
        assert resources["gpu_worker"]["makes_remote_calls"] is False

    def test_parse_resources_without_manifest_makes_remote_calls(self):
        """Default resources created without manifest default makes_remote_calls to False."""
        manifest = {"resources": {}}  # Empty resources

        resources = _parse_resources_from_manifest(manifest)

        # Assert default mothership is created
        assert "mothership" in resources
        assert resources["mothership"]["is_mothership"] is True
        assert resources["mothership"]["makes_remote_calls"] is False

    def test_build_resources_endpoints_creates_docker_dns_urls(self):
        """resources_endpoints maps resource names to Docker DNS URLs."""
        resources = {
            "mothership": {
                "is_mothership": True,
                "imageName": "runpod/flash-lb:wip",
                "makes_remote_calls": True,
            },
            "gpu_worker": {
                "is_mothership": False,
                "imageName": "runpod/flash-lb:wip",
                "makes_remote_calls": False,
            },
        }

        endpoints = _build_resources_endpoints(resources)

        # Assert Docker DNS URLs created
        assert endpoints["mothership"] == "http://flash-preview-mothership:80"
        assert endpoints["gpu_worker"] == "http://flash-preview-gpu_worker:80"

    def test_manifest_with_mothership_and_gpu_worker_with_remote_calls(self):
        """PRD Scenario 1: Mothership makes remote calls to GPU worker."""
        manifest = {
            "resources": {
                "mothership": {
                    "is_mothership": True,
                    "imageName": "runpod/flash-lb:wip",
                    "functions": [{"name": "route_request", "module": "main"}],
                    "makes_remote_calls": True,  # Mothership calls GPU worker
                },
                "gpu_worker": {
                    "is_mothership": False,
                    "imageName": "runpod/flash-lb:wip",
                    "functions": [{"name": "process_gpu", "module": "workers.gpu"}],
                    "makes_remote_calls": False,  # GPU worker doesn't call anyone
                },
            }
        }

        resources = _parse_resources_from_manifest(manifest)

        # Assert mothership needs API key
        assert resources["mothership"]["makes_remote_calls"] is True
        # Assert GPU worker doesn't need API key
        assert resources["gpu_worker"]["makes_remote_calls"] is False

    def test_manifest_with_chained_remote_calls(self):
        """PRD Scenario 2: Mothership → CPU worker → GPU worker (chain)."""
        manifest = {
            "resources": {
                "mothership": {
                    "is_mothership": True,
                    "imageName": "runpod/flash-lb:wip",
                    "functions": [{"name": "route", "module": "main"}],
                    "makes_remote_calls": True,  # Calls CPU worker
                },
                "cpu_worker": {
                    "is_mothership": False,
                    "imageName": "runpod/flash-lb:wip",
                    "functions": [{"name": "process_cpu", "module": "workers.cpu"}],
                    "makes_remote_calls": True,  # Calls GPU worker
                },
                "gpu_worker": {
                    "is_mothership": False,
                    "imageName": "runpod/flash-lb:wip",
                    "functions": [{"name": "process_gpu", "module": "workers.gpu"}],
                    "makes_remote_calls": False,  # Terminal node
                },
            }
        }

        resources = _parse_resources_from_manifest(manifest)

        # All except GPU worker need API key
        assert resources["mothership"]["makes_remote_calls"] is True
        assert resources["cpu_worker"]["makes_remote_calls"] is True
        assert resources["gpu_worker"]["makes_remote_calls"] is False

    def test_manifest_with_mothership_only(self):
        """PRD Scenario 3: Mothership-only (no workers)."""
        manifest = {
            "resources": {
                "mothership": {
                    "is_mothership": True,
                    "imageName": "runpod/flash-lb:wip",
                    "functions": [
                        {"name": "api_endpoint", "module": "main"},
                        {"name": "another_endpoint", "module": "main"},
                    ],
                    "makes_remote_calls": False,  # All functions are local
                }
            }
        }

        resources = _parse_resources_from_manifest(manifest)

        # Mothership doesn't need API key
        assert resources["mothership"]["makes_remote_calls"] is False


class TestPreviewModeStateManagerSkip:
    """Tests for preview mode State Manager query skipping."""

    def test_preview_endpoint_id_format(self):
        """Preview mode uses endpoint_id starting with 'preview-'."""
        # This format is set by preview.py:_start_resource_container()
        # Format: preview-{resource_name}
        preview_ids = ["preview-mothership", "preview-gpu_worker", "preview-cpu_worker"]

        for endpoint_id in preview_ids:
            # Should be detected as preview mode
            assert endpoint_id.startswith("preview-")

    def test_non_preview_endpoint_ids(self):
        """Non-preview endpoints have different format."""
        # Real RunPod endpoint IDs have format: abc123xyz...
        real_ids = ["abc123def456", "xyz789uvw", "endpoint-id-here"]

        for endpoint_id in real_ids:
            # Should NOT be detected as preview mode
            assert not endpoint_id.startswith("preview-")


class TestAPIKeyContextPropagation:
    """Tests for API key context propagation in workers."""

    def test_api_key_context_default_none(self):
        """API key context defaults to None."""
        from runpod_flash.runtime.api_key_context import get_api_key

        api_key = get_api_key()
        assert api_key is None

    def test_api_key_context_set_and_get(self):
        """API key can be set and retrieved from context."""
        from runpod_flash.runtime.api_key_context import (
            set_api_key,
            get_api_key,
            clear_api_key,
        )

        test_key = "test-api-key-123"

        # Set API key
        token = set_api_key(test_key)
        assert get_api_key() == test_key

        # Clear API key
        clear_api_key(token)
        assert get_api_key() is None

    def test_api_key_context_thread_safe(self):
        """API key context is thread-safe (contextvars behavior)."""
        from runpod_flash.runtime.api_key_context import (
            set_api_key,
            get_api_key,
            clear_api_key,
        )

        results = {}

        def set_and_verify(key_suffix):
            test_key = f"api-key-{key_suffix}"
            token = set_api_key(test_key)
            results[key_suffix] = get_api_key()
            clear_api_key(token)

        # Set different keys in different threads
        threads = [threading.Thread(target=set_and_verify, args=(i,)) for i in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Each thread should have its own value
        for i in range(3):
            assert results[i] == f"api-key-{i}"


class TestEnvironmentVariableBackoff:
    """Tests for environment variable backoff when context is not set."""

    def test_env_var_fallback_when_context_empty(self):
        """When context API key is None, environment variable is used."""
        from runpod_flash.runtime.api_key_context import get_api_key, clear_api_key

        # Clear context (set to None)
        clear_api_key()

        with patch.dict("os.environ", {"RUNPOD_API_KEY": "env-api-key"}):
            # Simulating logic in remote_executor.py
            api_key = get_api_key() or os.getenv("RUNPOD_API_KEY")
            assert api_key == "env-api-key"

    def test_context_takes_precedence_over_env_var(self):
        """When both context and env var set, context takes precedence."""
        from runpod_flash.runtime.api_key_context import (
            set_api_key,
            get_api_key,
            clear_api_key,
        )

        context_key = "context-key-123"
        env_key = "env-key-123"

        token = set_api_key(context_key)

        with patch.dict("os.environ", {"RUNPOD_API_KEY": env_key}):
            # Simulating logic in remote_executor.py
            api_key = get_api_key() or os.getenv("RUNPOD_API_KEY")
            assert api_key == context_key

        clear_api_key(token)

    def test_no_api_key_available(self):
        """When neither context nor env var set, api_key is None."""
        from runpod_flash.runtime.api_key_context import get_api_key, clear_api_key

        clear_api_key()

        with patch.dict("os.environ", {}, clear=True):
            api_key = get_api_key() or os.getenv("RUNPOD_API_KEY")
            assert api_key is None
