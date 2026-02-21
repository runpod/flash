"""Tests for flash run dev server generation."""

import tempfile
from pathlib import Path

from runpod_flash.cli.commands.run import (
    WorkerInfo,
    _generate_flash_server,
    _scan_project_workers,
)


def test_scan_separates_classes_from_functions():
    """Test that _scan_project_workers puts classes in class_remotes, not functions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        worker_file = project_root / "gpu_worker.py"
        worker_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="gpu_worker")

@remote(config)
async def process(data):
    return data

@remote(config)
class SimpleSD:
    def generate_image(self, prompt):
        return {"image": "data"}

    def upscale(self, image):
        return {"image": "upscaled"}
"""
        )

        workers = _scan_project_workers(project_root)

        assert len(workers) == 1
        worker = workers[0]
        assert worker.worker_type == "QB"
        assert worker.functions == ["process"]
        assert len(worker.class_remotes) == 1
        assert worker.class_remotes[0]["name"] == "SimpleSD"
        assert worker.class_remotes[0]["methods"] == ["generate_image", "upscale"]


def test_scan_class_only_worker():
    """Test scanning a file with only a class-based @remote."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        worker_file = project_root / "sd_worker.py"
        worker_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="sd_worker")

@remote(config)
class StableDiffusion:
    def __init__(self):
        self.model = None

    def generate(self, prompt):
        return {"image": "data"}
"""
        )

        workers = _scan_project_workers(project_root)

        assert len(workers) == 1
        worker = workers[0]
        assert worker.worker_type == "QB"
        assert worker.functions == []
        assert len(worker.class_remotes) == 1
        assert worker.class_remotes[0]["name"] == "StableDiffusion"
        assert worker.class_remotes[0]["methods"] == ["generate"]


def test_codegen_class_single_method():
    """Test generated server.py for a class with a single method uses short URL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        workers = [
            WorkerInfo(
                file_path=Path("sd_worker.py"),
                url_prefix="/sd_worker",
                module_path="sd_worker",
                resource_name="sd_worker",
                worker_type="QB",
                functions=[],
                class_remotes=[
                    {
                        "name": "StableDiffusion",
                        "methods": ["generate"],
                        "method_params": {"generate": ["prompt"]},
                    },
                ],
            ),
        ]

        server_path = _generate_flash_server(project_root, workers)
        content = server_path.read_text()

        assert "_instance_StableDiffusion = StableDiffusion()" in content
        assert (
            "_call_with_body(_instance_StableDiffusion.generate, body.input)" in content
        )
        assert "body: _sd_worker_StableDiffusion_generate_Request" in content
        assert "_make_input_model" in content
        assert "_make_wrapped_model" in content
        assert '"/sd_worker/runsync"' in content
        # Single method: no method name in URL
        assert '"/sd_worker/generate/runsync"' not in content


def test_codegen_class_multiple_methods():
    """Test generated server.py for a class with multiple methods uses method URLs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        workers = [
            WorkerInfo(
                file_path=Path("gpu_worker.py"),
                url_prefix="/gpu_worker",
                module_path="gpu_worker",
                resource_name="gpu_worker",
                worker_type="QB",
                functions=[],
                class_remotes=[
                    {
                        "name": "SimpleSD",
                        "methods": ["generate_image", "upscale"],
                        "method_params": {
                            "generate_image": ["prompt"],
                            "upscale": ["image"],
                        },
                    },
                ],
            ),
        ]

        server_path = _generate_flash_server(project_root, workers)
        content = server_path.read_text()

        assert "_instance_SimpleSD = SimpleSD()" in content
        assert '"/gpu_worker/generate_image/runsync"' in content
        assert '"/gpu_worker/upscale/runsync"' in content
        assert (
            "_call_with_body(_instance_SimpleSD.generate_image, body.input)" in content
        )
        assert "_call_with_body(_instance_SimpleSD.upscale, body.input)" in content
        assert "body: _gpu_worker_SimpleSD_generate_image_Request" in content
        assert "body: _gpu_worker_SimpleSD_upscale_Request" in content


def test_codegen_mixed_function_and_class():
    """Test codegen when a worker has both functions and class remotes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        workers = [
            WorkerInfo(
                file_path=Path("worker.py"),
                url_prefix="/worker",
                module_path="worker",
                resource_name="worker",
                worker_type="QB",
                functions=["process"],
                class_remotes=[
                    {
                        "name": "MyModel",
                        "methods": ["predict"],
                        "method_params": {"predict": ["data"]},
                    },
                ],
            ),
        ]

        server_path = _generate_flash_server(project_root, workers)
        content = server_path.read_text()

        # Both should use multi-callable URL pattern (total_callables = 2)
        assert '"/worker/process/runsync"' in content
        assert '"/worker/predict/runsync"' in content
        assert "_instance_MyModel = MyModel()" in content
        assert "_call_with_body(_instance_MyModel.predict, body.input)" in content
        assert "_call_with_body(process, body.input)" in content


def test_codegen_function_only():
    """Test that function-only workers use Pydantic model and _call_with_body."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        workers = [
            WorkerInfo(
                file_path=Path("simple.py"),
                url_prefix="/simple",
                module_path="simple",
                resource_name="simple",
                worker_type="QB",
                functions=["process"],
            ),
        ]

        server_path = _generate_flash_server(project_root, workers)
        content = server_path.read_text()

        # Single function: short URL
        assert '"/simple/runsync"' in content
        assert "_call_with_body(process, body.input)" in content
        assert "_simple_process_Input = _make_input_model(" in content
        assert "_simple_process_Request = _make_wrapped_model(" in content
        assert "body: _simple_process_Request" in content
        # No instance creation
        assert "_instance_" not in content


def test_codegen_zero_param_function():
    """Test generated code uses await fn() for zero-param functions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        workers = [
            WorkerInfo(
                file_path=Path("worker.py"),
                url_prefix="/worker",
                module_path="worker",
                resource_name="worker",
                worker_type="QB",
                functions=["list_images"],
                function_params={"list_images": []},
            ),
        ]

        server_path = _generate_flash_server(project_root, workers)
        content = server_path.read_text()

        assert "await list_images()" in content
        assert 'body.get("input"' not in content
        # Handler should not accept body parameter
        assert "async def worker_runsync():" in content


def test_codegen_multi_param_function():
    """Test generated code uses _call_with_body for multi-param functions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        workers = [
            WorkerInfo(
                file_path=Path("worker.py"),
                url_prefix="/worker",
                module_path="worker",
                resource_name="worker",
                worker_type="QB",
                functions=["transform"],
                function_params={"transform": ["text", "operation"]},
            ),
        ]

        server_path = _generate_flash_server(project_root, workers)
        content = server_path.read_text()

        assert "_call_with_body(transform, body.input)" in content
        assert "_worker_transform_Input = _make_input_model(" in content
        assert "_worker_transform_Request = _make_wrapped_model(" in content
        assert "body: _worker_transform_Request" in content


def test_codegen_single_param_function():
    """Test generated code uses _call_with_body for single-param functions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        workers = [
            WorkerInfo(
                file_path=Path("worker.py"),
                url_prefix="/worker",
                module_path="worker",
                resource_name="worker",
                worker_type="QB",
                functions=["process"],
                function_params={"process": ["data"]},
            ),
        ]

        server_path = _generate_flash_server(project_root, workers)
        content = server_path.read_text()

        assert "_call_with_body(process, body.input)" in content
        assert "body: _worker_process_Request" in content


def test_codegen_zero_param_class_method():
    """Test generated code uses await instance.method() for zero-param class methods."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        workers = [
            WorkerInfo(
                file_path=Path("worker.py"),
                url_prefix="/worker",
                module_path="worker",
                resource_name="worker",
                worker_type="QB",
                functions=[],
                class_remotes=[
                    {
                        "name": "ImageProcessor",
                        "methods": ["list_models"],
                        "method_params": {"list_models": []},
                    },
                ],
            ),
        ]

        server_path = _generate_flash_server(project_root, workers)
        content = server_path.read_text()

        assert "await _instance_ImageProcessor.list_models()" in content
        # Handler should not accept body parameter
        assert "worker_ImageProcessor_runsync():" in content


def test_codegen_multi_param_class_method():
    """Test generated code uses _call_with_body for multi-param class methods."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        workers = [
            WorkerInfo(
                file_path=Path("worker.py"),
                url_prefix="/worker",
                module_path="worker",
                resource_name="worker",
                worker_type="QB",
                functions=[],
                class_remotes=[
                    {
                        "name": "ImageProcessor",
                        "methods": ["generate"],
                        "method_params": {"generate": ["prompt", "width"]},
                    },
                ],
            ),
        ]

        server_path = _generate_flash_server(project_root, workers)
        content = server_path.read_text()

        assert (
            "_call_with_body(_instance_ImageProcessor.generate, body.input)" in content
        )
        assert "body: _worker_ImageProcessor_generate_Request" in content
        # Model creation uses _class_type to get original method signature
        assert "_class_type" in content


def test_codegen_backward_compat_no_method_params():
    """Test that missing method_params in class_remotes uses _call_with_body."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        workers = [
            WorkerInfo(
                file_path=Path("worker.py"),
                url_prefix="/worker",
                module_path="worker",
                resource_name="worker",
                worker_type="QB",
                functions=[],
                class_remotes=[
                    {"name": "OldStyle", "methods": ["process"]},
                ],
            ),
        ]

        server_path = _generate_flash_server(project_root, workers)
        content = server_path.read_text()

        # Should use _call_with_body when method_params not provided (params=None)
        assert "_call_with_body(_instance_OldStyle.process, body.input)" in content
        assert "body: _worker_OldStyle_process_Request" in content


def test_scan_populates_function_params():
    """Test that _scan_project_workers populates function_params from scanner."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        worker_file = project_root / "worker.py"
        worker_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="worker")

@remote(config)
async def no_params() -> dict:
    return {}

@remote(config)
async def one_param(data: dict) -> dict:
    return data

@remote(config)
async def multi_params(text: str, mode: str = "default") -> dict:
    return {"text": text}
"""
        )

        workers = _scan_project_workers(project_root)

        assert len(workers) == 1
        worker = workers[0]
        assert worker.function_params == {
            "no_params": [],
            "one_param": ["data"],
            "multi_params": ["text", "mode"],
        }


def test_scan_populates_class_method_params():
    """Test that _scan_project_workers populates method_params in class_remotes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        worker_file = project_root / "worker.py"
        worker_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="worker")

@remote(config)
class Processor:
    def run(self, data: dict):
        return data

    def status(self):
        return {"ok": True}
"""
        )

        workers = _scan_project_workers(project_root)

        assert len(workers) == 1
        worker = workers[0]
        assert len(worker.class_remotes) == 1
        cls = worker.class_remotes[0]
        assert cls["method_params"] == {
            "run": ["data"],
            "status": [],
        }


def test_codegen_lb_get_with_path_params():
    """Test LB GET route with path params generates proper Swagger-compatible handler."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        workers = [
            WorkerInfo(
                file_path=Path("worker.py"),
                url_prefix="/worker",
                module_path="worker",
                resource_name="worker",
                worker_type="LB",
                functions=["get_image"],
                lb_routes=[
                    {
                        "method": "GET",
                        "path": "/images/{file_id}",
                        "fn_name": "get_image",
                        "config_variable": "cpu_config",
                    },
                ],
            ),
        ]

        server_path = _generate_flash_server(project_root, workers)
        content = server_path.read_text()

        # Handler must declare file_id as a typed parameter for Swagger
        assert "file_id: str" in content
        # Path param must be forwarded in the body dict
        assert '"file_id": file_id' in content
        # Should NOT use bare request: Request as only param
        assert (
            "async def _route_worker_get_image(file_id: str, request: Request):"
            in content
        )


def test_codegen_lb_get_without_path_params():
    """Test LB GET route without path params uses request: Request."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        workers = [
            WorkerInfo(
                file_path=Path("worker.py"),
                url_prefix="/worker",
                module_path="worker",
                resource_name="worker",
                worker_type="LB",
                functions=["health"],
                lb_routes=[
                    {
                        "method": "GET",
                        "path": "/health",
                        "fn_name": "health",
                        "config_variable": "cpu_config",
                    },
                ],
            ),
        ]

        server_path = _generate_flash_server(project_root, workers)
        content = server_path.read_text()

        assert "async def _route_worker_health(request: Request):" in content
        assert "dict(request.query_params)" in content


def test_codegen_lb_post_with_path_params():
    """Test LB POST route with path params includes both body and path params."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        workers = [
            WorkerInfo(
                file_path=Path("worker.py"),
                url_prefix="/worker",
                module_path="worker",
                resource_name="worker",
                worker_type="LB",
                functions=["update_item"],
                lb_routes=[
                    {
                        "method": "POST",
                        "path": "/items/{item_id}",
                        "fn_name": "update_item",
                        "config_variable": "api_config",
                    },
                ],
            ),
        ]

        server_path = _generate_flash_server(project_root, workers)
        content = server_path.read_text()

        # POST handler must have typed body and path param
        assert (
            "async def _route_worker_update_item(body: _worker_update_item_Input, item_id: str):"
            in content
        )
        assert '"item_id": item_id' in content
        assert "_to_dict(body)" in content


def test_codegen_lb_get_with_multiple_path_params():
    """Test LB GET route with multiple path params."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        workers = [
            WorkerInfo(
                file_path=Path("worker.py"),
                url_prefix="/worker",
                module_path="worker",
                resource_name="worker",
                worker_type="LB",
                functions=["get_version"],
                lb_routes=[
                    {
                        "method": "GET",
                        "path": "/items/{item_id}/versions/{version_id}",
                        "fn_name": "get_version",
                        "config_variable": "api_config",
                    },
                ],
            ),
        ]

        server_path = _generate_flash_server(project_root, workers)
        content = server_path.read_text()

        assert "item_id: str" in content
        assert "version_id: str" in content
        assert '"item_id": item_id' in content
        assert '"version_id": version_id' in content
