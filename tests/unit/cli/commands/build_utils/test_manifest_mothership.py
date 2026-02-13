"""Tests for mothership resource creation in manifest."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from runpod_flash.cli.commands.build_utils.manifest import ManifestBuilder
from runpod_flash.cli.commands.build_utils.scanner import RemoteFunctionMetadata
from runpod_flash.core.resources.constants import (
    FLASH_CPU_LB_IMAGE,
    FLASH_LB_IMAGE,
)


class TestManifestMothership:
    """Test mothership resource creation in manifest."""

    def test_manifest_includes_mothership_with_main_py(self):
        """Test mothership resource added to manifest when main.py detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create main.py with FastAPI routes
            main_file = project_root / "main.py"
            main_file.write_text(
                """
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"msg": "Hello"}
"""
            )

            # Create a simple function file
            func_file = project_root / "functions.py"
            func_file.write_text(
                """
from runpod_flash import remote
from runpod_flash import LiveServerless

gpu_config = LiveServerless(name="gpu_worker")

@remote(resource_config=gpu_config)
def process(data):
    return data
"""
            )

            # Change to project directory for detection
            with patch(
                "runpod_flash.cli.commands.build_utils.manifest.Path.cwd",
                return_value=project_root,
            ):
                builder = ManifestBuilder(
                    project_name="test",
                    remote_functions=[],
                )
                manifest = builder.build()

                # Check mothership is in resources
                assert "mothership" in manifest["resources"]
                mothership = manifest["resources"]["mothership"]
                assert mothership["is_mothership"] is True
                assert mothership["main_file"] == "main.py"
                assert mothership["app_variable"] == "app"
                assert mothership["resource_type"] == "CpuLiveLoadBalancer"
                assert mothership["imageName"] == FLASH_CPU_LB_IMAGE

    def test_manifest_skips_mothership_without_routes(self):
        """Test mothership NOT added if main.py has no routes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create main.py without routes
            main_file = project_root / "main.py"
            main_file.write_text(
                """
from fastapi import FastAPI
app = FastAPI()
# No routes defined
"""
            )

            with patch(
                "runpod_flash.cli.commands.build_utils.manifest.Path.cwd",
                return_value=project_root,
            ):
                builder = ManifestBuilder(project_name="test", remote_functions=[])
                manifest = builder.build()

                # Mothership should NOT be in resources
                assert "mothership" not in manifest["resources"]

    def test_manifest_skips_mothership_without_main_py(self):
        """Test mothership NOT added if no main.py exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            with patch(
                "runpod_flash.cli.commands.build_utils.manifest.Path.cwd",
                return_value=project_root,
            ):
                builder = ManifestBuilder(project_name="test", remote_functions=[])
                manifest = builder.build()

                # Mothership should NOT be in resources
                assert "mothership" not in manifest["resources"]

    def test_manifest_handles_mothership_name_conflict(self):
        """Test mothership uses alternate name if conflict with @remote resource."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create main.py with routes
            main_file = project_root / "main.py"
            main_file.write_text(
                """
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"msg": "Hello"}
"""
            )

            # Create a remote function with name "mothership" (conflict)
            func_file = project_root / "functions.py"
            func_file.write_text(
                """
from runpod_flash import remote
from runpod_flash import LiveServerless

mothership_config = LiveServerless(name="mothership")

@remote(resource_config=mothership_config)
def process(data):
    return data
"""
            )

            # Create remote function metadata with resource named "mothership"
            remote_func = RemoteFunctionMetadata(
                function_name="process",
                module_path="functions",
                resource_config_name="mothership",
                resource_type="LiveServerless",
                is_async=False,
                is_class=False,
                file_path=func_file,
            )

            with patch(
                "runpod_flash.cli.commands.build_utils.manifest.Path.cwd",
                return_value=project_root,
            ):
                builder = ManifestBuilder(
                    project_name="test", remote_functions=[remote_func]
                )
                manifest = builder.build()

                # Original mothership should be in resources
                assert "mothership" in manifest["resources"]
                # Auto-generated mothership should use alternate name
                assert "mothership-entrypoint" in manifest["resources"]
                entrypoint = manifest["resources"]["mothership-entrypoint"]
                assert entrypoint["is_mothership"] is True

    def test_mothership_resource_config(self):
        """Test mothership resource has correct configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            main_file = project_root / "main.py"
            main_file.write_text(
                """
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"msg": "Hello"}
"""
            )

            with patch(
                "runpod_flash.cli.commands.build_utils.manifest.Path.cwd",
                return_value=project_root,
            ):
                builder = ManifestBuilder(project_name="test", remote_functions=[])
                manifest = builder.build()

                mothership = manifest["resources"]["mothership"]

                # Check all expected fields
                assert mothership["resource_type"] == "CpuLiveLoadBalancer"
                # Functions should include the FastAPI route
                assert len(mothership["functions"]) == 1
                assert mothership["functions"][0]["name"] == "root"
                assert mothership["functions"][0]["http_method"] == "GET"
                assert mothership["functions"][0]["http_path"] == "/"
                assert mothership["is_load_balanced"] is True
                assert mothership["is_live_resource"] is True
                assert mothership["imageName"] == FLASH_CPU_LB_IMAGE
                assert mothership["workersMin"] == 1
                assert mothership["workersMax"] == 1

    def test_manifest_uses_explicit_mothership_config(self):
        """Test explicit mothership.py config takes precedence over auto-detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create main.py with FastAPI routes
            main_file = project_root / "main.py"
            main_file.write_text(
                """
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"msg": "Hello"}
"""
            )

            # Create explicit mothership.py with custom config
            mothership_file = project_root / "mothership.py"
            mothership_file.write_text(
                """
from runpod_flash import CpuLiveLoadBalancer

mothership = CpuLiveLoadBalancer(
    name="my-api",
    workersMin=3,
    workersMax=7,
)
"""
            )

            with patch(
                "runpod_flash.cli.commands.build_utils.manifest.Path.cwd",
                return_value=project_root,
            ):
                builder = ManifestBuilder(project_name="test", remote_functions=[])
                manifest = builder.build()

                # Check explicit config is used
                assert "my-api" in manifest["resources"]
                mothership = manifest["resources"]["my-api"]
                assert mothership["is_explicit"] is True
                assert mothership["workersMin"] == 3
                assert mothership["workersMax"] == 7

    def test_manifest_skips_auto_detect_with_explicit_config(self):
        """Test auto-detection is skipped when explicit config exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create main.py with FastAPI routes
            main_file = project_root / "main.py"
            main_file.write_text(
                """
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"msg": "Hello"}
"""
            )

            # Create explicit mothership.py
            mothership_file = project_root / "mothership.py"
            mothership_file.write_text(
                """
from runpod_flash import CpuLiveLoadBalancer

mothership = CpuLiveLoadBalancer(
    name="explicit-mothership",
    workersMin=2,
    workersMax=4,
)
"""
            )

            with patch(
                "runpod_flash.cli.commands.build_utils.manifest.Path.cwd",
                return_value=project_root,
            ):
                builder = ManifestBuilder(project_name="test", remote_functions=[])
                manifest = builder.build()

                # Check only explicit config is in resources (not auto-detected "mothership")
                assert "explicit-mothership" in manifest["resources"]
                assert (
                    manifest["resources"]["explicit-mothership"]["is_explicit"] is True
                )
                assert "mothership" not in manifest["resources"]

    def test_manifest_handles_explicit_mothership_name_conflict(self):
        """Test explicit mothership uses alternate name if conflict with @remote."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create explicit mothership.py with name that conflicts with resource
            mothership_file = project_root / "mothership.py"
            mothership_file.write_text(
                """
from runpod_flash import CpuLiveLoadBalancer

mothership = CpuLiveLoadBalancer(
    name="api",  # Will conflict with @remote resource named "api"
    workersMin=1,
    workersMax=3,
)
"""
            )

            # Create a remote function with name "api" (conflict)
            func_file = project_root / "functions.py"
            func_file.write_text(
                """
from runpod_flash import remote
from runpod_flash import LiveServerless

api_config = LiveServerless(name="api")

@remote(resource_config=api_config)
def process(data):
    return data
"""
            )

            remote_func = RemoteFunctionMetadata(
                function_name="process",
                module_path="functions",
                resource_config_name="api",
                resource_type="LiveServerless",
                is_async=False,
                is_class=False,
                file_path=func_file,
            )

            with patch(
                "runpod_flash.cli.commands.build_utils.manifest.Path.cwd",
                return_value=project_root,
            ):
                builder = ManifestBuilder(
                    project_name="test", remote_functions=[remote_func]
                )
                manifest = builder.build()

                # Original resource should be in resources
                assert "api" in manifest["resources"]
                # Explicit mothership should use alternate name
                assert "mothership-entrypoint" in manifest["resources"]
                entrypoint = manifest["resources"]["mothership-entrypoint"]
                assert entrypoint["is_explicit"] is True

    def test_manifest_explicit_mothership_with_gpu_load_balancer(self):
        """Test explicit GPU-based load balancer config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create explicit mothership.py with GPU load balancer
            mothership_file = project_root / "mothership.py"
            mothership_file.write_text(
                """
from runpod_flash import LiveLoadBalancer

mothership = LiveLoadBalancer(
    name="gpu-mothership",
    workersMin=1,
    workersMax=2,
)
"""
            )

            # Create main.py for FastAPI app
            main_file = project_root / "main.py"
            main_file.write_text(
                """
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"msg": "Hello"}
"""
            )

            with patch(
                "runpod_flash.cli.commands.build_utils.manifest.Path.cwd",
                return_value=project_root,
            ):
                builder = ManifestBuilder(project_name="test", remote_functions=[])
                manifest = builder.build()

                mothership = manifest["resources"]["gpu-mothership"]
                assert mothership["resource_type"] == "LiveLoadBalancer"
                assert mothership["imageName"] == FLASH_LB_IMAGE
                assert mothership["is_explicit"] is True
