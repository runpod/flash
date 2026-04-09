"""Tests for HandlerGenerator."""

import ast
import logging
import tempfile
from pathlib import Path

import pytest

from runpod_flash.cli.commands.build_utils.handler_generator import HandlerGenerator


# -- function-based handlers --


def test_generate_handlers_creates_files():
    """Test that handler generator creates handler files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "gpu_config": {
                    "resource_type": "Endpoint",
                    "functions": [
                        {
                            "name": "gpu_task",
                            "module": "workers.gpu",
                            "is_async": True,
                            "is_class": False,
                        }
                    ],
                }
            },
        }

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()

        assert len(handler_paths) == 1
        assert handler_paths[0].exists()
        assert handler_paths[0].name == "handler_gpu_config.py"


def test_handler_imports_function():
    """Test that generated handler imports the target function."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "gpu_config": {
                    "resource_type": "Endpoint",
                    "functions": [
                        {
                            "name": "gpu_task",
                            "module": "workers.gpu",
                            "is_async": True,
                            "is_class": False,
                        }
                    ],
                }
            },
        }

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        handler_content = handler_paths[0].read_text()

        assert (
            "gpu_task = importlib.import_module('workers.gpu').gpu_task"
            in handler_content
        )


def test_handler_calls_function_with_job_input():
    """Test that handler passes job input as kwargs to the function."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "gpu_config": {
                    "resource_type": "Endpoint",
                    "functions": [
                        {
                            "name": "gpu_task",
                            "module": "workers.gpu",
                            "is_async": True,
                            "is_class": False,
                        }
                    ],
                }
            },
        }

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        handler_content = handler_paths[0].read_text()

        assert "def handler(job):" in handler_content
        assert "gpu_task(**job_input)" in handler_content


def test_handler_has_runpod_start():
    """Test that generated handler includes runpod.serverless.start."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "test_config": {
                    "resource_type": "Endpoint",
                    "functions": [
                        {
                            "name": "my_func",
                            "module": "workers.test",
                            "is_async": False,
                            "is_class": False,
                        }
                    ],
                }
            },
        }

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        handler_content = handler_paths[0].read_text()

        assert 'runpod.serverless.start({"handler": handler})' in handler_content


def test_handler_no_cloudpickle():
    """Test that handler has no cloudpickle or serialization imports."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "gpu_config": {
                    "resource_type": "Endpoint",
                    "functions": [
                        {
                            "name": "gpu_task",
                            "module": "workers.gpu",
                            "is_async": True,
                            "is_class": False,
                        }
                    ],
                }
            },
        }

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        handler_content = handler_paths[0].read_text()

        assert "import cloudpickle" not in handler_content
        assert "import base64" not in handler_content
        assert "from runpod_flash" not in handler_content
        assert "FUNCTION_REGISTRY" not in handler_content


def test_handler_uses_first_function_only():
    """Test that handler imports only the first function (one per endpoint)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "gpu_config": {
                    "resource_type": "Endpoint",
                    "functions": [
                        {
                            "name": "gpu_task",
                            "module": "workers.gpu",
                            "is_async": True,
                            "is_class": False,
                        },
                        {
                            "name": "other_func",
                            "module": "workers.other",
                            "is_async": False,
                            "is_class": False,
                        },
                    ],
                }
            },
        }

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        handler_content = handler_paths[0].read_text()

        assert (
            "gpu_task = importlib.import_module('workers.gpu').gpu_task"
            in handler_content
        )
        assert "other_func" not in handler_content


def test_multiple_handlers_created():
    """Test that multiple handlers are created for multiple resources."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "gpu_config": {
                    "resource_type": "Endpoint",
                    "functions": [
                        {
                            "name": "gpu_task",
                            "module": "workers.gpu",
                            "is_async": True,
                            "is_class": False,
                        }
                    ],
                },
                "cpu_config": {
                    "resource_type": "Endpoint",
                    "functions": [
                        {
                            "name": "cpu_task",
                            "module": "workers.cpu",
                            "is_async": True,
                            "is_class": False,
                        }
                    ],
                },
            },
        }

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()

        assert len(handler_paths) == 2
        handler_names = {p.name for p in handler_paths}
        assert handler_names == {"handler_gpu_config.py", "handler_cpu_config.py"}


def test_lb_resources_skipped():
    """Test that load-balanced resources are skipped (handled by LBHandlerGenerator)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "lb_config": {
                    "resource_type": "Endpoint",
                    "is_load_balanced": True,
                    "functions": [
                        {
                            "name": "handle",
                            "module": "app",
                            "is_async": True,
                            "is_class": False,
                        }
                    ],
                },
                "qb_config": {
                    "resource_type": "Endpoint",
                    "is_load_balanced": False,
                    "functions": [
                        {
                            "name": "process",
                            "module": "worker",
                            "is_async": True,
                            "is_class": False,
                        }
                    ],
                },
            },
        }

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()

        assert len(handler_paths) == 1
        assert handler_paths[0].name == "handler_qb_config.py"


# -- class-based handlers --


def test_class_handler_instantiates_once():
    """Test that class handler instantiates at module level (cold start)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "gpu_worker": {
                    "resource_type": "Endpoint",
                    "functions": [
                        {
                            "name": "MyWorker",
                            "module": "worker",
                            "is_async": False,
                            "is_class": True,
                            "class_methods": ["predict"],
                        }
                    ],
                }
            },
        }

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()

        assert "_instance = MyWorker()" in content
        assert "MyWorker = importlib.import_module('worker').MyWorker" in content


def test_class_handler_single_method_auto_dispatch():
    """Test that single-method class dispatches without 'method' key."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "worker": {
                    "resource_type": "Endpoint",
                    "functions": [
                        {
                            "name": "SDWorker",
                            "module": "gpu_worker",
                            "is_async": False,
                            "is_class": True,
                            "class_methods": ["generate"],
                        }
                    ],
                }
            },
        }

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()

        assert "_METHODS = {'generate': 'generate'}" in content
        assert "if len(_METHODS) == 1:" in content
        assert "method = getattr(_instance, method_name)" in content


def test_class_handler_multi_method_requires_key():
    """Test that multi-method class requires 'method' key in input."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "worker": {
                    "resource_type": "Endpoint",
                    "functions": [
                        {
                            "name": "MLWorker",
                            "module": "worker",
                            "is_async": False,
                            "is_class": True,
                            "class_methods": ["train", "predict"],
                        }
                    ],
                }
            },
        }

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()

        assert "'train': 'train'" in content
        assert "'predict': 'predict'" in content
        assert 'job_input.pop("method", None)' in content
        assert "class MLWorker has multiple methods" in content


def test_class_handler_no_cloudpickle():
    """Test that class handler has no cloudpickle imports."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "worker": {
                    "resource_type": "Endpoint",
                    "functions": [
                        {
                            "name": "Worker",
                            "module": "w",
                            "is_async": False,
                            "is_class": True,
                            "class_methods": ["run"],
                        }
                    ],
                }
            },
        }

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()

        assert "import cloudpickle" not in content
        assert "from runpod_flash" not in content


# -- validation --


def test_validate_handler_accepts_valid_syntax():
    """Validation passes for valid syntax even when imports would fail at runtime."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "gpu_config": {
                    "resource_type": "Endpoint",
                    "functions": [
                        {
                            "name": "cpu_worker",
                            "module": "01_getting_started.03_mixed.cpu_worker",
                            "is_async": False,
                            "is_class": False,
                        }
                    ],
                }
            },
        }

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        assert handler_paths[0].exists()


def test_validate_handler_rejects_syntax_errors():
    """Validation raises ValueError for handlers with invalid Python syntax."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "gpu_config": {
                    "resource_type": "Endpoint",
                    "functions": [
                        {
                            "name": "gpu_task",
                            "module": "workers.gpu",
                            "is_async": False,
                            "is_class": False,
                        }
                    ],
                }
            },
        }

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        handler_path = handler_paths[0]

        # corrupt the handler with invalid syntax
        handler_path.write_text("def broken(:\n    pass\n")

        with pytest.raises(ValueError, match="Handler has syntax errors"):
            generator._validate_handler_imports(handler_path)


def test_empty_functions_raises():
    """Test that a resource with no functions raises ValueError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "empty": {
                    "resource_type": "Endpoint",
                    "functions": [],
                }
            },
        }

        generator = HandlerGenerator(manifest, build_dir)
        with pytest.raises(ValueError, match="has no functions"):
            generator.generate_handlers()


# -- concurrent handlers --


def test_async_handler_with_concurrency():
    """max_concurrency > 1 + async produces async handler with concurrency_modifier."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)
        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "inference": {
                    "resource_type": "Endpoint",
                    "max_concurrency": 5,
                    "functions": [
                        {
                            "name": "generate",
                            "module": "workers.inference",
                            "is_async": True,
                            "is_class": False,
                        }
                    ],
                }
            },
        }
        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()
        assert "async def handler(job):" in content
        assert "await generate(**job_input)" in content
        assert "concurrency_modifier" in content
        assert "lambda current: 5" in content


def test_sync_handler_with_concurrency():
    """max_concurrency > 1 + sync uses sync template with concurrency_modifier."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)
        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "worker": {
                    "resource_type": "Endpoint",
                    "max_concurrency": 3,
                    "functions": [
                        {
                            "name": "process",
                            "module": "workers.cpu",
                            "is_async": False,
                            "is_class": False,
                        }
                    ],
                }
            },
        }
        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()
        assert "def handler(job):" in content
        assert "async def handler(job):" not in content
        assert "concurrency_modifier" in content
        assert "lambda current: 3" in content


def test_no_concurrency_modifier_when_default():
    """max_concurrency=1 (default) produces no concurrency_modifier."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)
        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "worker": {
                    "resource_type": "Endpoint",
                    "functions": [
                        {
                            "name": "process",
                            "module": "workers.cpu",
                            "is_async": True,
                            "is_class": False,
                        }
                    ],
                }
            },
        }
        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()
        assert "concurrency_modifier" not in content
        assert 'runpod.serverless.start({"handler": handler})' in content


def test_async_handler_valid_syntax():
    """Generated async handler passes ast.parse validation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)
        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "inference": {
                    "resource_type": "Endpoint",
                    "max_concurrency": 10,
                    "functions": [
                        {
                            "name": "generate",
                            "module": "workers.inference",
                            "is_async": True,
                            "is_class": False,
                        }
                    ],
                }
            },
        }
        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()
        ast.parse(content)


def test_async_class_handler_with_concurrency():
    """max_concurrency > 1 + async class produces async class handler."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)
        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "vllm_worker": {
                    "resource_type": "Endpoint",
                    "max_concurrency": 10,
                    "functions": [
                        {
                            "name": "VLLMWorker",
                            "module": "workers.vllm",
                            "is_async": True,
                            "is_class": True,
                            "class_methods": ["generate"],
                        }
                    ],
                }
            },
        }
        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()
        assert "async def handler(job):" in content
        assert "await method(**job_input)" in content
        assert "_instance = VLLMWorker()" in content
        assert "concurrency_modifier" in content
        assert "lambda current: 10" in content
        assert "_run_maybe_async" not in content


def test_async_class_handler_valid_syntax():
    """Generated async class handler passes ast.parse validation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)
        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "worker": {
                    "resource_type": "Endpoint",
                    "max_concurrency": 8,
                    "functions": [
                        {
                            "name": "Worker",
                            "module": "w",
                            "is_async": True,
                            "is_class": True,
                            "class_methods": ["predict", "embed"],
                        }
                    ],
                }
            },
        }
        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()
        ast.parse(content)


def test_sync_class_with_concurrency_uses_sync_template():
    """max_concurrency > 1 + sync class uses sync template with concurrency_modifier."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)
        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "worker": {
                    "resource_type": "Endpoint",
                    "max_concurrency": 4,
                    "functions": [
                        {
                            "name": "SyncWorker",
                            "module": "w",
                            "is_async": False,
                            "is_class": True,
                            "class_methods": ["run"],
                        }
                    ],
                }
            },
        }
        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()
        assert "def handler(job):" in content
        assert "async def handler(job):" not in content
        assert "_run_maybe_async" in content
        assert "concurrency_modifier" in content
        assert "lambda current: 4" in content


def test_sync_handler_with_concurrency_logs_warning(caplog):
    """max_concurrency > 1 + sync handler logs a warning."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)
        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "worker": {
                    "resource_type": "Endpoint",
                    "max_concurrency": 3,
                    "functions": [
                        {
                            "name": "process",
                            "module": "workers.cpu",
                            "is_async": False,
                            "is_class": False,
                        }
                    ],
                }
            },
        }
        with caplog.at_level(logging.WARNING):
            generator = HandlerGenerator(manifest, build_dir)
            generator.generate_handlers()
        assert any(
            "max_concurrency=3" in r.message and "sync" in r.message
            for r in caplog.records
        )


def test_high_concurrency_logs_warning(caplog):
    """max_concurrency > 100 logs a high concurrency warning."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)
        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "inference": {
                    "resource_type": "Endpoint",
                    "max_concurrency": 150,
                    "functions": [
                        {
                            "name": "generate",
                            "module": "workers.inference",
                            "is_async": True,
                            "is_class": False,
                        }
                    ],
                }
            },
        }
        with caplog.at_level(logging.WARNING):
            generator = HandlerGenerator(manifest, build_dir)
            generator.generate_handlers()
        assert any("max_concurrency=150" in r.message for r in caplog.records)


def test_inject_concurrency_modifier_raises_on_missing_start_call():
    """_inject_concurrency_modifier raises if the start call string is absent."""
    with pytest.raises(ValueError, match="Unable to inject concurrency_modifier"):
        HandlerGenerator._inject_concurrency_modifier("some random code", 5)
