"""Tests for ManifestBuilder."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from runpod_flash.cli.commands.build_utils.manifest import ManifestBuilder
from runpod_flash.cli.commands.build_utils.scanner import RemoteFunctionMetadata


def test_build_manifest_single_resource():
    """Test building manifest with single resource config."""
    functions = [
        RemoteFunctionMetadata(
            function_name="gpu_inference",
            module_path="workers.gpu",
            resource_config_name="gpu_config",
            resource_type="LiveServerless",
            is_async=True,
            is_class=False,
            file_path=Path("workers/gpu.py"),
        )
    ]

    builder = ManifestBuilder("test_app", functions)
    manifest = builder.build()

    assert manifest["version"] == "1.0"
    assert manifest["project_name"] == "test_app"
    assert "gpu_config" in manifest["resources"]
    assert len(manifest["resources"]["gpu_config"]["functions"]) == 1

    # Check function registry
    assert manifest["function_registry"]["gpu_inference"] == "gpu_config"


def test_build_manifest_multiple_resources():
    """Test building manifest with multiple resource configs."""
    functions = [
        RemoteFunctionMetadata(
            function_name="gpu_task",
            module_path="workers.gpu",
            resource_config_name="gpu_config",
            resource_type="LiveServerless",
            is_async=True,
            is_class=False,
            file_path=Path("workers/gpu.py"),
        ),
        RemoteFunctionMetadata(
            function_name="cpu_task",
            module_path="workers.cpu",
            resource_config_name="cpu_config",
            resource_type="CpuLiveServerless",
            is_async=True,
            is_class=False,
            file_path=Path("workers/cpu.py"),
        ),
    ]

    builder = ManifestBuilder("test_app", functions)
    manifest = builder.build()

    assert len(manifest["resources"]) == 2
    assert "gpu_config" in manifest["resources"]
    assert "cpu_config" in manifest["resources"]
    assert manifest["function_registry"]["gpu_task"] == "gpu_config"
    assert manifest["function_registry"]["cpu_task"] == "cpu_config"


def test_build_manifest_grouped_functions():
    """Test that functions are correctly grouped by resource config."""
    functions = [
        RemoteFunctionMetadata(
            function_name="process",
            module_path="workers.gpu",
            resource_config_name="gpu_config",
            resource_type="LiveServerless",
            is_async=True,
            is_class=False,
            file_path=Path("workers/gpu.py"),
        ),
        RemoteFunctionMetadata(
            function_name="analyze",
            module_path="workers.gpu",
            resource_config_name="gpu_config",
            resource_type="LiveServerless",
            is_async=True,
            is_class=False,
            file_path=Path("workers/gpu.py"),
        ),
    ]

    builder = ManifestBuilder("test_app", functions)
    manifest = builder.build()

    gpu_functions = manifest["resources"]["gpu_config"]["functions"]
    assert len(gpu_functions) == 2
    function_names = {f["name"] for f in gpu_functions}
    assert function_names == {"process", "analyze"}


def test_build_manifest_includes_metadata():
    """Test that manifest includes correct function metadata."""
    functions = [
        RemoteFunctionMetadata(
            function_name="async_func",
            module_path="workers.test",
            resource_config_name="config",
            resource_type="LiveServerless",
            is_async=True,
            is_class=False,
            file_path=Path("workers/test.py"),
        ),
        RemoteFunctionMetadata(
            function_name="sync_func",
            module_path="workers.test",
            resource_config_name="config",
            resource_type="LiveServerless",
            is_async=False,
            is_class=False,
            file_path=Path("workers/test.py"),
        ),
        RemoteFunctionMetadata(
            function_name="TestClass",
            module_path="workers.test",
            resource_config_name="config",
            resource_type="LiveServerless",
            is_async=False,
            is_class=True,
            file_path=Path("workers/test.py"),
        ),
    ]

    builder = ManifestBuilder("test_app", functions)
    manifest = builder.build()

    functions_list = manifest["resources"]["config"]["functions"]

    # Find each function in the list
    async_func = next(f for f in functions_list if f["name"] == "async_func")
    assert async_func["is_async"] is True
    assert async_func["is_class"] is False

    sync_func = next(f for f in functions_list if f["name"] == "sync_func")
    assert sync_func["is_async"] is False
    assert sync_func["is_class"] is False

    test_class = next(f for f in functions_list if f["name"] == "TestClass")
    assert test_class["is_class"] is True


def test_write_manifest_to_file():
    """Test writing manifest to file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "flash_manifest.json"

        functions = [
            RemoteFunctionMetadata(
                function_name="test_func",
                module_path="workers.test",
                resource_config_name="test_config",
                resource_type="LiveServerless",
                is_async=True,
                is_class=False,
                file_path=Path("workers/test.py"),
            )
        ]

        builder = ManifestBuilder("test_app", functions)
        result_path = builder.write_to_file(output_path)

        assert result_path.exists()
        assert result_path == output_path

        # Read and verify content
        with open(output_path) as f:
            manifest = json.load(f)

        assert manifest["project_name"] == "test_app"
        assert "test_config" in manifest["resources"]


def test_manifest_empty_functions():
    """Test building manifest with no functions."""
    builder = ManifestBuilder("empty_app", [])
    manifest = builder.build()

    assert manifest["version"] == "1.0"
    assert manifest["project_name"] == "empty_app"
    assert len(manifest["resources"]) == 0
    assert len(manifest["function_registry"]) == 0


def test_manifest_generated_at_timestamp():
    """Test that manifest includes generated_at timestamp."""
    functions = [
        RemoteFunctionMetadata(
            function_name="func",
            module_path="workers",
            resource_config_name="config",
            resource_type="LiveServerless",
            is_async=True,
            is_class=False,
            file_path=Path("workers.py"),
        )
    ]

    builder = ManifestBuilder("test_app", functions)
    manifest = builder.build()

    assert "generated_at" in manifest
    assert manifest["generated_at"].endswith("Z")


def test_manifest_includes_handler_file_for_qb_resources():
    """Test that QB (non-LB) resources include handler_file in manifest."""
    functions = [
        RemoteFunctionMetadata(
            function_name="gpu_inference",
            module_path="workers.gpu",
            resource_config_name="gpu_config",
            resource_type="LiveServerless",
            is_async=True,
            is_class=False,
            file_path=Path("workers/gpu.py"),
            is_load_balanced=False,
        )
    ]

    builder = ManifestBuilder("test_app", functions)
    manifest = builder.build()

    resource = manifest["resources"]["gpu_config"]
    assert resource["handler_file"] == "handler_gpu_config.py"


def test_manifest_excludes_handler_file_for_lb_resources():
    """Test that LB resources do not include handler_file in manifest."""
    functions = [
        RemoteFunctionMetadata(
            function_name="health",
            module_path="endpoint",
            resource_config_name="lb-endpoint",
            resource_type="LiveLoadBalancer",
            is_async=True,
            is_class=False,
            file_path=Path("endpoint.py"),
            http_method="GET",
            http_path="/health",
            is_load_balanced=True,
            is_live_resource=True,
            config_variable="gpu_config",
        )
    ]

    builder = ManifestBuilder("test_app", functions)
    manifest = builder.build()

    resource = manifest["resources"]["lb-endpoint"]
    assert "handler_file" not in resource


def test_manifest_handler_file_mixed_resources():
    """Test handler_file present for QB but not LB in mixed manifest."""
    functions = [
        RemoteFunctionMetadata(
            function_name="gpu_task",
            module_path="workers.gpu",
            resource_config_name="gpu_config",
            resource_type="LiveServerless",
            is_async=True,
            is_class=False,
            file_path=Path("workers/gpu.py"),
            is_load_balanced=False,
        ),
        RemoteFunctionMetadata(
            function_name="health",
            module_path="endpoint",
            resource_config_name="lb-endpoint",
            resource_type="LiveLoadBalancer",
            is_async=True,
            is_class=False,
            file_path=Path("endpoint.py"),
            http_method="GET",
            http_path="/health",
            is_load_balanced=True,
            is_live_resource=True,
            config_variable="lb_config",
        ),
    ]

    builder = ManifestBuilder("test_app", functions)
    manifest = builder.build()

    assert (
        manifest["resources"]["gpu_config"]["handler_file"] == "handler_gpu_config.py"
    )
    assert "handler_file" not in manifest["resources"]["lb-endpoint"]


def test_manifest_includes_config_variable():
    """Test that manifest includes config_variable field."""
    functions = [
        RemoteFunctionMetadata(
            function_name="health",
            module_path="endpoint",
            resource_config_name="my-endpoint",
            resource_type="LiveLoadBalancer",
            is_async=True,
            is_class=False,
            file_path=Path("endpoint.py"),
            http_method="GET",
            http_path="/health",
            is_load_balanced=True,
            is_live_resource=True,
            config_variable="gpu_config",
        )
    ]

    builder = ManifestBuilder("test-project", functions)
    manifest = builder.build()

    assert manifest["resources"]["my-endpoint"]["config_variable"] == "gpu_config"
    # config_variable is only stored at the resource level, not per-function
    assert "config_variable" not in manifest["resources"]["my-endpoint"]["functions"][0]


def test_manifest_makes_remote_calls_from_scanner_metadata():
    """Validate calls_remote_functions on metadata flows to makes_remote_calls in manifest."""
    functions = [
        RemoteFunctionMetadata(
            function_name="orchestrate",
            module_path="workers.orchestrator",
            resource_config_name="cpu_config",
            resource_type="CpuLiveServerless",
            is_async=True,
            is_class=False,
            file_path=Path("workers/orchestrator.py"),
            calls_remote_functions=True,
            called_remote_functions=["generate"],
        ),
        RemoteFunctionMetadata(
            function_name="generate",
            module_path="workers.gpu",
            resource_config_name="gpu_config",
            resource_type="LiveServerless",
            is_async=True,
            is_class=False,
            file_path=Path("workers/gpu.py"),
            calls_remote_functions=False,
        ),
    ]

    builder = ManifestBuilder("test_app", functions)
    manifest = builder.build()

    # cpu_config has a function that calls remote functions
    assert manifest["resources"]["cpu_config"]["makes_remote_calls"] is True
    # gpu_config does not
    assert manifest["resources"]["gpu_config"]["makes_remote_calls"] is False


# --- Tests for _extract_deployment_config sys.path handling ---


def test_extract_deployment_config_with_sibling_imports():
    """Extraction succeeds when resource file imports sibling modules."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Create sibling module that the resource file imports
        config_py = project_dir / "config.py"
        config_py.write_text(
            'IMAGE_NAME = "my-custom-image:latest"\nTEMPLATE_ID = "tpl_abc123"\n'
        )

        # Create resource file that imports from sibling
        pipeline_py = project_dir / "pipeline.py"
        pipeline_py.write_text(
            "from config import IMAGE_NAME, TEMPLATE_ID\n"
            "\n"
            "class gpu_config:\n"
            "    imageName = IMAGE_NAME\n"
            "    templateId = TEMPLATE_ID\n"
        )

        functions = [
            RemoteFunctionMetadata(
                function_name="run_pipeline",
                module_path="pipeline",
                resource_config_name="gpu_config",
                resource_type="LiveServerless",
                is_async=False,
                is_class=False,
                file_path=pipeline_py,
                config_variable="gpu_config",
            )
        ]

        scanner = MagicMock()
        builder = ManifestBuilder("test_app", functions, scanner=scanner)
        config = builder._extract_deployment_config(
            "gpu_config", "gpu_config", "LiveServerless"
        )

        assert config["imageName"] == "my-custom-image:latest"
        assert config["templateId"] == "tpl_abc123"


def test_extract_deployment_config_cleans_up_sys_path():
    """sys.path is restored after extraction, both on success and failure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Simple resource file (no sibling imports needed)
        resource_py = project_dir / "resource.py"
        resource_py.write_text('class gpu_config:\n    imageName = "test-image"\n')

        functions = [
            RemoteFunctionMetadata(
                function_name="my_func",
                module_path="resource",
                resource_config_name="gpu_config",
                resource_type="LiveServerless",
                is_async=False,
                is_class=False,
                file_path=resource_py,
                config_variable="gpu_config",
            )
        ]

        scanner = MagicMock()
        builder = ManifestBuilder("test_app", functions, scanner=scanner)

        path_before = sys.path.copy()
        builder._extract_deployment_config("gpu_config", "gpu_config", "LiveServerless")
        assert sys.path == path_before

        # Failure case: resource file with an import that raises
        bad_py = project_dir / "bad_resource.py"
        bad_py.write_text("from nonexistent_sibling import something\n")

        functions_bad = [
            RemoteFunctionMetadata(
                function_name="bad_func",
                module_path="bad_resource",
                resource_config_name="bad_config",
                resource_type="LiveServerless",
                is_async=False,
                is_class=False,
                file_path=bad_py,
                config_variable="bad_config",
            )
        ]

        builder_bad = ManifestBuilder("test_app", functions_bad, scanner=scanner)

        path_before = sys.path.copy()
        # Should not raise — failure is caught and logged
        builder_bad._extract_deployment_config(
            "bad_config", "bad_config", "LiveServerless"
        )
        assert sys.path == path_before


def test_extract_deployment_config_includes_env_without_api_key():
    """Resource env is extracted and RUNPOD_API_KEY is excluded."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        resource_py = project_dir / "resource.py"
        resource_py.write_text(
            "class gpu_config:\n"
            '    imageName = "test-image"\n'
            '    env = {"APP_MODE": "prod", "RUNPOD_API_KEY": "secret"}\n'
        )

        functions = [
            RemoteFunctionMetadata(
                function_name="my_func",
                module_path="resource",
                resource_config_name="gpu_config",
                resource_type="LiveServerless",
                is_async=False,
                is_class=False,
                file_path=resource_py,
                config_variable="gpu_config",
            )
        ]

        scanner = MagicMock()
        builder = ManifestBuilder("test_app", functions, scanner=scanner)
        config = builder._extract_deployment_config(
            "gpu_config", "gpu_config", "LiveServerless"
        )

        assert config["env"]["APP_MODE"] == "prod"
        assert "RUNPOD_API_KEY" not in config["env"]


# --- Tests for networkVolume extraction ---


def test_extract_deployment_config_includes_network_volume():
    """networkVolume fields are extracted from resource config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        resource_py = project_dir / "resource.py"
        resource_py.write_text(
            "from runpod_flash import NetworkVolume\n"
            "from runpod_flash.core.resources.network_volume import DataCenter\n"
            "\n"
            "class gpu_config:\n"
            '    imageName = "test-image"\n'
            "    networkVolume = NetworkVolume(\n"
            '        name="my-volume",\n'
            "        size=200,\n"
            "        dataCenterId=DataCenter.EU_RO_1,\n"
            "    )\n"
        )

        functions = [
            RemoteFunctionMetadata(
                function_name="my_func",
                module_path="resource",
                resource_config_name="gpu_config",
                resource_type="LiveServerless",
                is_async=False,
                is_class=False,
                file_path=resource_py,
                config_variable="gpu_config",
            )
        ]

        scanner = MagicMock()
        builder = ManifestBuilder("test_app", functions, scanner=scanner)
        config = builder._extract_deployment_config(
            "gpu_config", "gpu_config", "LiveServerless"
        )

        assert "networkVolume" in config
        assert config["networkVolume"]["name"] == "my-volume"
        assert config["networkVolume"]["size"] == 200
        assert config["networkVolume"]["dataCenterId"] == "EU-RO-1"


def test_extract_deployment_config_includes_network_volume_id():
    """networkVolumeId is extracted when set directly on resource config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        resource_py = project_dir / "resource.py"
        resource_py.write_text(
            "class gpu_config:\n"
            '    imageName = "test-image"\n'
            '    networkVolumeId = "vol_abc123"\n'
        )

        functions = [
            RemoteFunctionMetadata(
                function_name="my_func",
                module_path="resource",
                resource_config_name="gpu_config",
                resource_type="LiveServerless",
                is_async=False,
                is_class=False,
                file_path=resource_py,
                config_variable="gpu_config",
            )
        ]

        scanner = MagicMock()
        builder = ManifestBuilder("test_app", functions, scanner=scanner)
        config = builder._extract_deployment_config(
            "gpu_config", "gpu_config", "LiveServerless"
        )

        assert config["networkVolumeId"] == "vol_abc123"
        assert "networkVolume" not in config


def test_extract_deployment_config_network_volume_minimal():
    """networkVolume with only name populates Pydantic defaults for size and dataCenterId."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        resource_py = project_dir / "resource.py"
        resource_py.write_text(
            "from runpod_flash import NetworkVolume\n"
            "\n"
            "class gpu_config:\n"
            '    imageName = "test-image"\n'
            '    networkVolume = NetworkVolume(name="minimal-vol")\n'
        )

        functions = [
            RemoteFunctionMetadata(
                function_name="my_func",
                module_path="resource",
                resource_config_name="gpu_config",
                resource_type="LiveServerless",
                is_async=False,
                is_class=False,
                file_path=resource_py,
                config_variable="gpu_config",
            )
        ]

        scanner = MagicMock()
        builder = ManifestBuilder("test_app", functions, scanner=scanner)
        config = builder._extract_deployment_config(
            "gpu_config", "gpu_config", "LiveServerless"
        )

        assert config["networkVolume"]["name"] == "minimal-vol"
        # Default size and dataCenterId should still be present
        assert config["networkVolume"]["size"] == 100
        assert config["networkVolume"]["dataCenterId"] == "EU-RO-1"


def test_extract_deployment_config_includes_network_volumes():
    """networkVolumes list is extracted from resource config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        resource_py = project_dir / "resource.py"
        resource_py.write_text(
            "from runpod_flash import NetworkVolume\n"
            "from runpod_flash.core.resources.network_volume import DataCenter\n"
            "\n"
            "class gpu_config:\n"
            '    imageName = "test-image"\n'
            "    networkVolumes = [\n"
            "        NetworkVolume(\n"
            '            name="vol-eu",\n'
            "            size=100,\n"
            "            dataCenterId=DataCenter.EU_RO_1,\n"
            "        ),\n"
            "        NetworkVolume(\n"
            '            name="vol-us",\n'
            "            size=200,\n"
            "            dataCenterId=DataCenter.US_GA_2,\n"
            "        ),\n"
            "    ]\n"
        )

        functions = [
            RemoteFunctionMetadata(
                function_name="my_func",
                module_path="resource",
                resource_config_name="gpu_config",
                resource_type="LiveServerless",
                is_async=False,
                is_class=False,
                file_path=resource_py,
                config_variable="gpu_config",
            )
        ]

        scanner = MagicMock()
        builder = ManifestBuilder("test_app", functions, scanner=scanner)
        config = builder._extract_deployment_config(
            "gpu_config", "gpu_config", "LiveServerless"
        )

        assert "networkVolumes" in config
        assert len(config["networkVolumes"]) == 2
        assert config["networkVolumes"][0]["name"] == "vol-eu"
        assert config["networkVolumes"][0]["dataCenterId"] == "EU-RO-1"
        assert config["networkVolumes"][1]["name"] == "vol-us"
        assert config["networkVolumes"][1]["size"] == 200
        assert config["networkVolumes"][1]["dataCenterId"] == "US-GA-2"
        assert "networkVolume" not in config


def test_extract_deployment_config_network_volumes_id_only():
    """networkVolumes with id-only volumes are serialized correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        resource_py = project_dir / "resource.py"
        resource_py.write_text(
            "from runpod_flash import NetworkVolume\n"
            "\n"
            "class gpu_config:\n"
            '    imageName = "test-image"\n'
            '    networkVolumes = [NetworkVolume(id="vol_abc123")]\n'
        )

        functions = [
            RemoteFunctionMetadata(
                function_name="my_func",
                module_path="resource",
                resource_config_name="gpu_config",
                resource_type="LiveServerless",
                is_async=False,
                is_class=False,
                file_path=resource_py,
                config_variable="gpu_config",
            )
        ]

        scanner = MagicMock()
        builder = ManifestBuilder("test_app", functions, scanner=scanner)
        config = builder._extract_deployment_config(
            "gpu_config", "gpu_config", "LiveServerless"
        )

        assert "networkVolumes" in config
        assert len(config["networkVolumes"]) == 1
        assert config["networkVolumes"][0]["id"] == "vol_abc123"


# --- Tests for inline @Endpoint() deployment config extraction ---


def test_extract_deployment_config_same_variable_name_different_files():
    """Config extraction uses resource_config_name, not config_variable, to find the file.

    When multiple files use the same variable name (e.g. both use ``api``),
    each resource must resolve to its own file.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        cpu_py = Path(tmpdir) / "cpu_lb.py"
        cpu_py.write_text(
            "from runpod_flash import Endpoint\n"
            "\n"
            "api = Endpoint(name='my_cpu', cpu='cpu3c-1-2')\n"
            "\n"
            "@api.post('/process')\n"
            "async def process(data: dict) -> dict:\n"
            "    return data\n"
        )

        gpu_py = Path(tmpdir) / "gpu_lb.py"
        gpu_py.write_text(
            "from runpod_flash import Endpoint, GpuGroup\n"
            "\n"
            "api = Endpoint(name='my_gpu', gpu=GpuGroup.ADA_24, workers=(1, 3))\n"
            "\n"
            "@api.post('/compute')\n"
            "async def compute(data: dict) -> dict:\n"
            "    return data\n"
        )

        functions = [
            RemoteFunctionMetadata(
                function_name="process",
                module_path="cpu_lb",
                resource_config_name="my_cpu",
                resource_type="Endpoint",
                is_async=True,
                is_class=False,
                file_path=cpu_py,
                config_variable="api",
                is_load_balanced=True,
                http_method="POST",
                http_path="/process",
            ),
            RemoteFunctionMetadata(
                function_name="compute",
                module_path="gpu_lb",
                resource_config_name="my_gpu",
                resource_type="Endpoint",
                is_async=True,
                is_class=False,
                file_path=gpu_py,
                config_variable="api",
                is_load_balanced=True,
                http_method="POST",
                http_path="/compute",
            ),
        ]

        scanner = MagicMock()
        builder = ManifestBuilder("test_app", functions, scanner=scanner)

        cpu_config = builder._extract_deployment_config("my_cpu", "api", "Endpoint")
        gpu_config = builder._extract_deployment_config("my_gpu", "api", "Endpoint")

        # cpu endpoint should get cpu config
        assert cpu_config.get("instanceIds") == ["cpu3c-1-2"]
        assert not cpu_config.get("gpuIds")

        # gpu endpoint should get gpu config, not the cpu one
        assert gpu_config.get("gpuIds") == "ADA_24"
        assert not gpu_config.get("instanceIds")
        assert gpu_config["workersMin"] == 1
        assert gpu_config["workersMax"] == 3


def test_extract_deployment_config_inline_cpu_instance():
    """Import-based extraction reads cpu= from inline @Endpoint decorator."""
    with tempfile.TemporaryDirectory() as tmpdir:
        worker_py = Path(tmpdir) / "worker.py"
        worker_py.write_text(
            "from runpod_flash import Endpoint, CpuInstanceType\n"
            "\n"
            "@Endpoint(name='cpu-worker', cpu=CpuInstanceType.CPU3C_1_2)\n"
            "async def handler(data: dict) -> dict:\n"
            "    return data\n"
        )

        functions = [
            RemoteFunctionMetadata(
                function_name="handler",
                module_path="worker",
                resource_config_name="cpu-worker",
                resource_type="Endpoint",
                is_async=True,
                is_class=False,
                file_path=worker_py,
                config_variable=None,
            )
        ]

        scanner = MagicMock()
        builder = ManifestBuilder("test_app", functions, scanner=scanner)
        config = builder._extract_deployment_config("cpu-worker", None, "Endpoint")

        assert config["instanceIds"] == ["cpu3c-1-2"]
        assert "gpuIds" not in config or not config.get("gpuIds")


def test_extract_deployment_config_inline_gpu():
    """Import-based extraction reads gpu= from inline @Endpoint decorator."""
    with tempfile.TemporaryDirectory() as tmpdir:
        worker_py = Path(tmpdir) / "worker.py"
        worker_py.write_text(
            "from runpod_flash import Endpoint, GpuGroup\n"
            "\n"
            "@Endpoint(name='gpu-worker', gpu=GpuGroup.ADA_24)\n"
            "async def handler(data: dict) -> dict:\n"
            "    return data\n"
        )

        functions = [
            RemoteFunctionMetadata(
                function_name="handler",
                module_path="worker",
                resource_config_name="gpu-worker",
                resource_type="Endpoint",
                is_async=True,
                is_class=False,
                file_path=worker_py,
                config_variable=None,
            )
        ]

        scanner = MagicMock()
        builder = ManifestBuilder("test_app", functions, scanner=scanner)
        config = builder._extract_deployment_config("gpu-worker", None, "Endpoint")

        assert config["gpuIds"] == "ADA_24"


def test_extract_deployment_config_inline_gpu_any_expands():
    """GpuGroup.ANY expands to all concrete GPU groups."""
    from runpod_flash.core.resources.gpu import GpuGroup

    with tempfile.TemporaryDirectory() as tmpdir:
        worker_py = Path(tmpdir) / "worker.py"
        worker_py.write_text(
            "from runpod_flash import Endpoint, GpuGroup\n"
            "\n"
            "@Endpoint(name='any-gpu', gpu=GpuGroup.ANY)\n"
            "async def handler(data: dict) -> dict:\n"
            "    return data\n"
        )

        functions = [
            RemoteFunctionMetadata(
                function_name="handler",
                module_path="worker",
                resource_config_name="any-gpu",
                resource_type="Endpoint",
                is_async=True,
                is_class=False,
                file_path=worker_py,
                config_variable=None,
            )
        ]

        scanner = MagicMock()
        builder = ManifestBuilder("test_app", functions, scanner=scanner)
        config = builder._extract_deployment_config("any-gpu", None, "Endpoint")

        # ANY should expand to all GPU groups, not the literal "any"
        assert "any" not in config["gpuIds"].lower()
        for g in GpuGroup.all():
            assert g.value in config["gpuIds"]


def test_extract_deployment_config_inline_workers():
    """Import-based extraction reads workers= from inline @Endpoint decorator."""
    with tempfile.TemporaryDirectory() as tmpdir:
        worker_py = Path(tmpdir) / "worker.py"
        worker_py.write_text(
            "from runpod_flash import Endpoint, GpuGroup\n"
            "\n"
            "@Endpoint(name='scaled', gpu=GpuGroup.ANY, workers=(1, 5))\n"
            "async def handler(data: dict) -> dict:\n"
            "    return data\n"
        )

        functions = [
            RemoteFunctionMetadata(
                function_name="handler",
                module_path="worker",
                resource_config_name="scaled",
                resource_type="Endpoint",
                is_async=True,
                is_class=False,
                file_path=worker_py,
                config_variable=None,
            )
        ]

        scanner = MagicMock()
        builder = ManifestBuilder("test_app", functions, scanner=scanner)
        config = builder._extract_deployment_config("scaled", None, "Endpoint")

        assert config["workersMin"] == 1
        assert config["workersMax"] == 5


def test_manifest_includes_python_version():
    """Manifest should record the Python version used at build time."""
    functions = [
        RemoteFunctionMetadata(
            function_name="gpu_inference",
            module_path="workers.gpu",
            resource_config_name="gpu_config",
            resource_type="LiveServerless",
            is_async=True,
            is_class=False,
            file_path=Path("workers/gpu.py"),
        )
    ]

    builder = ManifestBuilder("test_app", functions)
    manifest = builder.build()

    assert "python_version" in manifest
    import sys

    expected = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert manifest["python_version"] == expected


def test_manifest_uses_explicit_python_version():
    """Manifest should use the explicitly passed python_version over sys.version_info."""
    functions = [
        RemoteFunctionMetadata(
            function_name="gpu_inference",
            module_path="workers.gpu",
            resource_config_name="gpu_config",
            resource_type="LiveServerless",
            is_async=True,
            is_class=False,
            file_path=Path("workers/gpu.py"),
        )
    ]

    builder = ManifestBuilder("test_app", functions, python_version="3.12")
    manifest = builder.build()

    assert manifest["python_version"] == "3.12"
