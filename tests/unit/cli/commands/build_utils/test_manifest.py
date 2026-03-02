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
