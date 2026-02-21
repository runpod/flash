"""Tests for RemoteDecoratorScanner."""

import tempfile
from pathlib import Path

import runpod_flash
from runpod_flash.cli.commands.build_utils.scanner import RemoteDecoratorScanner
from runpod_flash.core.resources.serverless import ServerlessResource


def test_discover_simple_function():
    """Test discovering a simple @remote function."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Create a simple test file
        test_file = project_dir / "test_module.py"
        test_file.write_text(
            """
from runpod_flash import LiveServerless, remote

gpu_config = LiveServerless(name="test_gpu")

@remote(gpu_config)
async def my_function(data):
    return processed_data
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 1
        assert functions[0].function_name == "my_function"
        assert functions[0].resource_config_name == "test_gpu"
        assert functions[0].is_async is True
        assert functions[0].is_class is False


def test_discover_class():
    """Test discovering a @remote class."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        test_file = project_dir / "test_module.py"
        test_file.write_text(
            """
from runpod_flash import LiveServerless, remote

gpu_config = LiveServerless(name="test_gpu")

@remote(gpu_config)
class MyModel:
    def __init__(self):
        pass

    def process(self, data):
        return data
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 1
        assert functions[0].function_name == "MyModel"
        assert functions[0].is_class is True


def test_discover_multiple_functions_same_config():
    """Test discovering multiple functions with same resource config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        test_file = project_dir / "test_module.py"
        test_file.write_text(
            """
from runpod_flash import LiveServerless, remote

gpu_config = LiveServerless(name="gpu_worker")

@remote(gpu_config)
async def process_data(data):
    return data

@remote(gpu_config)
async def analyze_data(data):
    return analysis
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 2
        assert all(f.resource_config_name == "gpu_worker" for f in functions)
        assert functions[0].function_name in ["process_data", "analyze_data"]


def test_discover_functions_different_configs():
    """Test discovering functions with different resource configs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        test_file = project_dir / "test_module.py"
        test_file.write_text(
            """
from runpod_flash import LiveServerless, CpuLiveServerless, remote

gpu_config = LiveServerless(name="gpu_worker")
cpu_config = CpuLiveServerless(name="cpu_worker")

@remote(gpu_config)
async def gpu_task(data):
    return data

@remote(cpu_config)
async def cpu_task(data):
    return data
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 2
        resource_configs = {f.resource_config_name for f in functions}
        assert resource_configs == {"gpu_worker", "cpu_worker"}


def test_discover_nested_module():
    """Test discovering functions in nested modules."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Create nested structure
        workers_dir = project_dir / "workers" / "gpu"
        workers_dir.mkdir(parents=True)

        test_file = workers_dir / "inference.py"
        test_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="gpu_inference")

@remote(config)
async def inference(model, data):
    return results
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 1
        assert functions[0].module_path == "workers.gpu.inference"
        assert functions[0].function_name == "inference"


def test_discover_inline_config():
    """Test discovering with inline resource config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        test_file = project_dir / "test_module.py"
        test_file.write_text(
            """
from runpod_flash import LiveServerless, remote

@remote(LiveServerless(name="inline_config"))
async def my_function(data):
    return data
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 1
        assert functions[0].resource_config_name == "inline_config"


def test_ignore_non_remote_functions():
    """Test that non-decorated functions are ignored."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        test_file = project_dir / "test_module.py"
        test_file.write_text(
            """
async def normal_function(data):
    return data

class NormalClass:
    pass
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 0


def test_discover_sync_function():
    """Test discovering synchronous @remote function."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        test_file = project_dir / "test_module.py"
        test_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="cpu_sync")

@remote(config)
def sync_function(data):
    return data
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 1
        assert functions[0].is_async is False


def test_exclude_venv_directory():
    """Test that .venv directory is excluded from scanning."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Create .venv directory with Python files
        venv_dir = project_dir / ".venv" / "lib" / "python3.11"
        venv_dir.mkdir(parents=True)
        venv_file = venv_dir / "test_module.py"
        venv_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="venv_config")

@remote(config)
async def venv_function(data):
    return data
"""
        )

        # Create legitimate project file
        project_file = project_dir / "main.py"
        project_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="project_config")

@remote(config)
async def project_function(data):
    return data
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        # Should only find the project function, not the venv one
        assert len(functions) == 1
        assert functions[0].resource_config_name == "project_config"


def test_exclude_flash_directory():
    """Test that .flash directory is excluded from scanning."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Create .flash directory with Python files
        flash_dir = project_dir / ".flash" / "build"
        flash_dir.mkdir(parents=True)
        flash_file = flash_dir / "generated.py"
        flash_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="flash_config")

@remote(config)
async def flash_function(data):
    return data
"""
        )

        # Create legitimate project file
        project_file = project_dir / "main.py"
        project_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="project_config")

@remote(config)
async def project_function(data):
    return data
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        # Should only find the project function, not the flash one
        assert len(functions) == 1
        assert functions[0].resource_config_name == "project_config"


def test_exclude_runpod_directory():
    """Test that .runpod directory is excluded from scanning."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Create .runpod directory with Python files
        runpod_dir = project_dir / ".runpod" / "cache"
        runpod_dir.mkdir(parents=True)
        runpod_file = runpod_dir / "cached.py"
        runpod_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="runpod_config")

@remote(config)
async def runpod_function(data):
    return data
"""
        )

        # Create legitimate project file
        project_file = project_dir / "main.py"
        project_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="project_config")

@remote(config)
async def project_function(data):
    return data
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        # Should only find the project function, not the runpod one
        assert len(functions) == 1
        assert functions[0].resource_config_name == "project_config"


def test_exclude_nested_venv_directory():
    """Test that nested .venv directories (not just root-level) are excluded."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Create a nested .venv inside a subdirectory (the original bug)
        nested_venv = project_dir / "subproject" / ".venv" / "lib" / "python3.11"
        nested_venv.mkdir(parents=True)
        venv_file = nested_venv / "site_package.py"
        venv_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="nested_venv_config")

@remote(config)
async def nested_venv_function(data):
    return data
"""
        )

        # Create legitimate project file
        project_file = project_dir / "worker.py"
        project_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="project_config")

@remote(config)
async def project_function(data):
    return data
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        # Should only find the project function, not the nested venv one
        assert len(functions) == 1
        assert functions[0].resource_config_name == "project_config"


def test_fallback_to_variable_name_when_name_parameter_missing():
    """Test that variable name is used when resource config has no name= parameter."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        test_file = project_dir / "test_module.py"
        test_file.write_text(
            """
from runpod_flash import LiveServerless, remote

gpu_config = LiveServerless()

@remote(gpu_config)
async def my_function(data):
    return data
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 1
        # Should fall back to variable name when name parameter is missing
        assert functions[0].resource_config_name == "gpu_config"


def test_ignore_non_serverless_classes_with_serverless_in_name():
    """Test that helper classes with 'Serverless' in name are ignored."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        test_file = project_dir / "test_module.py"
        test_file.write_text(
            """
from runpod_flash import LiveServerless, remote

class MyServerlessHelper:
    def __init__(self):
        pass

helper = MyServerlessHelper()
config = LiveServerless(name="real_config")

@remote(config)
async def my_function(data):
    return data
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        # Should find function with real config but ignore helper class
        assert len(functions) == 1
        assert functions[0].resource_config_name == "real_config"


def test_extract_resource_name_with_special_characters():
    """Test that resource names with special characters are extracted correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        test_file = project_dir / "test_module.py"
        test_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="01_gpu-worker.v1")

@remote(config)
async def my_function(data):
    return data
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 1
        # Should preserve special characters in resource name
        assert functions[0].resource_config_name == "01_gpu-worker.v1"


def test_scanner_extracts_config_variable_names():
    """Test that scanner captures config variable names."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        test_file = project_dir / "endpoint.py"

        test_file.write_text(
            """
from runpod_flash import LiveLoadBalancer, remote

gpu_config = LiveLoadBalancer(name="my-endpoint")

@remote(gpu_config, method="GET", path="/health")
async def health():
    return {"status": "ok"}
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 1
        assert functions[0].config_variable == "gpu_config"
        assert functions[0].resource_config_name == "my-endpoint"


def test_cpu_live_load_balancer_flags():
    """Test that CpuLiveLoadBalancer is correctly flagged as load-balanced and live."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        test_file = project_dir / "cpu_endpoint.py"

        test_file.write_text(
            """
from runpod_flash import CpuLiveLoadBalancer, remote

cpu_config = CpuLiveLoadBalancer(name="cpu_worker")

@remote(cpu_config, method="POST", path="/validate")
async def validate_data(text):
    return {"valid": True}

@remote(cpu_config, method="GET", path="/health")
async def health():
    return {"status": "ok"}
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 2

        # Check that both functions have the correct flags
        for func in functions:
            assert func.resource_config_name == "cpu_worker"
            assert func.is_load_balanced is True, (
                "CpuLiveLoadBalancer should be marked as load-balanced"
            )
            assert func.is_live_resource is True, (
                "CpuLiveLoadBalancer should be marked as live resource"
            )
            assert func.resource_type == "CpuLiveLoadBalancer"

        # Check specific HTTP metadata for each function
        validate_func = next(f for f in functions if f.function_name == "validate_data")
        assert validate_func.http_method == "POST"
        assert validate_func.http_path == "/validate"

        health_func = next(f for f in functions if f.function_name == "health")
        assert health_func.http_method == "GET"
        assert health_func.http_path == "/health"


def test_extract_fastapi_routes():
    """Test that FastAPI routes are extracted from decorators."""
    import ast
    from runpod_flash.cli.commands.build_utils.scanner import _extract_fastapi_routes

    code = """
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def home():
    return {"hello": "world"}

@app.post("/api/users")
async def create_user():
    return {}

@app.put("/api/users/{id}")
async def update_user(id: int):
    return {"id": id}
"""

    tree = ast.parse(code)
    routes = _extract_fastapi_routes(tree, "app", "main")

    assert len(routes) == 3

    # Check first route (GET /)
    home_route = next(r for r in routes if r.function_name == "home")
    assert home_route.http_method == "GET"
    assert home_route.http_path == "/"
    assert home_route.is_async is False
    assert home_route.is_load_balanced is True
    assert home_route.is_live_resource is True

    # Check second route (POST /api/users)
    create_route = next(r for r in routes if r.function_name == "create_user")
    assert create_route.http_method == "POST"
    assert create_route.http_path == "/api/users"
    assert create_route.is_async is True

    # Check third route (PUT /api/users/{id})
    update_route = next(r for r in routes if r.function_name == "update_user")
    assert update_route.http_method == "PUT"
    assert update_route.http_path == "/api/users/{id}"
    assert update_route.is_async is True


def test_extract_fastapi_routes_with_different_app_variable():
    """Test that FastAPI routes work with different app variable names."""
    import ast
    from runpod_flash.cli.commands.build_utils.scanner import _extract_fastapi_routes

    code = """
from fastapi import FastAPI

router = FastAPI()

@router.get("/health")
def health_check():
    return {"status": "ok"}
"""

    tree = ast.parse(code)
    routes = _extract_fastapi_routes(tree, "router", "main")

    assert len(routes) == 1
    assert routes[0].function_name == "health_check"
    assert routes[0].http_method == "GET"
    assert routes[0].http_path == "/health"


def test_extract_fastapi_routes_ignores_non_matching():
    """Test that only matching app variable routes are extracted."""
    import ast
    from runpod_flash.cli.commands.build_utils.scanner import _extract_fastapi_routes

    code = """
from fastapi import FastAPI

app = FastAPI()
other_app = FastAPI()

@app.get("/")
def home():
    return {}

@other_app.get("/other")
def other():
    return {}
"""

    tree = ast.parse(code)
    routes = _extract_fastapi_routes(tree, "app", "main")

    # Should only extract routes from 'app', not 'other_app'
    assert len(routes) == 1
    assert routes[0].function_name == "home"


def test_extract_routes_from_single_included_router():
    """Test that routes from a single included router are discovered."""
    from runpod_flash.cli.commands.build_utils.scanner import detect_main_app

    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        # Create main.py with router include
        main_file = project_root / "main.py"
        main_file.write_text("""
from fastapi import FastAPI
from routers import user_router

app = FastAPI()
app.include_router(user_router, prefix="/users")

@app.get("/")
def home():
    return {"msg": "Home"}
""")

        # Create routers/__init__.py
        routers_dir = project_root / "routers"
        routers_dir.mkdir()
        (routers_dir / "__init__.py").write_text("""
from fastapi import APIRouter

user_router = APIRouter()

@user_router.get("/")
def list_users():
    return []

@user_router.post("/")
def create_user():
    return {}
""")

        # Detect routes
        main_app_config = detect_main_app(
            project_root, explicit_mothership_exists=False
        )

        assert main_app_config is not None
        routes = main_app_config["fastapi_routes"]

        # Should find 3 routes total: app.get + 2 router routes
        assert len(routes) == 3

        # Check home route
        home = next(r for r in routes if r.function_name == "home")
        assert home.http_path == "/"
        assert home.http_method == "GET"

        # Check router routes have prefix applied
        list_users = next(r for r in routes if r.function_name == "list_users")
        assert list_users.http_path == "/users/"
        assert list_users.http_method == "GET"

        create_user = next(r for r in routes if r.function_name == "create_user")
        assert create_user.http_path == "/users/"
        assert create_user.http_method == "POST"


def test_multiple_included_routers():
    """Test multiple routers with different prefixes."""
    from runpod_flash.cli.commands.build_utils.scanner import detect_main_app

    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        main_file = project_root / "main.py"
        main_file.write_text("""
from fastapi import FastAPI
from routers import user_router, admin_router

app = FastAPI()
app.include_router(user_router, prefix="/users")
app.include_router(admin_router, prefix="/admin")
""")

        routers_dir = project_root / "routers"
        routers_dir.mkdir()
        (routers_dir / "__init__.py").write_text("""
from fastapi import APIRouter

user_router = APIRouter()
admin_router = APIRouter()

@user_router.get("/list")
def list_users():
    return []

@admin_router.get("/dashboard")
def admin_dashboard():
    return {}
""")

        main_app_config = detect_main_app(
            project_root, explicit_mothership_exists=False
        )

        routes = main_app_config["fastapi_routes"]
        assert len(routes) == 2

        user_route = next(r for r in routes if "users" in r.http_path)
        assert user_route.http_path == "/users/list"

        admin_route = next(r for r in routes if "admin" in r.http_path)
        assert admin_route.http_path == "/admin/dashboard"


def test_router_import_not_found():
    """Test that missing router files are handled gracefully."""
    from runpod_flash.cli.commands.build_utils.scanner import detect_main_app

    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        main_file = project_root / "main.py"
        main_file.write_text("""
from fastapi import FastAPI
from nonexistent import some_router

app = FastAPI()
app.include_router(some_router, prefix="/api")

@app.get("/")
def home():
    return {}
""")

        main_app_config = detect_main_app(
            project_root, explicit_mothership_exists=False
        )

        # Should still work, just skip the missing router
        routes = main_app_config["fastapi_routes"]
        assert len(routes) == 1  # Only the home route
        assert routes[0].http_path == "/"


def test_router_with_no_prefix():
    """Test router included without a prefix."""
    from runpod_flash.cli.commands.build_utils.scanner import detect_main_app

    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        main_file = project_root / "main.py"
        main_file.write_text("""
from fastapi import FastAPI
from routers import api_router

app = FastAPI()
app.include_router(api_router)

@app.get("/")
def home():
    return {}
""")

        routers_dir = project_root / "routers"
        routers_dir.mkdir()
        (routers_dir / "__init__.py").write_text("""
from fastapi import APIRouter

api_router = APIRouter()

@api_router.get("/data")
def get_data():
    return {}
""")

        main_app_config = detect_main_app(
            project_root, explicit_mothership_exists=False
        )

        routes = main_app_config["fastapi_routes"]
        assert len(routes) == 2

        # Router route should not have prefix
        data_route = next(r for r in routes if r.function_name == "get_data")
        assert data_route.http_path == "/data"


def test_router_in_separate_module_file():
    """Test router defined in a separate .py file (not __init__.py)."""
    from runpod_flash.cli.commands.build_utils.scanner import detect_main_app

    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        main_file = project_root / "main.py"
        main_file.write_text("""
from fastapi import FastAPI
from routers.users import user_router

app = FastAPI()
app.include_router(user_router, prefix="/users")
""")

        routers_dir = project_root / "routers"
        routers_dir.mkdir()
        (routers_dir / "__init__.py").write_text("")  # Empty init

        # Router in separate file
        (routers_dir / "users.py").write_text("""
from fastapi import APIRouter

user_router = APIRouter()

@user_router.get("/{user_id}")
def get_user(user_id: int):
    return {}
""")

        main_app_config = detect_main_app(
            project_root, explicit_mothership_exists=False
        )

        routes = main_app_config["fastapi_routes"]
        assert len(routes) == 1
        assert routes[0].http_path == "/users/{user_id}"
        assert routes[0].function_name == "get_user"


def test_router_with_async_handlers():
    """Test router with async route handlers."""
    from runpod_flash.cli.commands.build_utils.scanner import detect_main_app

    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        main_file = project_root / "main.py"
        main_file.write_text("""
from fastapi import FastAPI
from routers import async_router

app = FastAPI()
app.include_router(async_router, prefix="/api")
""")

        routers_dir = project_root / "routers"
        routers_dir.mkdir()
        (routers_dir / "__init__.py").write_text("""
from fastapi import APIRouter

async_router = APIRouter()

@async_router.post("/process")
async def process_data():
    return {}
""")

        main_app_config = detect_main_app(
            project_root, explicit_mothership_exists=False
        )

        routes = main_app_config["fastapi_routes"]
        assert len(routes) == 1
        assert routes[0].http_path == "/api/process"
        assert routes[0].is_async is True
        assert routes[0].http_method == "POST"


def test_class_methods_extraction():
    """Test that public methods are extracted from @remote classes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        test_file = project_dir / "gpu_worker.py"
        test_file.write_text(
            """
from runpod_flash import LiveServerless, remote

gpu_config = LiveServerless(name="gpu_worker")

@remote(gpu_config)
class SimpleSD:
    def __init__(self):
        self.model = None

    def generate_image(self, prompt):
        return {"image": "base64..."}

    def upscale(self, image):
        return {"image": "upscaled..."}

    def _load_model(self):
        pass

    def __repr__(self):
        return "SimpleSD"
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 1
        meta = functions[0]
        assert meta.function_name == "SimpleSD"
        assert meta.is_class is True
        assert meta.class_methods == ["generate_image", "upscale"]


def test_class_methods_excludes_private_and_dunder():
    """Test that _private and __dunder__ methods are excluded from class_methods."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        test_file = project_dir / "worker.py"
        test_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="worker")

@remote(config)
class MyWorker:
    def __init__(self):
        pass

    def __repr__(self):
        return "MyWorker"

    def _internal_helper(self):
        pass

    async def process(self, data):
        return data
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 1
        assert functions[0].class_methods == ["process"]


def test_class_with_no_public_methods():
    """Test @remote class with only private/dunder methods has empty class_methods."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        test_file = project_dir / "worker.py"
        test_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="worker")

@remote(config)
class EmptyWorker:
    def __init__(self):
        pass

    def __call__(self, data):
        return data
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 1
        assert functions[0].class_methods == []


def test_function_has_empty_class_methods():
    """Test that regular @remote functions have empty class_methods list."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        test_file = project_dir / "worker.py"
        test_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="worker")

@remote(config)
async def my_function(data):
    return data
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 1
        assert functions[0].is_class is False
        assert functions[0].class_methods == []


def test_param_names_single_param():
    """Test that param_names extracts a single parameter."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        test_file = project_dir / "worker.py"
        test_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="worker")

@remote(config)
async def process(data):
    return data
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 1
        assert functions[0].param_names == ["data"]


def test_param_names_zero_params():
    """Test that param_names is empty for zero-parameter functions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        test_file = project_dir / "worker.py"
        test_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="worker")

@remote(config)
async def list_images() -> dict:
    return {"images": []}
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 1
        assert functions[0].param_names == []


def test_param_names_multiple_params():
    """Test that param_names extracts multiple parameters."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        test_file = project_dir / "worker.py"
        test_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="worker")

@remote(config)
async def transform(text: str, operation: str = "uppercase") -> dict:
    return {"result": text}
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 1
        assert functions[0].param_names == ["text", "operation"]


def test_class_method_params_extraction():
    """Test that class_method_params extracts params for each public method."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        test_file = project_dir / "worker.py"
        test_file.write_text(
            """
from runpod_flash import LiveServerless, remote

config = LiveServerless(name="worker")

@remote(config)
class ImageProcessor:
    def __init__(self):
        pass

    def generate(self, prompt: str, width: int = 512):
        return {}

    def list_models(self):
        return []

    def _internal(self):
        pass
"""
        )

        scanner = RemoteDecoratorScanner(project_dir)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 1
        meta = functions[0]
        assert meta.is_class is True
        assert meta.class_methods == ["generate", "list_models"]
        assert meta.class_method_params == {
            "generate": ["prompt", "width"],
            "list_models": [],
        }
        # Classes should have empty param_names
        assert meta.param_names == []


def test_resource_config_types_matches_exports():
    """Static _RESOURCE_CONFIG_TYPES must include all ServerlessResource subclasses from runpod_flash."""
    for type_name in RemoteDecoratorScanner._RESOURCE_CONFIG_TYPES:
        cls = getattr(runpod_flash, type_name, None)
        assert cls is not None, f"{type_name} not found in runpod_flash exports"
        assert issubclass(cls, ServerlessResource), (
            f"{type_name} is not a ServerlessResource subclass"
        )
