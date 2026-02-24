"""Tests for main.py FastAPI app detection in scanner."""

import tempfile
from pathlib import Path

from runpod_flash.cli.commands.build_utils.scanner import (
    detect_main_app,
)


class TestDetectMainApp:
    """Test main.py FastAPI app detection."""

    def test_detect_main_app_with_fastapi_and_routes(self):
        """Test detection of main.py with FastAPI app and custom routes."""
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

            result = detect_main_app(project_root)

            assert result is not None
            assert result["app_variable"] == "app"
            assert result["has_routes"] is True
            assert result["file_path"] == main_file

    def test_detect_main_app_with_app_py(self):
        """Test detection works with app.py instead of main.py."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            app_file = project_root / "app.py"
            app_file.write_text(
                """
from fastapi import FastAPI

api = FastAPI()

@api.post("/process")
async def process():
    return {"status": "ok"}
"""
            )

            result = detect_main_app(project_root)

            assert result is not None
            assert result["app_variable"] == "api"
            assert result["has_routes"] is True

    def test_detect_main_app_with_server_py(self):
        """Test detection works with server.py instead of main.py."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            server_file = project_root / "server.py"
            server_file.write_text(
                """
from fastapi import FastAPI

server = FastAPI()

@server.get("/health")
def health():
    return {"status": "healthy"}
"""
            )

            result = detect_main_app(project_root)

            assert result is not None
            assert result["app_variable"] == "server"
            assert result["has_routes"] is True

    def test_detect_main_app_no_routes(self):
        """Test skipping main.py with FastAPI but no custom routes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            main_file = project_root / "main.py"
            main_file.write_text(
                """
from fastapi import FastAPI
from runpod_flash import remote

app = FastAPI()

@remote(resource_config=gpu_config)
def process(data):
    return data
"""
            )

            result = detect_main_app(project_root)

            # Should detect app but has_routes should be False
            assert result is not None
            assert result["has_routes"] is False

    def test_detect_main_app_no_fastapi(self):
        """Test returns None if no FastAPI app found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            main_file = project_root / "main.py"
            main_file.write_text(
                """
def main():
    print("hello")
"""
            )

            result = detect_main_app(project_root)

            assert result is None

    def test_detect_main_app_no_file(self):
        """Test returns None if no main.py exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            result = detect_main_app(project_root)

            assert result is None

    def test_detect_main_app_syntax_error(self):
        """Test gracefully handles syntax errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            main_file = project_root / "main.py"
            main_file.write_text(
                """
from fastapi import FastAPI
app = FastAPI(
    # Missing closing parenthesis
"""
            )

            result = detect_main_app(project_root)

            assert result is None

    def test_detect_main_app_priority_main_over_app(self):
        """Test main.py takes priority over app.py."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create both main.py and app.py
            main_file = project_root / "main.py"
            main_file.write_text(
                """
from fastapi import FastAPI
app = FastAPI()

@app.get("/main")
def main_route():
    return {"from": "main"}
"""
            )

            app_file = project_root / "app.py"
            app_file.write_text(
                """
from fastapi import FastAPI
app = FastAPI()

@app.get("/app")
def app_route():
    return {"from": "app"}
"""
            )

            result = detect_main_app(project_root)

            # Should use main.py
            assert result is not None
            assert result["file_path"] == main_file

    def test_detect_main_app_async_route(self):
        """Test detection works with async routes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            main_file = project_root / "main.py"
            main_file.write_text(
                """
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
async def root():
    return {"msg": "Hello"}
"""
            )

            result = detect_main_app(project_root)

            assert result is not None
            assert result["has_routes"] is True

    def test_detect_main_app_multiple_routes(self):
        """Test detection with multiple routes."""
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

@app.post("/items")
def create_item(item: dict):
    return item

@app.put("/items/{item_id}")
async def update_item(item_id: int, item: dict):
    return {"id": item_id, "item": item}

@app.delete("/items/{item_id}")
def delete_item(item_id: int):
    return {"deleted": item_id}
"""
            )

            result = detect_main_app(project_root)

            assert result is not None
            assert result["has_routes"] is True

    def test_detect_main_app_respects_explicit_lb_flag(self):
        """Test that explicit_lb_exists flag prevents auto-detection."""
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

            # Without flag, should detect
            result = detect_main_app(project_root, explicit_lb_exists=False)
            assert result is not None
            assert result["has_routes"] is True

            # With flag, should not detect
            result = detect_main_app(project_root, explicit_lb_exists=True)
            assert result is None
