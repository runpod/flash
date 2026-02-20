"""Unit tests for run CLI command and programmatic dev server."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from runpod_flash.cli.commands._dev_server import (
    _import_from_module,
    _register_lb_routes,
    _register_qb_routes,
    create_app,
)
from runpod_flash.cli.commands.run import WorkerInfo
from runpod_flash.cli.main import app


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def temp_project(tmp_path):
    """Create a minimal Flash project with a @remote function."""
    worker_file = tmp_path / "worker.py"
    worker_file.write_text(
        "from runpod_flash import LiveServerless, remote\n"
        "gpu_config = LiveServerless(name='test_worker')\n"
        "@remote(gpu_config)\n"
        "async def process(data: dict) -> dict:\n"
        "    return data\n"
    )
    return tmp_path


def _run_cli(runner, project_dir, extra_args=None):
    """Invoke ``flash dev`` with subprocess mocked and return the Popen command."""
    saved_env = {
        k: os.environ.get(k)
        for k in ("FLASH_PROJECT_ROOT", "FLASH_IS_LIVE_PROVISIONING")
    }
    with patch("runpod_flash.cli.commands.run.subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.wait.side_effect = KeyboardInterrupt()
        mock_popen.return_value = mock_process

        with patch("runpod_flash.cli.commands.run.os.getpgid", return_value=12345):
            with patch("runpod_flash.cli.commands.run.os.killpg"):
                old_cwd = os.getcwd()
                try:
                    os.chdir(project_dir)
                    runner.invoke(app, ["dev"] + (extra_args or []))
                finally:
                    os.chdir(old_cwd)
                    for k, v in saved_env.items():
                        if v is None:
                            os.environ.pop(k, None)
                        else:
                            os.environ[k] = v

        return mock_popen.call_args[0][0]


# ---------------------------------------------------------------------------
# CLI: uvicorn command construction
# ---------------------------------------------------------------------------


class TestRunCommandFlags:
    """Test that run_command builds the correct uvicorn command."""

    def test_uses_factory_flag(self, runner, temp_project):
        cmd = _run_cli(runner, temp_project)
        assert "--factory" in cmd
        idx = cmd.index("--factory")
        assert cmd[idx + 1] == "runpod_flash.cli.commands._dev_server:create_app"

    def test_no_flash_dir_created(self, runner, temp_project):
        _run_cli(runner, temp_project)
        assert not (temp_project / ".flash").exists()

    def test_default_host_and_port(self, runner, temp_project):
        cmd = _run_cli(runner, temp_project)
        assert cmd[cmd.index("--host") + 1] == "localhost"
        assert cmd[cmd.index("--port") + 1] == "8888"

    def test_custom_port_flag(self, runner, temp_project):
        cmd = _run_cli(runner, temp_project, ["--port", "9000"])
        assert cmd[cmd.index("--port") + 1] == "9000"

    def test_custom_host_flag(self, runner, temp_project):
        cmd = _run_cli(runner, temp_project, ["--host", "0.0.0.0"])
        assert cmd[cmd.index("--host") + 1] == "0.0.0.0"

    def test_short_port_flag(self, runner, temp_project):
        cmd = _run_cli(runner, temp_project, ["-p", "7000"])
        assert cmd[cmd.index("--port") + 1] == "7000"

    def test_reload_watches_project_root(self, runner, temp_project):
        cmd = _run_cli(runner, temp_project)
        assert "--reload" in cmd
        idx = cmd.index("--reload-dir")
        assert cmd[idx + 1] == str(temp_project)

    def test_no_reload_flag(self, runner, temp_project):
        cmd = _run_cli(runner, temp_project, ["--no-reload"])
        assert "--reload" not in cmd
        assert "--reload-dir" not in cmd

    def test_sets_project_root_env_var(self, runner, temp_project):
        """FLASH_PROJECT_ROOT is set when Popen is called (inherited by child)."""
        captured_env = {}

        def capture_popen(cmd, **kwargs):
            captured_env["FLASH_PROJECT_ROOT"] = os.environ.get("FLASH_PROJECT_ROOT")
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_process.wait.side_effect = KeyboardInterrupt()
            return mock_process

        with patch(
            "runpod_flash.cli.commands.run.subprocess.Popen", side_effect=capture_popen
        ):
            with patch("runpod_flash.cli.commands.run.os.getpgid", return_value=12345):
                with patch("runpod_flash.cli.commands.run.os.killpg"):
                    old_cwd = os.getcwd()
                    try:
                        os.chdir(temp_project)
                        runner.invoke(app, ["dev"])
                    finally:
                        os.chdir(old_cwd)
                        os.environ.pop("FLASH_PROJECT_ROOT", None)
                        os.environ.pop("FLASH_IS_LIVE_PROVISIONING", None)

        assert captured_env["FLASH_PROJECT_ROOT"] == str(temp_project)


# ---------------------------------------------------------------------------
# create_app factory
# ---------------------------------------------------------------------------


class TestCreateApp:
    """Test the programmatic create_app factory."""

    def test_returns_fastapi_instance(self, tmp_path):
        result = create_app(project_root=tmp_path, workers=[])
        assert isinstance(result, FastAPI)

    def test_health_endpoints(self, tmp_path):
        test_app = create_app(project_root=tmp_path, workers=[])
        client = TestClient(test_app)

        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json()["docs"] == "/docs"

        resp = client.get("/ping")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_registers_qb_worker_routes(self, tmp_path):
        mod = tmp_path / "worker.py"
        mod.write_text("async def process(data):\n    return {'echo': data}\n")

        worker = WorkerInfo(
            file_path=mod,
            url_prefix="/worker",
            module_path="worker",
            resource_name="worker",
            worker_type="QB",
            functions=["process"],
        )
        sys.path.insert(0, str(tmp_path))
        try:
            test_app = create_app(project_root=tmp_path, workers=[worker])
            client = TestClient(test_app)
            resp = client.post("/worker/run_sync", json={"input": "hello"})
            assert resp.status_code == 200
            assert resp.json()["output"] == {"echo": "hello"}
        finally:
            sys.path.remove(str(tmp_path))
            sys.modules.pop("worker", None)


# ---------------------------------------------------------------------------
# QB routes
# ---------------------------------------------------------------------------


class TestRegisterQBRoutes:
    """Test QB route registration and invocation."""

    def test_single_function_run_sync(self, tmp_path):
        mod = tmp_path / "worker.py"
        mod.write_text("async def process(data):\n    return {'echo': data}\n")

        worker = WorkerInfo(
            file_path=mod,
            url_prefix="/worker",
            module_path="worker",
            resource_name="worker",
            worker_type="QB",
            functions=["process"],
        )
        sys.path.insert(0, str(tmp_path))
        try:
            test_app = FastAPI()
            _register_qb_routes(test_app, worker, tmp_path, "test [QB]")
            client = TestClient(test_app)
            resp = client.post("/worker/run_sync", json={"input": {"k": "v"}})
            body = resp.json()
            assert resp.status_code == 200
            assert body["status"] == "COMPLETED"
            assert body["output"] == {"echo": {"k": "v"}}
            assert "id" in body
        finally:
            sys.path.remove(str(tmp_path))
            sys.modules.pop("worker", None)

    def test_multi_function_routes(self, tmp_path):
        mod = tmp_path / "multi.py"
        mod.write_text(
            "async def alpha(d):\n    return 'a'\nasync def beta(d):\n    return 'b'\n"
        )
        worker = WorkerInfo(
            file_path=mod,
            url_prefix="/multi",
            module_path="multi",
            resource_name="multi",
            worker_type="QB",
            functions=["alpha", "beta"],
        )
        sys.path.insert(0, str(tmp_path))
        try:
            test_app = FastAPI()
            _register_qb_routes(test_app, worker, tmp_path, "test [QB]")
            client = TestClient(test_app)
            assert (
                client.post("/multi/alpha/run_sync", json={"input": {}}).json()[
                    "output"
                ]
                == "a"
            )
            assert (
                client.post("/multi/beta/run_sync", json={"input": {}}).json()["output"]
                == "b"
            )
        finally:
            sys.path.remove(str(tmp_path))
            sys.modules.pop("multi", None)


# ---------------------------------------------------------------------------
# LB routes
# ---------------------------------------------------------------------------


class TestRegisterLBRoutes:
    """Test LB route registration using an injected executor."""

    def _write_lb_module(self, tmp_path, name, config_var, fn_name):
        mod = tmp_path / f"{name}.py"
        mod.write_text(
            f"{config_var} = 'fake_config'\nasync def {fn_name}(d):\n    return d\n"
        )

    def _make_lb_worker(self, tmp_path, name, config_var, fn_name, method, path):
        return WorkerInfo(
            file_path=tmp_path / f"{name}.py",
            url_prefix=f"/{name}",
            module_path=name,
            resource_name=name,
            worker_type="LB",
            functions=[fn_name],
            lb_routes=[
                {
                    "method": method,
                    "path": path,
                    "fn_name": fn_name,
                    "config_variable": config_var,
                }
            ],
        )

    def test_post_route_passes_body(self, tmp_path):
        """POST LB routes forward the request body to the executor."""
        self._write_lb_module(tmp_path, "api", "api_config", "handle")
        worker = self._make_lb_worker(
            tmp_path, "api", "api_config", "handle", "POST", "/do"
        )
        captured = {}

        async def fake_executor(config, fn, body):
            captured["config"] = config
            captured["body"] = body
            return {"ok": True}

        sys.path.insert(0, str(tmp_path))
        try:
            test_app = FastAPI()
            _register_lb_routes(
                test_app, worker, tmp_path, "lb", executor=fake_executor
            )
            client = TestClient(test_app)
            resp = client.post("/api/do", json={"key": "val"})
            assert resp.status_code == 200
            assert captured["config"] == "fake_config"
            assert captured["body"] == {"key": "val"}
        finally:
            sys.path.remove(str(tmp_path))
            sys.modules.pop("api", None)

    def test_get_route_passes_query_params(self, tmp_path):
        """GET LB routes forward query params as a dict."""
        self._write_lb_module(tmp_path, "search", "search_cfg", "find")
        worker = self._make_lb_worker(
            tmp_path, "search", "search_cfg", "find", "GET", "/query"
        )
        captured = {}

        async def fake_executor(config, fn, body):
            captured["body"] = body
            return {"ok": True}

        sys.path.insert(0, str(tmp_path))
        try:
            test_app = FastAPI()
            _register_lb_routes(
                test_app, worker, tmp_path, "lb", executor=fake_executor
            )
            client = TestClient(test_app)
            resp = client.get("/search/query?q=test&limit=10")
            assert resp.status_code == 200
            assert captured["body"] == {"q": "test", "limit": "10"}
        finally:
            sys.path.remove(str(tmp_path))
            sys.modules.pop("search", None)

    def test_all_body_methods(self, tmp_path):
        """POST/PUT/PATCH/DELETE all register as body-accepting routes."""
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            mod_name = f"mod_{method.lower()}"
            self._write_lb_module(tmp_path, mod_name, "cfg", "handler")
            worker = self._make_lb_worker(
                tmp_path, mod_name, "cfg", "handler", method, "/ep"
            )

            async def noop_executor(config, fn, body):
                return {"ok": True}

            sys.path.insert(0, str(tmp_path))
            try:
                test_app = FastAPI()
                _register_lb_routes(
                    test_app, worker, tmp_path, "lb", executor=noop_executor
                )
                route = next(
                    r
                    for r in test_app.routes
                    if hasattr(r, "path") and r.path == f"/{mod_name}/ep"
                )
                assert method in route.methods
            finally:
                sys.path.remove(str(tmp_path))
                sys.modules.pop(mod_name, None)


# ---------------------------------------------------------------------------
# _import_from_module
# ---------------------------------------------------------------------------


class TestImportFromModule:
    """Test module importing with standard and numeric-prefix paths."""

    def test_standard_module(self, tmp_path):
        (tmp_path / "mymod.py").write_text("MY_VAR = 42\n")
        sys.path.insert(0, str(tmp_path))
        try:
            assert _import_from_module("mymod", "MY_VAR", tmp_path) == 42
        finally:
            sys.path.remove(str(tmp_path))
            sys.modules.pop("mymod", None)

    def test_numeric_prefix_module(self, tmp_path):
        subdir = tmp_path / "01_hello"
        subdir.mkdir()
        (subdir / "__init__.py").write_text("")
        (subdir / "gpu_worker.py").write_text("VALUE = 'hello'\n")
        sys.path.insert(0, str(tmp_path))
        try:
            assert (
                _import_from_module("01_hello.gpu_worker", "VALUE", tmp_path) == "hello"
            )
        finally:
            sys.path.remove(str(tmp_path))
            sys.modules.pop("01_hello.gpu_worker", None)
            sys.modules.pop("01_hello", None)

    def test_top_level_numeric_module(self, tmp_path):
        (tmp_path / "01_worker.py").write_text("RESULT = 'ok'\n")
        sys.path.insert(0, str(tmp_path))
        try:
            assert _import_from_module("01_worker", "RESULT", tmp_path) == "ok"
        finally:
            sys.path.remove(str(tmp_path))
            sys.modules.pop("01_worker", None)


# ---------------------------------------------------------------------------
# _map_body_to_params
# ---------------------------------------------------------------------------


class TestMapBodyToParams:
    """Tests for _map_body_to_params."""

    def test_matching_keys_spread_as_kwargs(self):
        from runpod_flash.cli.commands._run_server_helpers import _map_body_to_params

        def process(name: str, value: int):
            pass

        assert _map_body_to_params(process, {"name": "t", "value": 1}) == {
            "name": "t",
            "value": 1,
        }

    def test_mismatched_keys_wrap_in_first_param(self):
        from runpod_flash.cli.commands._run_server_helpers import _map_body_to_params

        def run(input_data: dict):
            pass

        assert _map_body_to_params(run, {"a": 1}) == {"input_data": {"a": 1}}

    def test_non_dict_wraps_in_first_param(self):
        from runpod_flash.cli.commands._run_server_helpers import _map_body_to_params

        def run(input_data):
            pass

        assert _map_body_to_params(run, [1, 2]) == {"input_data": [1, 2]}

    def test_no_params_returns_empty(self):
        from runpod_flash.cli.commands._run_server_helpers import _map_body_to_params

        def noop():
            pass

        assert _map_body_to_params(noop, {"k": "v"}) == {}

    def test_partial_match_wraps_in_first_param(self):
        from runpod_flash.cli.commands._run_server_helpers import _map_body_to_params

        def process(name: str, value: int):
            pass

        assert _map_body_to_params(process, {"name": "t", "extra": "x"}) == {
            "name": {"name": "t", "extra": "x"}
        }

    def test_empty_dict_spreads_as_empty(self):
        from runpod_flash.cli.commands._run_server_helpers import _map_body_to_params

        def run(input_data: dict):
            pass

        assert _map_body_to_params(run, {}) == {}
