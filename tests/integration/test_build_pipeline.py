"""Integration tests for the build pipeline.

Exercises: scanner → manifest → handler generation with real code paths.
Only external I/O (install_dependencies) is mocked.
"""

import ast

import pytest

from runpod_flash.cli.commands.build_utils.handler_generator import HandlerGenerator
from runpod_flash.cli.commands.build_utils.manifest import ManifestBuilder
from runpod_flash.cli.commands.build_utils.scanner import (
    RemoteDecoratorScanner,
)


@pytest.fixture()
def build_project(tmp_path):
    """Create a minimal project with @remote-decorated functions."""
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()

    # Create a .flashignore so scanner doesn't try .gitignore
    (project_dir / ".flashignore").write_text("")

    return project_dir


def _write_worker_file(project_dir, filename, content):
    """Write a Python file into the project directory."""
    filepath = project_dir / filename
    filepath.write_text(content)
    return filepath


class TestBuildProducesValidManifest:
    """Scanner → ManifestBuilder → valid manifest JSON."""

    def test_build_produces_valid_manifest(self, build_project):
        """Minimal @remote file → scanner → manifest with correct structure."""
        _write_worker_file(
            build_project,
            "worker.py",
            """\
from runpod_flash import remote, LiveServerless

gpu = LiveServerless(name="test-gpu", gpu_count=1, gpu_ids="AMPERE_48")

@remote(gpu)
def process(data):
    return sum(data)
""",
        )

        scanner = RemoteDecoratorScanner(build_project)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 1
        assert functions[0].function_name == "process"
        assert functions[0].resource_config_name == "test-gpu"

        builder = ManifestBuilder(
            project_name="test-project",
            remote_functions=functions,
            scanner=scanner,
        )
        manifest = builder.build()

        assert "version" in manifest
        assert "resources" in manifest
        assert "function_registry" in manifest
        assert "test-gpu" in manifest["resources"]

        resource = manifest["resources"]["test-gpu"]
        assert len(resource["functions"]) == 1
        assert resource["functions"][0]["name"] == "process"

    def test_build_with_multiple_resources(self, build_project):
        """File with GPU + CPU resources → both appear in manifest."""
        _write_worker_file(
            build_project,
            "worker.py",
            """\
from runpod_flash import remote, LiveServerless, CpuLiveServerless

gpu = LiveServerless(name="my-gpu", gpu_count=1, gpu_ids="AMPERE_48")
cpu = CpuLiveServerless(name="my-cpu")

@remote(gpu)
def gpu_task(x):
    return x * 2

@remote(cpu)
def cpu_task(x):
    return x + 1
""",
        )

        scanner = RemoteDecoratorScanner(build_project)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 2

        builder = ManifestBuilder(
            project_name="multi-resource",
            remote_functions=functions,
            scanner=scanner,
        )
        manifest = builder.build()

        assert "my-gpu" in manifest["resources"]
        assert "my-cpu" in manifest["resources"]
        assert len(manifest["function_registry"]) == 2


class TestBuildGeneratesHandlerFiles:
    """HandlerGenerator produces valid Python handler files."""

    def test_build_generates_handler_files(self, tmp_path):
        """HandlerGenerator produces syntactically valid handler file."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-01T00:00:00Z",
            "project_name": "test",
            "resources": {
                "test-gpu": {
                    "resource_type": "LiveServerless",
                    "is_load_balanced": False,
                    "is_live_resource": True,
                    "functions": [
                        {
                            "name": "process",
                            "module": "worker",
                            "is_async": False,
                            "is_class": False,
                        }
                    ],
                }
            },
        }

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()

        assert len(handler_paths) == 1
        handler_path = handler_paths[0]
        assert handler_path.exists()
        assert handler_path.name == "handler_test-gpu.py"

        # Verify it's valid Python
        content = handler_path.read_text()
        ast.parse(content)  # Raises SyntaxError if invalid

        # Verify it contains the function registry
        assert "FUNCTION_REGISTRY" in content
        assert "process" in content

    def test_deployed_handler_generation(self, tmp_path):
        """Deployed (non-live) resource generates deployed handler template."""
        build_dir = tmp_path / "build"
        build_dir.mkdir()

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-01T00:00:00Z",
            "project_name": "test",
            "resources": {
                "deployed-ep": {
                    "resource_type": "ServerlessEndpoint",
                    "is_load_balanced": False,
                    "is_live_resource": False,
                    "functions": [
                        {
                            "name": "inference",
                            "module": "model_worker",
                            "is_async": False,
                            "is_class": False,
                        }
                    ],
                }
            },
        }

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()

        assert len(handler_paths) == 1
        content = handler_paths[0].read_text()
        ast.parse(content)

        # Deployed handlers use inline handler() definition (not create_handler)
        assert "def handler(job):" in content
        assert "inference" in content
