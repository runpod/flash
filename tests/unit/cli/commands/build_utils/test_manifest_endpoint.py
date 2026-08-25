"""tests for ManifestBuilder with Endpoint-based metadata."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from runpod_flash.cli.commands.build_utils.manifest import ManifestBuilder
from runpod_flash.cli.commands.build_utils.scanner import RemoteFunctionMetadata


class TestManifestEndpointQB:
    """test manifest building with Endpoint QB metadata."""

    def test_qb_endpoint_resource_type(self):
        functions = [
            RemoteFunctionMetadata(
                function_name="process",
                module_path="worker",
                resource_config_name="worker",
                resource_type="Endpoint",
                is_async=True,
                is_class=False,
                file_path=Path("worker.py"),
            )
        ]
        builder = ManifestBuilder("test_app", functions)
        manifest = builder.build()

        assert manifest["resources"]["worker"]["resource_type"] == "Endpoint"
        assert manifest["resources"]["worker"]["is_load_balanced"] is False
        assert manifest["resources"]["worker"]["handler_file"] == "handler_worker.py"
        assert manifest["function_registry"]["process"] == "worker"

    def test_qb_endpoint_with_config_variable(self):
        functions = [
            RemoteFunctionMetadata(
                function_name="process",
                module_path="worker",
                resource_config_name="worker",
                resource_type="Endpoint",
                is_async=True,
                is_class=False,
                file_path=Path("worker.py"),
                config_variable=None,
            )
        ]
        builder = ManifestBuilder("test_app", functions)
        manifest = builder.build()

        # qb endpoints created via @Endpoint() dont have a config_variable
        assert manifest["resources"]["worker"]["config_variable"] is None


class TestManifestEndpointLB:
    """test manifest building with Endpoint LB metadata."""

    def test_lb_endpoint_with_routes(self):
        functions = [
            RemoteFunctionMetadata(
                function_name="health",
                module_path="api",
                resource_config_name="my-api",
                resource_type="Endpoint",
                is_async=True,
                is_class=False,
                file_path=Path("api.py"),
                http_method="GET",
                http_path="/health",
                is_load_balanced=True,
                is_live_resource=True,
                config_variable="api",
            ),
            RemoteFunctionMetadata(
                function_name="compute",
                module_path="api",
                resource_config_name="my-api",
                resource_type="Endpoint",
                is_async=True,
                is_class=False,
                file_path=Path("api.py"),
                http_method="POST",
                http_path="/compute",
                is_load_balanced=True,
                is_live_resource=True,
                config_variable="api",
            ),
        ]
        builder = ManifestBuilder("test_app", functions)
        manifest = builder.build()

        resource = manifest["resources"]["my-api"]
        assert resource["resource_type"] == "Endpoint"
        assert resource["is_load_balanced"] is True
        assert resource["config_variable"] == "api"
        assert "handler_file" not in resource
        assert len(resource["functions"]) == 2
        assert resource["functions"][0]["http_method"] == "GET"
        assert resource["functions"][0]["http_path"] == "/health"

        # routes section
        assert "routes" in manifest
        assert "GET /health" in manifest["routes"]["my-api"]
        assert "POST /compute" in manifest["routes"]["my-api"]

    def test_mixed_endpoint_and_legacy(self):
        functions = [
            RemoteFunctionMetadata(
                function_name="process",
                module_path="worker",
                resource_config_name="worker",
                resource_type="Endpoint",
                is_async=True,
                is_class=False,
                file_path=Path("worker.py"),
            ),
            RemoteFunctionMetadata(
                function_name="legacy_task",
                module_path="legacy",
                resource_config_name="legacy_config",
                resource_type="LiveServerless",
                is_async=True,
                is_class=False,
                file_path=Path("legacy.py"),
            ),
        ]
        builder = ManifestBuilder("test_app", functions)
        manifest = builder.build()

        assert len(manifest["resources"]) == 2
        assert manifest["resources"]["worker"]["resource_type"] == "Endpoint"
        assert (
            manifest["resources"]["legacy_config"]["resource_type"] == "LiveServerless"
        )


class TestExtractDeploymentConfigEndpoint:
    """test _extract_deployment_config with Endpoint objects."""

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_endpoint_unwraps_to_internal_config(self):
        """config extraction calls _build_resource_config() on Endpoint objects."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)

            resource_py = project_dir / "api.py"
            resource_py.write_text(
                "from runpod_flash.endpoint import Endpoint\n"
                "from runpod_flash.core.resources.gpu import GpuGroup\n"
                "\n"
                "api = Endpoint(\n"
                '    name="my-api",\n'
                "    gpu=GpuGroup.ADA_24,\n"
                "    workers=(1, 5),\n"
                ")\n"
            )

            functions = [
                RemoteFunctionMetadata(
                    function_name="health",
                    module_path="api",
                    resource_config_name="my-api",
                    resource_type="Endpoint",
                    is_async=True,
                    is_class=False,
                    file_path=resource_py,
                    is_load_balanced=True,
                    config_variable="api",
                )
            ]

            scanner = MagicMock()
            builder = ManifestBuilder("test_app", functions, scanner=scanner)
            config = builder._extract_deployment_config("my-api", "api", "Endpoint")

            assert config["workersMin"] == 1
            assert config["workersMax"] == 5

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "false"})
    def test_endpoint_with_image_extracts_image_name(self):
        """config extraction picks up imageName from the internal config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)

            resource_py = project_dir / "vllm.py"
            resource_py.write_text(
                "from runpod_flash.endpoint import Endpoint\n"
                "from runpod_flash.core.resources.gpu import GpuGroup\n"
                "\n"
                "vllm = Endpoint(\n"
                '    name="vllm-server",\n'
                '    image="vllm/vllm-openai:latest",\n'
                "    gpu=GpuGroup.ADA_24,\n"
                ")\n"
            )

            functions = [
                RemoteFunctionMetadata(
                    function_name="placeholder",
                    module_path="vllm",
                    resource_config_name="vllm-server",
                    resource_type="Endpoint",
                    is_async=True,
                    is_class=False,
                    file_path=resource_py,
                    config_variable="vllm",
                )
            ]

            scanner = MagicMock()
            builder = ManifestBuilder("test_app", functions, scanner=scanner)
            config = builder._extract_deployment_config(
                "vllm-server", "vllm", "Endpoint"
            )

            assert config["imageName"] == "vllm/vllm-openai:latest"

    def test_endpoint_sys_path_cleaned_up(self):
        """sys.path is restored after extracting config from an Endpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)

            resource_py = project_dir / "ep.py"
            resource_py.write_text(
                "from runpod_flash.endpoint import Endpoint\n"
                "ep = Endpoint(name='test')\n"
            )

            functions = [
                RemoteFunctionMetadata(
                    function_name="fn",
                    module_path="ep",
                    resource_config_name="test",
                    resource_type="Endpoint",
                    is_async=True,
                    is_class=False,
                    file_path=resource_py,
                    config_variable="ep",
                )
            ]

            scanner = MagicMock()
            builder = ManifestBuilder("test_app", functions, scanner=scanner)

            path_before = sys.path.copy()
            builder._extract_deployment_config("test", "ep", "Endpoint")
            assert sys.path == path_before


class TestAddClientEndpoints:
    """test manifest registration of client-mode Endpoint(image=...) objects."""

    def _build_manifest(self, project_dir: Path, files: dict) -> dict:
        for name, code in files.items():
            target = project_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code, encoding="utf-8")

        from runpod_flash.cli.commands.build_utils.scanner import RuntimeScanner

        scanner = RuntimeScanner(project_dir)
        functions = scanner.discover_remote_functions()
        builder = ManifestBuilder(
            "test_app", functions, scanner=scanner, build_dir=project_dir
        )
        return builder.build()

    def test_client_endpoint_registered_as_provisionable_resource(self):
        """a client-only project produces a function-less manifest entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = self._build_manifest(
                Path(tmpdir),
                {
                    "vllm_ep.py": (
                        "from runpod_flash import Endpoint\n"
                        "from runpod_flash.core.resources.gpu import GpuGroup\n"
                        "\n"
                        "vllm = Endpoint(\n"
                        '    name="vllm-server",\n'
                        '    image="runpod/vllm-openai:stable",\n'
                        "    gpu=GpuGroup.ADA_24,\n"
                        "    workers=(0, 3),\n"
                        '    env={"MODEL_NAME": "m"},\n'
                        ")\n"
                    ),
                },
            )

        entry = manifest["resources"]["vllm-server"]
        assert entry["client_mode"] is True
        assert entry["functions"] == []
        assert entry["is_load_balanced"] is False
        assert entry["makes_remote_calls"] is False
        assert entry["imageName"] == "runpod/vllm-openai:stable"
        assert entry["gpuIds"] == "ADA_24"
        assert entry["workersMin"] == 0
        assert entry["workersMax"] == 3
        assert entry["env"] == {"MODEL_NAME": "m"}
        assert entry["resource_type"] == "LiveServerless"
        # client endpoints never get a generated worker handler
        assert "handler_file" not in entry
        # no decorated functions exist, so the registry is empty
        assert manifest["function_registry"] == {}

    def test_cpu_client_endpoint_resource_type(self):
        """cpu client endpoints resolve to CpuLiveServerless with instanceIds."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = self._build_manifest(
                Path(tmpdir),
                {
                    "cpu_ep.py": (
                        "from runpod_flash import Endpoint\n"
                        "from runpod_flash.core.resources.cpu import CpuInstanceType\n"
                        "\n"
                        "whisper = Endpoint(\n"
                        '    name="whisper",\n'
                        '    image="runpod/whisper:latest",\n'
                        "    cpu=CpuInstanceType.CPU3G_2_8,\n"
                        ")\n"
                    ),
                },
            )

        entry = manifest["resources"]["whisper"]
        assert entry["client_mode"] is True
        assert entry["resource_type"] == "CpuLiveServerless"
        assert entry["instanceIds"] == ["cpu3g-2-8"]
        assert entry["imageName"] == "runpod/whisper:latest"

    def test_non_provisionable_class_name_falls_back_to_endpoint(self):
        """when the built config class is not provisionable (deploy-mode env),
        resource_type stays 'Endpoint' so the provisioner resolves it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "false"}):
                manifest = self._build_manifest(
                    Path(tmpdir),
                    {
                        "vllm_ep.py": (
                            "from runpod_flash import Endpoint\n"
                            "from runpod_flash.core.resources.gpu import GpuGroup\n"
                            "\n"
                            "vllm = Endpoint(\n"
                            '    name="vllm-server",\n'
                            '    image="runpod/vllm-openai:stable",\n'
                            "    gpu=GpuGroup.ADA_24,\n"
                            ")\n"
                        ),
                    },
                )

        entry = manifest["resources"]["vllm-server"]
        assert entry["resource_type"] == "Endpoint"
        # gpuIds still present so the provisioner can resolve GPU vs CPU
        assert entry["gpuIds"] == "ADA_24"
        assert entry["imageName"] == "runpod/vllm-openai:stable"

    def test_mixed_project_registers_both(self):
        """decorated resources and client endpoints coexist in one manifest."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = self._build_manifest(
                Path(tmpdir),
                {
                    "worker.py": (
                        "from runpod_flash import remote, LiveServerless\n"
                        'cfg = LiveServerless(name="worker")\n'
                        "\n"
                        "@remote(cfg)\n"
                        "def process(x):\n"
                        "    return x\n"
                    ),
                    "vllm_ep.py": (
                        "from runpod_flash import Endpoint\n"
                        "\n"
                        'vllm = Endpoint(name="vllm-server", image="img:v1")\n'
                    ),
                },
            )

        assert set(manifest["resources"]) == {"worker", "vllm-server"}
        assert manifest["resources"]["vllm-server"]["client_mode"] is True
        assert manifest["resources"]["worker"]["functions"]
        assert "client_mode" not in manifest["resources"]["worker"]
        assert manifest["function_registry"] == {"process": "worker"}

    def test_name_collision_with_decorated_resource_raises(self):
        """a client endpoint sharing a decorated resource's name is an error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="both a client-mode"):
                self._build_manifest(
                    Path(tmpdir),
                    {
                        "worker.py": (
                            "from runpod_flash import remote, LiveServerless\n"
                            'cfg = LiveServerless(name="vllm-server")\n'
                            "\n"
                            "@remote(cfg)\n"
                            "def process(x):\n"
                            "    return x\n"
                        ),
                        "vllm_ep.py": (
                            "from runpod_flash import Endpoint\n"
                            "\n"
                            'vllm = Endpoint(name="vllm-server", image="img:v1")\n'
                        ),
                    },
                )

    def test_import_failure_falls_back_to_endpoint_type(self, caplog):
        """unimportable source module keeps the entry but with a bare
        'Endpoint' type and a warning about the missing image."""
        import logging

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            bad_file = project_dir / "broken.py"
            bad_file.write_text("def broken(:\n", encoding="utf-8")

            scanner = MagicMock()
            scanner.client_endpoints = {
                "broken-ep": {
                    "var_name": "ep",
                    "file_path": bad_file,
                    "module_path": "broken",
                }
            }
            builder = ManifestBuilder("test_app", [], scanner=scanner)

            with caplog.at_level(logging.WARNING):
                manifest = builder.build()

        entry = manifest["resources"]["broken-ep"]
        assert entry["client_mode"] is True
        assert entry["resource_type"] == "Endpoint"
        assert "imageName" not in entry
        assert any(
            "Failed to extract image/template" in rec.message for rec in caplog.records
        )

    def test_no_client_endpoints_is_noop(self):
        """a scanner with no client endpoints leaves resources untouched."""
        scanner = MagicMock()
        scanner.client_endpoints = {}
        builder = ManifestBuilder("test_app", [], scanner=scanner)
        manifest = builder.build()
        assert manifest["resources"] == {}
