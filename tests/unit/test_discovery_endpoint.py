"""tests for ResourceDiscovery with Endpoint patterns."""

import os
from textwrap import dedent
from unittest.mock import patch

import pytest

from runpod_flash.core.discovery import ResourceDiscovery
from runpod_flash.core.resources.base import DeployableResource


class TestDiscoveryEndpointLB:
    """test discovery of Endpoint LB patterns (ep = Endpoint(...) + @ep.get)."""

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_discover_endpoint_lb_variable(self, tmp_path):
        entry = tmp_path / "api.py"
        entry.write_text(
            dedent("""\
                from runpod_flash.endpoint import Endpoint
                from runpod_flash.core.resources.gpu import GpuGroup

                api = Endpoint(name="my-api", gpu=GpuGroup.ADA_24, workers=(1, 3))

                @api.get("/health")
                async def health():
                    return {"status": "ok"}

                @api.post("/compute")
                async def compute(data):
                    return data
            """)
        )

        discovery = ResourceDiscovery(str(entry))
        resources = discovery.discover()

        assert len(resources) == 1
        assert isinstance(resources[0], DeployableResource)
        # the internal resource config prepends "live-" and appends "-fb"
        assert "my-api" in resources[0].name

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_discover_endpoint_lb_cpu(self, tmp_path):
        entry = tmp_path / "api.py"
        entry.write_text(
            dedent("""\
                from runpod_flash.endpoint import Endpoint
                from runpod_flash.core.resources.cpu import CpuInstanceType

                api = Endpoint(name="cpu-api", cpu=CpuInstanceType.CPU3G_2_8)

                @api.post("/process")
                async def process(data):
                    return data
            """)
        )

        discovery = ResourceDiscovery(str(entry))
        resources = discovery.discover()

        assert len(resources) == 1
        assert "cpu-api" in resources[0].name
        # should resolve to a CpuLiveLoadBalancer
        assert "Cpu" in type(resources[0]).__name__

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_discover_endpoint_lb_no_routes_not_discovered(self, tmp_path):
        """an Endpoint variable with no route decorators is not found by the
        route-based AST scan (no @ep.get/post decorators to trigger detection)."""
        entry = tmp_path / "api.py"
        entry.write_text(
            dedent("""\
                from runpod_flash.endpoint import Endpoint

                api = Endpoint(name="unused-api")
            """)
        )

        discovery = ResourceDiscovery(str(entry))
        resources = discovery.discover()

        assert resources == []


class TestDiscoveryEndpointResolve:
    """test _resolve_resource_variable with Endpoint objects."""

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_resolve_endpoint_to_deployable(self, tmp_path):
        entry = tmp_path / "worker.py"
        entry.write_text(
            dedent("""\
                from runpod_flash.endpoint import Endpoint
                from runpod_flash.core.resources.gpu import GpuGroup

                ep = Endpoint(name="worker", gpu=GpuGroup.ADA_24)

                @ep.post("/run")
                async def run(data):
                    return data
            """)
        )

        discovery = ResourceDiscovery(str(entry))
        module = discovery._import_module(entry)

        result = discovery._resolve_resource_variable(module, "ep")
        assert result is not None
        assert isinstance(result, DeployableResource)
        assert "worker" in result.name


class TestDiscoveryEndpointDirectoryScan:
    """test directory scanning fallback finds Endpoint patterns."""

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_directory_scan_finds_endpoint(self, tmp_path):
        """directory scan fallback detects files with Endpoint patterns."""
        entry = tmp_path / "main.py"
        entry.write_text("import importlib.util\n")

        workers_dir = tmp_path / "workers"
        workers_dir.mkdir()
        worker = workers_dir / "api.py"
        worker.write_text(
            dedent("""\
                from runpod_flash.endpoint import Endpoint
                from runpod_flash.core.resources.gpu import GpuGroup

                api = Endpoint(name="found-api", gpu=GpuGroup.ADA_24)

                @api.get("/health")
                async def health():
                    return {"ok": True}
            """)
        )

        discovery = ResourceDiscovery(str(entry))
        resources = discovery.discover()

        assert len(resources) == 1
        assert "found-api" in resources[0].name


class TestDiscoveryMixed:
    """test discovery with both legacy @remote and Endpoint patterns."""

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_mixed_remote_and_endpoint(self, tmp_path):
        entry = tmp_path / "main.py"
        entry.write_text(
            dedent("""\
                from runpod_flash.client import remote
                from runpod_flash.core.resources.serverless import ServerlessResource
                from runpod_flash.endpoint import Endpoint
                from runpod_flash.core.resources.gpu import GpuGroup

                legacy_config = ServerlessResource(
                    name="legacy",
                    gpuCount=1,
                    workersMax=3,
                    workersMin=0,
                    flashboot=False,
                )

                @remote(resource_config=legacy_config)
                async def legacy_task():
                    return "legacy"

                api = Endpoint(name="new-api", gpu=GpuGroup.ADA_24)

                @api.post("/process")
                async def process(data):
                    return data
            """)
        )

        discovery = ResourceDiscovery(str(entry))
        resources = discovery.discover()

        assert len(resources) == 2
        names = {r.name for r in resources}
        # internal resource configs may modify names (e.g. "live-" prefix, "-fb" suffix)
        assert any("legacy" in n for n in names)
        assert any("new-api" in n for n in names)
