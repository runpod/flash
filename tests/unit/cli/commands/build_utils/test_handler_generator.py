"""Tests for HandlerGenerator."""

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


def test_function_handler_validates_empty_input():
    """Generated function handler rejects empty input dict."""
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
        content = handler_paths[0].read_text()

        assert "if raw_input is None" in content
        assert "Empty or null input" in content
        assert '"success": False' in content


def test_class_handler_validates_empty_input():
    """Generated class handler rejects empty input dict."""
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

        assert "if raw_input is None" in content
        assert "Empty or null input" in content
        assert '"success": False' in content


# -- exec()-and-call tests for generated handler templates --
# These compile and execute the generated handler code to catch
# brace-escaping bugs that string-presence checks would miss.


def _exec_handler(content: str, stub_module: str, stub_name: str, stub_obj: object):
    """Compile generated handler code with a stubbed import, return the handler function.

    Replaces the importlib.import_module line with a direct assignment so the
    generated code can run without the real module on sys.path.
    """
    # Replace the importlib import line with a stub assignment
    import_line = f"{stub_name} = importlib.import_module('{stub_module}').{stub_name}"
    patched = content.replace(import_line, f"{stub_name} = _stub_obj")

    # Strip the __main__ block so runpod.serverless.start is never called
    main_marker = 'if __name__ == "__main__":'
    if main_marker in patched:
        patched = patched[: patched.index(main_marker)]

    namespace: dict = {"_stub_obj": stub_obj}
    exec(compile(patched, "<generated-handler>", "exec"), namespace)  # noqa: S102
    return namespace["handler"]


@pytest.mark.parametrize(
    "job_input, expect_error_substring",
    [
        ({"input": {}}, "Empty or null input"),
        ({"input": None}, "Empty or null input"),
        ({}, "Empty or null input"),
        ({"input": []}, "Malformed input"),
        ({"input": 0}, "Malformed input"),
        ({"input": ""}, "Malformed input"),
    ],
    ids=[
        "empty-dict",
        "null-input",
        "missing-input-key",
        "list-input",
        "int-input",
        "string-input",
    ],
)
def test_function_handler_exec_rejects_bad_input(job_input, expect_error_substring):
    """exec() the generated function handler and verify it rejects bad input at runtime."""
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
        content = handler_paths[0].read_text()

        handler = _exec_handler(content, "workers.gpu", "gpu_task", lambda **kw: kw)
        result = handler(job_input)

        assert result["success"] is False
        assert expect_error_substring in result["error"]


def test_function_handler_exec_accepts_valid_input():
    """exec() the generated function handler and verify it passes valid input through."""
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
        content = handler_paths[0].read_text()

        handler = _exec_handler(content, "workers.gpu", "gpu_task", lambda **kw: kw)
        result = handler({"input": {"prompt": "hello"}})

        assert result == {"prompt": "hello"}


@pytest.mark.parametrize(
    "job_input, expect_error_substring",
    [
        ({"input": {}}, "Empty or null input"),
        ({"input": None}, "Empty or null input"),
        ({}, "Empty or null input"),
        ({"input": []}, "Malformed input"),
    ],
    ids=["empty-dict", "null-input", "missing-input-key", "list-input"],
)
def test_class_handler_exec_rejects_bad_input(job_input, expect_error_substring):
    """exec() the generated class handler and verify it rejects bad input at runtime."""
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

        class StubWorker:
            def run(self, **kw):
                return kw

        handler = _exec_handler(content, "w", "Worker", StubWorker)
        result = handler(job_input)

        assert result["success"] is False
        assert expect_error_substring in result["error"]


def test_class_handler_exec_accepts_valid_input():
    """exec() the generated class handler and verify it dispatches valid input."""
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

        class StubWorker:
            def run(self, **kw):
                return kw

        handler = _exec_handler(content, "w", "Worker", StubWorker)
        result = handler({"input": {"prompt": "hello"}})

        assert result == {"prompt": "hello"}
