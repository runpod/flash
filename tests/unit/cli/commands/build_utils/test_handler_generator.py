"""Tests for HandlerGenerator."""

import tempfile
from pathlib import Path

import pytest

from runpod_flash.cli.commands.build_utils.handler_generator import HandlerGenerator


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
                    "resource_type": "LiveServerless",
                    "is_live_resource": True,
                    "handler_file": "handler_gpu_config.py",
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


def test_handler_file_contains_imports():
    """Test that generated handler includes proper imports."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "gpu_config": {
                    "resource_type": "LiveServerless",
                    "is_live_resource": True,
                    "handler_file": "handler_gpu_config.py",
                    "functions": [
                        {
                            "name": "gpu_task",
                            "module": "workers.gpu",
                            "is_async": True,
                            "is_class": False,
                        },
                        {
                            "name": "process_data",
                            "module": "workers.utils",
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
        assert (
            "process_data = importlib.import_module('workers.utils').process_data"
            in handler_content
        )


def test_handler_file_contains_registry():
    """Test that generated handler includes function registry."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "gpu_config": {
                    "resource_type": "LiveServerless",
                    "is_live_resource": True,
                    "handler_file": "handler_gpu_config.py",
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
        assert "FUNCTION_REGISTRY = {" in handler_content
        assert '"gpu_task": gpu_task,' in handler_content


def test_handler_file_contains_runpod_start():
    """Test that generated handler includes RunPod start."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "test_config": {
                    "resource_type": "LiveServerless",
                    "is_live_resource": True,
                    "handler_file": "handler_test_config.py",
                    "functions": [],
                }
            },
        }

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()

        handler_content = handler_paths[0].read_text()
        assert 'runpod.serverless.start({"handler": handler})' in handler_content


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
                    "resource_type": "LiveServerless",
                    "is_live_resource": True,
                    "handler_file": "handler_gpu_config.py",
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
                    "resource_type": "CpuLiveServerless",
                    "is_live_resource": True,
                    "handler_file": "handler_cpu_config.py",
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


def test_handler_includes_create_handler_import():
    """Test that generated handler imports create_handler factory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "test_config": {
                    "resource_type": "LiveServerless",
                    "is_live_resource": True,
                    "handler_file": "handler_test_config.py",
                    "functions": [
                        {
                            "name": "test_func",
                            "module": "workers.test",
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
            "from runpod_flash.runtime.generic_handler import create_handler"
            in handler_content
        )
        assert "handler = create_handler(FUNCTION_REGISTRY)" in handler_content


def test_handler_does_not_contain_serialization_logic():
    """Test that generated handler delegates serialization to generic_handler."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "test_config": {
                    "resource_type": "LiveServerless",
                    "is_live_resource": True,
                    "handler_file": "handler_test_config.py",
                    "functions": [
                        {
                            "name": "test_func",
                            "module": "workers.test",
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
        # Serialization logic should NOT be in generated handler
        # (it's now in generic_handler.py)
        assert "cloudpickle.loads(base64.b64decode" not in handler_content
        assert "def handler(" not in handler_content
        assert "import base64" not in handler_content
        assert "import json" not in handler_content


# --- Tests for deployed handler template (is_live_resource=False) ---


def test_deployed_handler_inlines_handler_logic():
    """Deployed resource generates handler with inlined logic (no runpod_flash import)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "gpu_config": {
                    "resource_type": "Serverless",
                    "is_live_resource": False,
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

        # Handler logic is inlined, no runpod_flash import
        assert "from runpod_flash" not in handler_content
        assert "def handler(job):" in handler_content
        assert "gpu_task(**job_input)" in handler_content
        assert "FUNCTION_REGISTRY" not in handler_content


def test_deployed_handler_single_function_import():
    """Deployed handler imports only the first function (one per endpoint)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "gpu_config": {
                    "resource_type": "Serverless",
                    "is_live_resource": False,
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

        # Only first function imported
        assert (
            "gpu_task = importlib.import_module('workers.gpu').gpu_task"
            in handler_content
        )
        assert "other_func" not in handler_content


def test_deployed_handler_no_cloudpickle_imports():
    """Deployed handler has no cloudpickle or serialization imports."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "gpu_config": {
                    "resource_type": "Serverless",
                    "is_live_resource": False,
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
        assert "from .serialization" not in handler_content
        assert "from runpod_flash" not in handler_content


def test_deployed_handler_has_runpod_start():
    """Deployed handler includes runpod.serverless.start."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "test_config": {
                    "resource_type": "Serverless",
                    "is_live_resource": False,
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


def test_live_resource_uses_old_template():
    """Live resource (is_live_resource=True) uses HANDLER_TEMPLATE with create_handler."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "gpu_config": {
                    "resource_type": "LiveServerless",
                    "is_live_resource": True,
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
            "from runpod_flash.runtime.generic_handler import create_handler"
            in handler_content
        )
        assert "FUNCTION_REGISTRY" in handler_content
        assert "handler = create_handler(FUNCTION_REGISTRY)" in handler_content
        assert "def handler(job):" not in handler_content


# --- Tests for _validate_handler_imports (ast.parse validation) ---


def test_validate_handler_accepts_valid_syntax_with_unavailable_imports():
    """Validation passes for valid syntax even when imports would fail at runtime."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)

        # Module path uses numeric prefix that can't resolve at build time
        manifest = {
            "version": "1.0",
            "generated_at": "2026-01-02T10:00:00Z",
            "project_name": "test_app",
            "resources": {
                "gpu_config": {
                    "resource_type": "Serverless",
                    "is_live_resource": False,
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
        # Should not raise — syntax is valid even though the import
        # (importlib.import_module('01_getting_started.03_mixed.cpu_worker'))
        # would fail at build time
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
                    "resource_type": "Serverless",
                    "is_live_resource": False,
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

        # Corrupt the handler file with invalid syntax
        handler_path.write_text("def broken(:\n    pass\n")

        with pytest.raises(ValueError, match="Handler has syntax errors"):
            generator._validate_handler_imports(handler_path)


# --- Tests for deployed class-based handler (is_class=True) ---


def _make_class_manifest(
    *, is_live_resource=False, class_methods=None, extra_resource_fields=None
):
    """Helper to create a manifest with a class-based @remote entry."""
    func_entry = {
        "name": "MyModel",
        "module": "workers.model",
        "is_async": False,
        "is_class": True,
    }
    if class_methods is not None:
        func_entry["class_methods"] = class_methods
    resource = {
        "resource_type": "Serverless",
        "is_live_resource": is_live_resource,
        "functions": [func_entry],
    }
    if extra_resource_fields:
        resource.update(extra_resource_fields)
    return {
        "version": "1.0",
        "generated_at": "2026-01-02T10:00:00Z",
        "project_name": "test_app",
        "resources": {"my_model_config": resource},
    }


def test_deployed_class_handler_creates_module_level_instance():
    """Deployed class handler instantiates the class at module level."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)
        manifest = _make_class_manifest()

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()

        assert "_instance = MyModel()" in content


def test_deployed_class_handler_dispatches_to_method():
    """Deployed class handler reads method_name from job input and dispatches."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)
        manifest = _make_class_manifest()

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()

        # Handler should get method_name from input and call it on the instance
        assert "method_name" in content
        assert "getattr(_instance, method_name)" in content


def test_deployed_class_handler_does_not_call_class_directly():
    """Deployed class handler must NOT do MyModel(**job_input) — that's the bug."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)
        manifest = _make_class_manifest()

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()

        # The broken pattern: calling the class as a function with job input
        assert "MyModel(**job_input)" not in content


def test_deployed_class_handler_excludes_method_name_from_kwargs():
    """method_name must be stripped from kwargs before passing to the method."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)
        manifest = _make_class_manifest()

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()

        # Should filter out method_name from the kwargs passed to the method
        assert 'k != "method_name"' in content


def test_deployed_class_handler_handles_async_methods():
    """Deployed class handler handles coroutines from async methods."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)
        manifest = _make_class_manifest()

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()

        assert "inspect.iscoroutine(result)" in content
        assert "asyncio.run(result)" in content


def test_deployed_class_handler_has_valid_syntax():
    """Generated class handler must be valid Python (passes ast.parse)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)
        manifest = _make_class_manifest()

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()

        # Should not raise — _validate_handler_imports uses ast.parse
        assert handler_paths[0].exists()
        import ast

        ast.parse(handler_paths[0].read_text())


def test_deployed_class_handler_has_runpod_start():
    """Deployed class handler includes runpod.serverless.start."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)
        manifest = _make_class_manifest()

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()

        assert 'runpod.serverless.start({"handler": handler})' in content


def test_deployed_class_handler_imports_class():
    """Deployed class handler imports the class via importlib."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)
        manifest = _make_class_manifest()

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()

        assert "MyModel = importlib.import_module('workers.model').MyModel" in content


def test_deployed_class_handler_single_method_defaults_to_that_method():
    """Single public method class defaults method_name to that method (no method_name needed)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)
        manifest = _make_class_manifest(class_methods=["predict"])

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()

        assert 'method_name = job_input.get("method_name", "predict")' in content


def test_deployed_class_handler_multi_method_defaults_to_call():
    """Multi-method class defaults method_name to __call__ (requires explicit method_name)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)
        manifest = _make_class_manifest(class_methods=["predict", "embed"])

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()

        assert 'method_name = job_input.get("method_name", "__call__")' in content


def test_deployed_class_handler_no_class_methods_defaults_to_call():
    """Class with no class_methods metadata defaults to __call__."""
    with tempfile.TemporaryDirectory() as tmpdir:
        build_dir = Path(tmpdir)
        manifest = _make_class_manifest()  # No class_methods

        generator = HandlerGenerator(manifest, build_dir)
        handler_paths = generator.generate_handlers()
        content = handler_paths[0].read_text()

        assert 'method_name = job_input.get("method_name", "__call__")' in content
