"""P1 integration test gap-fills.

Covers: CLI-RUN-013 (QB+LB mix codegen), CLI-RUN-019 (server.py regeneration),
        BUILD-005 (requirements.txt deps).
"""

import tempfile
from pathlib import Path

from runpod_flash.cli.commands.run import WorkerInfo, _generate_flash_server


# ---------------------------------------------------------------------------
# CLI-RUN-013: Mix of QB and LB endpoints in the same project
# ---------------------------------------------------------------------------
class TestQBAndLBMixCodegen:
    """Generated server.py correctly handles both QB and LB workers."""

    def test_qb_and_lb_workers_in_same_project(self):
        """CLI-RUN-013: QB function + LB route → both present in generated code."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            workers = [
                WorkerInfo(
                    file_path=Path("gpu_worker.py"),
                    url_prefix="/gpu_worker",
                    module_path="gpu_worker",
                    resource_name="gpu_worker",
                    worker_type="QB",
                    functions=["process"],
                    function_params={"process": ["data"]},
                ),
                WorkerInfo(
                    file_path=Path("api.py"),
                    url_prefix="/api",
                    module_path="api",
                    resource_name="api",
                    worker_type="LB",
                    functions=["list_items"],
                    lb_routes=[
                        {
                            "method": "GET",
                            "path": "/items",
                            "fn_name": "list_items",
                            "config_variable": "api_config",
                        },
                    ],
                ),
            ]

            server_path = _generate_flash_server(project_root, workers)
            content = server_path.read_text()

            # QB worker: direct function import + runsync route
            assert "from gpu_worker import process" in content
            assert '"/gpu_worker/runsync"' in content
            assert "_call_with_body(process" in content

            # LB worker: config + function import + LB route
            assert "from api import api_config" in content
            assert "from api import list_items" in content
            assert "_lb_execute(api_config, list_items," in content

            # Both import helpers should be present
            assert "_call_with_body" in content
            assert "_lb_execute" in content

    def test_qb_class_and_lb_function_in_same_project(self):
        """QB class + LB function → both properly generated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            workers = [
                WorkerInfo(
                    file_path=Path("model.py"),
                    url_prefix="/model",
                    module_path="model",
                    resource_name="model",
                    worker_type="QB",
                    functions=[],
                    class_remotes=[
                        {
                            "name": "TextModel",
                            "methods": ["predict"],
                            "method_params": {"predict": ["text"]},
                        }
                    ],
                ),
                WorkerInfo(
                    file_path=Path("health.py"),
                    url_prefix="/health",
                    module_path="health",
                    resource_name="health",
                    worker_type="LB",
                    functions=["status"],
                    lb_routes=[
                        {
                            "method": "GET",
                            "path": "/status",
                            "fn_name": "status",
                            "config_variable": "health_config",
                        },
                    ],
                ),
            ]

            server_path = _generate_flash_server(project_root, workers)
            content = server_path.read_text()

            # QB class: instantiation + method route
            assert "_instance_TextModel = TextModel()" in content
            assert "_instance_TextModel.predict" in content

            # LB function: config import + route
            assert "from health import health_config" in content
            assert "from health import status" in content
            assert "_lb_execute(health_config, status," in content

    def test_multiple_lb_routes_alongside_qb(self):
        """Multiple LB routes + QB function all present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            workers = [
                WorkerInfo(
                    file_path=Path("worker.py"),
                    url_prefix="/worker",
                    module_path="worker",
                    resource_name="worker",
                    worker_type="QB",
                    functions=["compute"],
                    function_params={"compute": ["x"]},
                ),
                WorkerInfo(
                    file_path=Path("routes.py"),
                    url_prefix="/routes",
                    module_path="routes",
                    resource_name="routes",
                    worker_type="LB",
                    functions=["create", "read"],
                    lb_routes=[
                        {
                            "method": "POST",
                            "path": "/create",
                            "fn_name": "create",
                            "config_variable": "lb_config",
                        },
                        {
                            "method": "GET",
                            "path": "/read",
                            "fn_name": "read",
                            "config_variable": "lb_config",
                        },
                    ],
                ),
            ]

            server_path = _generate_flash_server(project_root, workers)
            content = server_path.read_text()

            # Both LB routes registered
            assert "_lb_execute(lb_config, create," in content
            assert "_lb_execute(lb_config, read," in content
            # QB route also present
            assert '"/worker/runsync"' in content


# ---------------------------------------------------------------------------
# CLI-RUN-019: server.py regenerated on each flash run (no stale cache)
# ---------------------------------------------------------------------------
class TestServerRegeneration:
    """_generate_flash_server overwrites existing server.py on each call."""

    def test_server_py_regenerated_not_cached(self):
        """CLI-RUN-019: Calling _generate_flash_server twice overwrites previous output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # First generation: one function
            workers_v1 = [
                WorkerInfo(
                    file_path=Path("worker.py"),
                    url_prefix="/worker",
                    module_path="worker",
                    resource_name="worker",
                    worker_type="QB",
                    functions=["func_v1"],
                    function_params={"func_v1": ["x"]},
                ),
            ]

            server_path = _generate_flash_server(project_root, workers_v1)
            content_v1 = server_path.read_text()
            assert "func_v1" in content_v1

            # Second generation: different function
            workers_v2 = [
                WorkerInfo(
                    file_path=Path("worker.py"),
                    url_prefix="/worker",
                    module_path="worker",
                    resource_name="worker",
                    worker_type="QB",
                    functions=["func_v2"],
                    function_params={"func_v2": ["y"]},
                ),
            ]

            server_path_2 = _generate_flash_server(project_root, workers_v2)
            content_v2 = server_path_2.read_text()

            # v2 should contain new function, NOT old one
            assert "func_v2" in content_v2
            assert "func_v1" not in content_v2

            # Same file path
            assert server_path == server_path_2

    def test_server_py_in_flash_directory(self):
        """Generated server.py is placed in .flash/ subdirectory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            workers = [
                WorkerInfo(
                    file_path=Path("w.py"),
                    url_prefix="/w",
                    module_path="w",
                    resource_name="w",
                    worker_type="QB",
                    functions=["f"],
                ),
            ]

            server_path = _generate_flash_server(project_root, workers)

            assert server_path.parent.name == ".flash"
            assert server_path.name == "server.py"
            assert server_path.exists()


# ---------------------------------------------------------------------------
# BUILD-005: requirements.txt deps included in build
# ---------------------------------------------------------------------------
class TestRequirementsTxtCollection:
    """collect_requirements reads requirements.txt and merges with @remote deps."""

    def test_requirements_txt_parsed(self):
        """BUILD-005: requirements.txt entries included in collected requirements."""
        from runpod_flash.cli.commands.build import collect_requirements

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            build_dir = project_dir / "build"
            build_dir.mkdir()

            # Create requirements.txt
            (project_dir / "requirements.txt").write_text(
                "torch>=2.0.0\nnumpy\n# comment line\n\npandas==1.5.0\n"
            )

            reqs = collect_requirements(project_dir, build_dir)

            assert "torch>=2.0.0" in reqs
            assert "numpy" in reqs
            assert "pandas==1.5.0" in reqs
            # Comments and empty lines excluded
            assert "# comment line" not in reqs
            assert "" not in reqs

    def test_requirements_txt_missing_is_ok(self):
        """No requirements.txt → still works (returns empty or remote deps only)."""
        from runpod_flash.cli.commands.build import collect_requirements

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            build_dir = project_dir / "build"
            build_dir.mkdir()

            # No requirements.txt
            reqs = collect_requirements(project_dir, build_dir)
            assert isinstance(reqs, list)

    def test_requirements_deduplication(self):
        """Duplicate requirements across sources are deduplicated."""
        from runpod_flash.cli.commands.build import collect_requirements

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            build_dir = project_dir / "build"
            build_dir.mkdir()

            # requirements.txt with duplicates
            (project_dir / "requirements.txt").write_text("torch\ntorch\nnumpy\n")

            reqs = collect_requirements(project_dir, build_dir)

            # Should be deduplicated
            assert reqs.count("torch") == 1
            assert reqs.count("numpy") == 1

    def test_requirements_with_remote_deps_merged(self):
        """requirements.txt + @remote dependencies merged without duplicates."""
        from runpod_flash.cli.commands.build import collect_requirements

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            build_dir = project_dir / "build"
            workers_dir = build_dir / "workers"
            workers_dir.mkdir(parents=True)

            # requirements.txt
            (project_dir / "requirements.txt").write_text("requests\n")

            # Worker file with @remote deps (sync function — AST parser
            # uses ast.FunctionDef, not AsyncFunctionDef)
            (workers_dir / "worker.py").write_text(
                "from runpod_flash import LiveServerless, remote\n"
                'gpu = LiveServerless(name="test")\n'
                '@remote(gpu, dependencies=["torch", "pillow"])\n'
                "def process(data): return data\n"
            )

            reqs = collect_requirements(project_dir, build_dir)

            assert "requests" in reqs
            assert "torch" in reqs
            assert "pillow" in reqs
