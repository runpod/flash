"""Tests for scanner recognition of the new Endpoint API patterns."""

import tempfile
from pathlib import Path

from runpod_flash.cli.commands.build_utils.scanner import RemoteDecoratorScanner


# -- QB mode: @Endpoint(...) on a function --


class TestEndpointQBFunction:
    def test_discover_simple_qb_function(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "worker.py").write_text(
                """
from runpod_flash import Endpoint, GpuGroup

@Endpoint(name="gpu-worker", gpu=GpuGroup.ADA_24, workers=(0, 3))
async def gpu_hello(input_data: dict) -> dict:
    return {"result": input_data}
"""
            )
            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            assert len(functions) == 1
            f = functions[0]
            assert f.function_name == "gpu_hello"
            assert f.resource_config_name == "gpu-worker"
            assert f.resource_type == "Endpoint"
            assert f.is_async is True
            assert f.is_class is False
            assert f.is_load_balanced is False
            assert f.is_lb_route_handler is False
            assert f.is_live_resource is True
            assert f.param_names == ["input_data"]

    def test_discover_sync_qb_function(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "worker.py").write_text(
                """
from runpod_flash import Endpoint

@Endpoint(name="sync-worker")
def process(data: dict) -> dict:
    return data
"""
            )
            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            assert len(functions) == 1
            assert functions[0].is_async is False
            assert functions[0].resource_config_name == "sync-worker"

    def test_qb_zero_params(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "worker.py").write_text(
                """
from runpod_flash import Endpoint

@Endpoint(name="zero-params")
async def get_status() -> dict:
    return {"status": "ok"}
"""
            )
            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            assert len(functions) == 1
            assert functions[0].param_names == []

    def test_qb_multiple_params(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "worker.py").write_text(
                """
from runpod_flash import Endpoint

@Endpoint(name="multi-param")
async def transform(text: str, operation: str = "upper") -> dict:
    return {}
"""
            )
            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            assert len(functions) == 1
            assert functions[0].param_names == ["text", "operation"]

    def test_qb_docstring_extracted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "worker.py").write_text(
                '''
from runpod_flash import Endpoint

@Endpoint(name="documented")
async def process(data: dict) -> dict:
    """Process incoming data and return results."""
    return data
'''
            )
            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            assert len(functions) == 1
            assert functions[0].docstring == "Process incoming data and return results."


# -- QB mode: @Endpoint(...) on a class --


class TestEndpointQBClass:
    def test_discover_qb_class(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "worker.py").write_text(
                """
from runpod_flash import Endpoint, GpuGroup

@Endpoint(name="model-worker", gpu=GpuGroup.ANY, workers=(0, 2))
class TextModel:
    def __init__(self):
        self.ready = True

    async def predict(self, text: str) -> dict:
        return {"text": text}

    async def info(self) -> dict:
        return {"ready": self.ready}

    def _internal(self):
        pass
"""
            )
            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            assert len(functions) == 1
            f = functions[0]
            assert f.function_name == "TextModel"
            assert f.resource_config_name == "model-worker"
            assert f.is_class is True
            assert f.is_load_balanced is False
            assert f.class_methods == ["predict", "info"]
            assert f.class_method_params == {
                "predict": ["text"],
                "info": [],
            }

    def test_qb_class_docstrings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "worker.py").write_text(
                '''
from runpod_flash import Endpoint

@Endpoint(name="doc-class")
class Worker:
    """A documented worker."""

    def process(self, data):
        """Process data."""
        return data

    def info(self):
        return {}
'''
            )
            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            assert len(functions) == 1
            f = functions[0]
            assert f.docstring == "A documented worker."
            assert f.class_method_docstrings["process"] == "Process data."
            assert f.class_method_docstrings["info"] is None


# -- LB mode: ep = Endpoint(...) + @ep.get/post/... --


class TestEndpointLBRoutes:
    def test_discover_single_lb_route(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "api.py").write_text(
                """
from runpod_flash import Endpoint

api = Endpoint(name="api-service", cpu="cpu3g-2-8", workers=(1, 3))

@api.post("/compute")
async def compute(data: dict) -> dict:
    return {"result": data}
"""
            )
            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            assert len(functions) == 1
            f = functions[0]
            assert f.function_name == "compute"
            assert f.resource_config_name == "api-service"
            assert f.resource_type == "Endpoint"
            assert f.is_load_balanced is True
            assert f.is_lb_route_handler is True
            assert f.is_live_resource is True
            assert f.http_method == "POST"
            assert f.http_path == "/compute"
            assert f.config_variable == "api"
            assert f.param_names == ["data"]

    def test_discover_multiple_lb_routes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "api.py").write_text(
                """
from runpod_flash import Endpoint

api = Endpoint(name="my-api", cpu="cpu3g-2-8", workers=(1, 3))

@api.get("/health")
async def health():
    return {"status": "ok"}

@api.post("/echo")
async def echo(message: str = "hello") -> dict:
    return {"echo": message}

@api.post("/transform")
async def transform(text: str, operation: str = "uppercase") -> dict:
    return {"result": text}

@api.get("/info")
async def info():
    return {"service": "api"}
"""
            )
            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            assert len(functions) == 4

            by_name = {f.function_name: f for f in functions}

            assert by_name["health"].http_method == "GET"
            assert by_name["health"].http_path == "/health"
            assert by_name["health"].param_names == []

            assert by_name["echo"].http_method == "POST"
            assert by_name["echo"].http_path == "/echo"
            assert by_name["echo"].param_names == ["message"]

            assert by_name["transform"].http_method == "POST"
            assert by_name["transform"].http_path == "/transform"
            assert by_name["transform"].param_names == ["text", "operation"]

            assert by_name["info"].http_method == "GET"
            assert by_name["info"].http_path == "/info"

            # all routes share the same resource
            assert all(
                f.resource_config_name == "my-api" for f in functions
            )
            assert all(f.config_variable == "api" for f in functions)
            assert all(f.is_lb_route_handler for f in functions)

    def test_all_http_methods(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "api.py").write_text(
                """
from runpod_flash import Endpoint

api = Endpoint(name="rest-api")

@api.get("/items")
async def list_items():
    return []

@api.post("/items")
async def create_item(data: dict):
    return data

@api.put("/items")
async def update_item(data: dict):
    return data

@api.delete("/items")
async def delete_item(id: str):
    return {"deleted": id}

@api.patch("/items")
async def patch_item(data: dict):
    return data
"""
            )
            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            methods = {f.function_name: f.http_method for f in functions}
            assert methods == {
                "list_items": "GET",
                "create_item": "POST",
                "update_item": "PUT",
                "delete_item": "DELETE",
                "patch_item": "PATCH",
            }

    def test_lb_route_docstrings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "api.py").write_text(
                '''
from runpod_flash import Endpoint

api = Endpoint(name="doc-api")

@api.get("/health")
async def health():
    """Check service health."""
    return {"status": "ok"}

@api.post("/process")
async def process(data: dict):
    return data
'''
            )
            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            by_name = {f.function_name: f for f in functions}
            assert by_name["health"].docstring == "Check service health."
            assert by_name["process"].docstring is None


# -- mixed patterns: QB + LB in same project --


class TestEndpointMixedPatterns:
    def test_qb_and_lb_in_different_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)

            (project_dir / "worker.py").write_text(
                """
from runpod_flash import Endpoint, GpuGroup

@Endpoint(name="gpu-worker", gpu=GpuGroup.ADA_24)
async def process(data: dict) -> dict:
    return data
"""
            )
            (project_dir / "api.py").write_text(
                """
from runpod_flash import Endpoint

api = Endpoint(name="cpu-api", cpu="cpu3g-2-8")

@api.get("/health")
async def health():
    return {"status": "ok"}

@api.post("/compute")
async def compute(data: dict):
    return data
"""
            )

            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            qb_funcs = [f for f in functions if not f.is_load_balanced]
            lb_funcs = [f for f in functions if f.is_load_balanced]

            assert len(qb_funcs) == 1
            assert qb_funcs[0].function_name == "process"
            assert qb_funcs[0].resource_config_name == "gpu-worker"

            assert len(lb_funcs) == 2
            assert all(f.resource_config_name == "cpu-api" for f in lb_funcs)

    def test_endpoint_and_legacy_remote_coexist(self):
        """new Endpoint API and legacy @remote coexist in the same project."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)

            # new style
            (project_dir / "new_worker.py").write_text(
                """
from runpod_flash import Endpoint

@Endpoint(name="new-style")
async def new_process(data: dict):
    return data
"""
            )

            # old style
            (project_dir / "old_worker.py").write_text(
                """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="old-style")

@remote(config)
async def old_process(data: dict):
    return data
"""
            )

            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            names = {f.function_name for f in functions}
            assert names == {"new_process", "old_process"}

            new_f = next(f for f in functions if f.function_name == "new_process")
            assert new_f.resource_type == "Endpoint"

            old_f = next(f for f in functions if f.function_name == "old_process")
            assert old_f.resource_type == "LiveServerless"

    def test_multiple_lb_endpoints_in_same_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "apis.py").write_text(
                """
from runpod_flash import Endpoint

public_api = Endpoint(name="public")
admin_api = Endpoint(name="admin")

@public_api.get("/items")
async def list_items():
    return []

@admin_api.post("/users")
async def create_user(data: dict):
    return data
"""
            )

            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            assert len(functions) == 2
            by_name = {f.function_name: f for f in functions}

            assert by_name["list_items"].resource_config_name == "public"
            assert by_name["list_items"].config_variable == "public_api"

            assert by_name["create_user"].resource_config_name == "admin"
            assert by_name["create_user"].config_variable == "admin_api"


# -- edge cases --


class TestEndpointScannerEdgeCases:
    def test_non_endpoint_attribute_call_ignored(self):
        """@app.get() from regular FastAPI should not match as Endpoint route."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "app.py").write_text(
                """
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
async def health():
    return {"status": "ok"}
"""
            )

            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            # FastAPI routes are detected via detect_main_app, not as Endpoint routes
            assert len(functions) == 0

    def test_endpoint_variable_name_as_fallback(self):
        """if name= is missing, variable name is used as resource name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "api.py").write_text(
                """
from runpod_flash import Endpoint

my_api = Endpoint()

@my_api.get("/health")
async def health():
    return {"status": "ok"}
"""
            )

            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            assert len(functions) == 1
            assert functions[0].resource_config_name == "my_api"
            assert functions[0].config_variable == "my_api"

    def test_unregistered_variable_route_ignored(self):
        """@x.get() where x is not a known Endpoint is silently skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "app.py").write_text(
                """
from somewhere import router

@router.get("/stuff")
async def stuff():
    return {}
"""
            )

            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            assert len(functions) == 0

    def test_endpoint_in_nested_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            nested = project_dir / "workers" / "gpu"
            nested.mkdir(parents=True)

            (nested / "inference.py").write_text(
                """
from runpod_flash import Endpoint, GpuGroup

@Endpoint(name="gpu-inference", gpu=GpuGroup.ADA_24)
async def infer(data: dict) -> dict:
    return data
"""
            )

            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            assert len(functions) == 1
            assert functions[0].module_path == "workers.gpu.inference"
            assert functions[0].resource_config_name == "gpu-inference"

    def test_cross_call_detection_with_endpoint(self):
        """cross-call analysis works for @Endpoint-decorated functions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "workers.py").write_text(
                """
from runpod_flash import Endpoint, GpuGroup

@Endpoint(name="worker-a", gpu=GpuGroup.ANY)
async def generate(prompt: str):
    return {"text": prompt}

@Endpoint(name="worker-b", gpu=GpuGroup.ANY)
async def pipeline(prompt: str):
    result = generate(prompt)
    return result
"""
            )

            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            pipeline = next(f for f in functions if f.function_name == "pipeline")
            assert pipeline.calls_remote_functions is True
            assert "generate" in pipeline.called_remote_functions

    def test_multiple_qb_endpoints_same_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "workers.py").write_text(
                """
from runpod_flash import Endpoint, GpuGroup

@Endpoint(name="worker-a", gpu=GpuGroup.ADA_24)
async def process_a(data: dict):
    return data

@Endpoint(name="worker-b", gpu=GpuGroup.ANY)
async def process_b(data: dict):
    return data
"""
            )

            scanner = RemoteDecoratorScanner(project_dir)
            functions = scanner.discover_remote_functions()

            assert len(functions) == 2
            configs = {f.resource_config_name for f in functions}
            assert configs == {"worker-a", "worker-b"}
