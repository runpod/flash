"""Tests for flash run with the new Endpoint API patterns."""

import tempfile
from pathlib import Path

from runpod_flash.cli.commands.run import _scan_project_workers, _generate_flash_server


class TestScanEndpointWorkers:
    def test_qb_endpoint_discovered_as_qb_worker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "worker.py").write_text(
                """
from runpod_flash import Endpoint, GpuGroup

@Endpoint(name="gpu-worker", gpu=GpuGroup.ADA_24, workers=(0, 3))
async def process(data: dict) -> dict:
    return data
"""
            )

            workers = _scan_project_workers(project_root)
            assert len(workers) == 1
            w = workers[0]
            assert w.worker_type == "QB"
            assert w.functions == ["process"]
            assert w.function_params == {"process": ["data"]}

    def test_lb_endpoint_discovered_as_lb_worker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "api.py").write_text(
                """
from runpod_flash import Endpoint

api = Endpoint(name="my-api", cpu="cpu3g-2-8", workers=(1, 3))

@api.get("/health")
async def health():
    return {"status": "ok"}

@api.post("/compute")
async def compute(data: dict) -> dict:
    return data
"""
            )

            workers = _scan_project_workers(project_root)
            assert len(workers) == 1
            w = workers[0]
            assert w.worker_type == "LB"
            assert set(w.functions) == {"health", "compute"}
            assert len(w.lb_routes) == 2

            by_fn = {r["fn_name"]: r for r in w.lb_routes}
            assert by_fn["health"]["method"] == "GET"
            assert by_fn["health"]["path"] == "/health"
            assert by_fn["health"]["config_variable"] == "api"

            assert by_fn["compute"]["method"] == "POST"
            assert by_fn["compute"]["path"] == "/compute"

    def test_mixed_qb_and_lb_in_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            (project_root / "gpu_worker.py").write_text(
                """
from runpod_flash import Endpoint, GpuGroup

@Endpoint(name="gpu-worker", gpu=GpuGroup.ANY)
async def gpu_process(data: dict) -> dict:
    return data
"""
            )
            (project_root / "api.py").write_text(
                """
from runpod_flash import Endpoint

api = Endpoint(name="cpu-api", cpu="cpu3g-2-8")

@api.get("/health")
async def health():
    return {"status": "ok"}
"""
            )

            workers = _scan_project_workers(project_root)
            assert len(workers) == 2

            qb = [w for w in workers if w.worker_type == "QB"]
            lb = [w for w in workers if w.worker_type == "LB"]
            assert len(qb) == 1
            assert len(lb) == 1

    def test_endpoint_class_discovered_as_qb(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "model.py").write_text(
                """
from runpod_flash import Endpoint, GpuGroup

@Endpoint(name="model-worker", gpu=GpuGroup.ANY)
class Model:
    def __init__(self):
        pass

    async def predict(self, text: str):
        return {"label": "ok"}

    async def info(self):
        return {"model": "test"}
"""
            )

            workers = _scan_project_workers(project_root)
            assert len(workers) == 1
            w = workers[0]
            assert w.worker_type == "QB"
            assert len(w.class_remotes) == 1
            assert w.class_remotes[0]["name"] == "Model"
            assert w.class_remotes[0]["methods"] == ["predict", "info"]


class TestGenerateServerEndpoint:
    def test_qb_endpoint_generates_valid_server(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "worker.py").write_text(
                """
from runpod_flash import Endpoint

@Endpoint(name="my-worker")
async def process(data: dict) -> dict:
    return data
"""
            )

            workers = _scan_project_workers(project_root)
            server_path = _generate_flash_server(project_root, workers)

            assert server_path.exists()
            content = server_path.read_text()

            # should import the function
            assert "from worker import process" in content
            # should generate a POST route
            assert "/worker/runsync" in content

    def test_lb_endpoint_generates_valid_server(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "api.py").write_text(
                """
from runpod_flash import Endpoint

api = Endpoint(name="my-api", cpu="cpu3g-2-8")

@api.get("/health")
async def health():
    return {"status": "ok"}

@api.post("/compute")
async def compute(data: dict) -> dict:
    return data
"""
            )

            workers = _scan_project_workers(project_root)
            server_path = _generate_flash_server(project_root, workers)

            assert server_path.exists()
            content = server_path.read_text()

            # should import the endpoint variable and functions
            assert "from api import api" in content
            assert "from api import health" in content or "from api import compute" in content

            # should generate LB routes
            assert "/api/health" in content
            assert "/api/compute" in content
            assert "_lb_execute" in content

    def test_multiple_endpoints_generates_all_routes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            (project_root / "gpu_worker.py").write_text(
                """
from runpod_flash import Endpoint, GpuGroup

@Endpoint(name="gpu-worker", gpu=GpuGroup.ANY)
async def gpu_process(data: dict) -> dict:
    return data
"""
            )
            (project_root / "api.py").write_text(
                """
from runpod_flash import Endpoint

api = Endpoint(name="cpu-api", cpu="cpu3g-2-8")

@api.post("/process")
async def api_process(text: str) -> dict:
    return {"result": text}
"""
            )

            workers = _scan_project_workers(project_root)
            server_path = _generate_flash_server(project_root, workers)

            content = server_path.read_text()
            assert "/gpu_worker/runsync" in content
            assert "/api/process" in content
