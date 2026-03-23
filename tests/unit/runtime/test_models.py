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


class TestResourceConfigFields:
    """Tests for is_load_balanced and is_live_resource on ResourceConfig."""

    def test_from_dict_parses_is_load_balanced(self):
        """from_dict sets is_load_balanced when present."""
        config = ResourceConfig.from_dict(
            {"resource_type": "LoadBalancerSlsResource", "is_load_balanced": True}
        )
        assert config.is_load_balanced is True

    def test_from_dict_defaults_is_load_balanced_false(self):
        """from_dict defaults is_load_balanced to False."""
        config = ResourceConfig.from_dict({"resource_type": "Serverless"})
        assert config.is_load_balanced is False

    def test_from_dict_parses_is_live_resource(self):
        """from_dict sets is_live_resource when present."""
        config = ResourceConfig.from_dict(
            {"resource_type": "LiveServerless", "is_live_resource": True}
        )
        assert config.is_live_resource is True

    def test_from_dict_defaults_is_live_resource_false(self):
        """from_dict defaults is_live_resource to False."""
        config = ResourceConfig.from_dict({"resource_type": "Serverless"})
        assert config.is_live_resource is False

    def test_from_dict_both_flags(self):
        """from_dict parses both flags together."""
        config = ResourceConfig.from_dict(
            {
                "resource_type": "LiveLoadBalancer",
                "is_load_balanced": True,
                "is_live_resource": True,
            }
        )
        assert config.is_load_balanced is True
        assert config.is_live_resource is True

    def test_from_dict_parses_pod_id(self):
        """from_dict sets pod_id when present."""
        config = ResourceConfig.from_dict(
            {"resource_type": "Pod", "pod_id": "pod-abc123"}
        )
        assert config.pod_id == "pod-abc123"

    def test_from_dict_defaults_pod_id_none(self):
        """from_dict defaults pod_id to None."""
        config = ResourceConfig.from_dict({"resource_type": "Serverless"})
        assert config.pod_id is None

    def test_from_dict_parses_pod_ports(self):
        """from_dict sets pod_ports when present."""
        config = ResourceConfig.from_dict(
            {"resource_type": "Pod", "pod_ports": ["8080/http", "22/tcp"]}
        )
        assert config.pod_ports == ["8080/http", "22/tcp"]

    def test_from_dict_defaults_pod_ports_none(self):
        """from_dict defaults pod_ports to None."""
        config = ResourceConfig.from_dict({"resource_type": "Serverless"})
        assert config.pod_ports is None

    def test_from_dict_pod_fields_roundtrip(self):
        """Manifest roundtrip preserves pod_id and pod_ports."""
        data = _make_manifest_dict(
            resources={
                "pod_res": {
                    "resource_type": "Pod",
                    "functions": [],
                    "makes_remote_calls": False,
                    "pod_id": "pod-xyz",
                    "pod_ports": ["8080/http"],
                }
            }
        )
        manifest = Manifest.from_dict(data)
        rc = manifest.resources["pod_res"]
        assert rc.pod_id == "pod-xyz"
        assert rc.pod_ports == ["8080/http"]

        roundtrip = Manifest.from_dict(manifest.to_dict())
        rc2 = roundtrip.resources["pod_res"]
        assert rc2.pod_id == "pod-xyz"
        assert rc2.pod_ports == ["8080/http"]

    def test_from_dict_parses_pod_dependencies_on_function(self):
        """from_dict parses pod_dependencies on FunctionMetadata."""
        config = ResourceConfig.from_dict(
            {
                "resource_type": "LiveServerless",
                "functions": [
                    {
                        "name": "predict",
                        "module": "app",
                        "is_async": False,
                        "is_class": False,
                        "pod_dependencies": ["redis-pod", "db-pod"],
                    }
                ],
            }
        )
        assert config.functions[0].pod_dependencies == ["redis-pod", "db-pod"]

    def test_from_dict_ignores_extra_function_fields(self):
        """from_dict filters unknown keys from function dicts."""
        config = ResourceConfig.from_dict(
            {
                "resource_type": "LiveServerless",
                "functions": [
                    {
                        "name": "predict",
                        "module": "app",
                        "is_async": False,
                        "is_class": False,
                        "is_load_balanced": True,
                        "is_live_resource": True,
                        "config_variable": "gpu_config",
                    }
                ],
            }
        )
        assert len(config.functions) == 1
        assert config.functions[0].name == "predict"
        assert not hasattr(config.functions[0], "config_variable")

    def test_manifest_roundtrip_preserves_flags(self):
        """Manifest to_dict/from_dict preserves is_load_balanced and is_live_resource."""
        data = _make_manifest_dict(
            resources={
                "lb_res": {
                    "resource_type": "LoadBalancerSlsResource",
                    "functions": [],
                    "is_load_balanced": True,
                    "is_live_resource": False,
                    "makes_remote_calls": False,
                }
            }
        )
        manifest = Manifest.from_dict(data)
        rc = manifest.resources["lb_res"]
        assert rc.is_load_balanced is True
        assert rc.is_live_resource is False

        roundtrip = Manifest.from_dict(manifest.to_dict())
        rc2 = roundtrip.resources["lb_res"]
        assert rc2.is_load_balanced is True
        assert rc2.is_live_resource is False
