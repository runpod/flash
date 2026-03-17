"""Tests for max_concurrency in manifest models and builder."""

from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from runpod_flash.cli.commands.build_utils.manifest import ManifestBuilder
from runpod_flash.cli.commands.build_utils.scanner import RemoteFunctionMetadata
from runpod_flash.runtime.models import ResourceConfig


class TestResourceConfigMaxConcurrency:
    def test_default_is_one(self):
        rc = ResourceConfig(resource_type="LiveServerless")
        assert rc.max_concurrency == 1

    def test_explicit_value(self):
        rc = ResourceConfig(resource_type="LiveServerless", max_concurrency=5)
        assert rc.max_concurrency == 5

    def test_from_dict_with_max_concurrency(self):
        data = {
            "resource_type": "LiveServerless",
            "max_concurrency": 10,
            "functions": [],
        }
        rc = ResourceConfig.from_dict(data)
        assert rc.max_concurrency == 10

    def test_from_dict_missing_field_defaults_to_one(self):
        data = {
            "resource_type": "LiveServerless",
            "functions": [],
        }
        rc = ResourceConfig.from_dict(data)
        assert rc.max_concurrency == 1

    def test_round_trip_through_dict(self):
        rc = ResourceConfig(resource_type="LiveServerless", max_concurrency=7)
        d = asdict(rc)
        assert d["max_concurrency"] == 7
        rc2 = ResourceConfig.from_dict(d)
        assert rc2.max_concurrency == 7


class TestManifestBuilderMaxConcurrency:
    def test_qb_resource_includes_max_concurrency_from_deployment_config(self):
        """QB resource with max_concurrency in deployment_config includes it in manifest."""
        func = RemoteFunctionMetadata(
            function_name="generate",
            module_path="app",
            resource_config_name="inference",
            resource_type="LiveServerless",
            is_async=True,
            is_class=False,
            is_load_balanced=False,
            is_live_resource=False,
            file_path=Path("/nonexistent/app.py"),
        )

        builder = ManifestBuilder(
            project_name="test",
            remote_functions=[func],
            build_dir=None,
        )

        with patch.object(
            builder,
            "_extract_deployment_config",
            return_value={"max_concurrency": 5},
        ):
            manifest = builder.build()

        resource = manifest["resources"]["inference"]
        assert resource["max_concurrency"] == 5

    def test_lb_resource_omits_max_concurrency_and_warns(self):
        """LB resource with max_concurrency > 1 logs warning and omits value."""
        func = RemoteFunctionMetadata(
            function_name="health",
            module_path="app",
            resource_config_name="api",
            resource_type="LiveLoadBalancer",
            is_async=True,
            is_class=False,
            is_load_balanced=True,
            is_live_resource=True,
            http_method="GET",
            http_path="/health",
            file_path=Path("/nonexistent/app.py"),
        )

        builder = ManifestBuilder(
            project_name="test",
            remote_functions=[func],
            build_dir=None,
        )

        with patch.object(
            builder,
            "_extract_deployment_config",
            return_value={"max_concurrency": 5},
        ):
            with patch(
                "runpod_flash.cli.commands.build_utils.manifest.logger"
            ) as mock_logger:
                manifest = builder.build()

        resource = manifest["resources"]["api"]
        assert "max_concurrency" not in resource
        mock_logger.warning.assert_called_once()
        assert (
            "max_concurrency=5"
            in mock_logger.warning.call_args[0][0]
            % mock_logger.warning.call_args[0][1:]
        )

    def test_qb_resource_without_max_concurrency_has_no_field(self):
        """QB resource with no max_concurrency in deployment_config omits the field."""
        func = RemoteFunctionMetadata(
            function_name="process",
            module_path="worker",
            resource_config_name="worker",
            resource_type="LiveServerless",
            is_async=True,
            is_class=False,
            is_load_balanced=False,
            is_live_resource=False,
            file_path=Path("/nonexistent/worker.py"),
        )

        builder = ManifestBuilder(
            project_name="test",
            remote_functions=[func],
            build_dir=None,
        )

        with patch.object(
            builder,
            "_extract_deployment_config",
            return_value={},
        ):
            manifest = builder.build()

        resource = manifest["resources"]["worker"]
        assert "max_concurrency" not in resource
