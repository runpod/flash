"""Unit tests for runtime models."""

from runpod_flash.runtime.models import Manifest, ResourceConfig


def _make_manifest_dict(**overrides):
    """Build a minimal valid manifest dict with optional overrides."""
    base = {
        "version": "1.0",
        "generated_at": "2026-01-01T00:00:00",
        "project_name": "test-project",
        "function_registry": {"func_a": "resource_x"},
        "resources": {
            "resource_x": {
                "resource_type": "local",
                "functions": [],
                "makes_remote_calls": False,
            }
        },
    }
    base.update(overrides)
    return base


class TestManifestResourcesEndpoints:
    """Tests for the resources_endpoints field on Manifest."""

    def test_manifest_from_dict_includes_resources_endpoints(self):
        """from_dict parses resources_endpoints when present."""
        endpoints = {"resource_x": "https://api.runpod.ai/v2/abc123"}
        data = _make_manifest_dict(resources_endpoints=endpoints)

        manifest = Manifest.from_dict(data)

        assert manifest.resources_endpoints == endpoints

    def test_manifest_to_dict_includes_resources_endpoints(self):
        """to_dict includes resources_endpoints when not None."""
        endpoints = {"resource_x": "https://api.runpod.ai/v2/abc123"}
        manifest = Manifest(
            version="1.0",
            generated_at="2026-01-01T00:00:00",
            project_name="test-project",
            function_registry={"func_a": "resource_x"},
            resources={
                "resource_x": ResourceConfig(
                    resource_type="local", functions=[], makes_remote_calls=False
                )
            },
            resources_endpoints=endpoints,
        )

        result = manifest.to_dict()

        assert result["resources_endpoints"] == endpoints

    def test_manifest_from_dict_without_resources_endpoints(self):
        """from_dict defaults resources_endpoints to None for backward compat."""
        data = _make_manifest_dict()

        manifest = Manifest.from_dict(data)

        assert manifest.resources_endpoints is None

    def test_manifest_to_dict_omits_none_resources_endpoints(self):
        """to_dict omits resources_endpoints key when value is None."""
        manifest = Manifest(
            version="1.0",
            generated_at="2026-01-01T00:00:00",
            project_name="test-project",
            function_registry={"func_a": "resource_x"},
            resources={
                "resource_x": ResourceConfig(
                    resource_type="local", functions=[], makes_remote_calls=False
                )
            },
            resources_endpoints=None,
        )

        result = manifest.to_dict()

        assert "resources_endpoints" not in result
