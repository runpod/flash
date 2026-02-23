"""TDD tests for scanner path utility functions.

Written first (failing) per the plan's TDD requirement.
These test file_to_url_prefix, file_to_resource_name, file_to_module_path.
"""

import os


from runpod_flash.cli.commands.build_utils.scanner import (
    file_to_module_path,
    file_to_resource_name,
    file_to_url_prefix,
)


class TestFileToUrlPrefix:
    """Tests for file_to_url_prefix utility."""

    def test_root_level_file(self, tmp_path):
        """gpu_worker.py → /gpu_worker"""
        f = tmp_path / "gpu_worker.py"
        assert file_to_url_prefix(f, tmp_path) == "/gpu_worker"

    def test_single_subdir(self, tmp_path):
        """longruns/stage1.py → /longruns/stage1"""
        f = tmp_path / "longruns" / "stage1.py"
        assert file_to_url_prefix(f, tmp_path) == "/longruns/stage1"

    def test_nested_subdir(self, tmp_path):
        """preprocess/first_pass.py → /preprocess/first_pass"""
        f = tmp_path / "preprocess" / "first_pass.py"
        assert file_to_url_prefix(f, tmp_path) == "/preprocess/first_pass"

    def test_deep_nested(self, tmp_path):
        """workers/gpu/inference.py → /workers/gpu/inference"""
        f = tmp_path / "workers" / "gpu" / "inference.py"
        assert file_to_url_prefix(f, tmp_path) == "/workers/gpu/inference"

    def test_hyphenated_filename(self, tmp_path):
        """my-worker.py → /my-worker (hyphens valid in URLs)"""
        f = tmp_path / "my-worker.py"
        assert file_to_url_prefix(f, tmp_path) == "/my-worker"

    def test_starts_with_slash(self, tmp_path):
        """Result always starts with /"""
        f = tmp_path / "worker.py"
        result = file_to_url_prefix(f, tmp_path)
        assert result.startswith("/")

    def test_no_py_extension(self, tmp_path):
        """Result does not include .py extension"""
        f = tmp_path / "worker.py"
        result = file_to_url_prefix(f, tmp_path)
        assert ".py" not in result


class TestFileToResourceName:
    """Tests for file_to_resource_name utility."""

    def test_root_level_file(self, tmp_path):
        """gpu_worker.py → gpu_worker"""
        f = tmp_path / "gpu_worker.py"
        assert file_to_resource_name(f, tmp_path) == "gpu_worker"

    def test_single_subdir(self, tmp_path):
        """longruns/stage1.py → longruns_stage1"""
        f = tmp_path / "longruns" / "stage1.py"
        assert file_to_resource_name(f, tmp_path) == "longruns_stage1"

    def test_nested_subdir(self, tmp_path):
        """preprocess/first_pass.py → preprocess_first_pass"""
        f = tmp_path / "preprocess" / "first_pass.py"
        assert file_to_resource_name(f, tmp_path) == "preprocess_first_pass"

    def test_deep_nested(self, tmp_path):
        """workers/gpu/inference.py → workers_gpu_inference"""
        f = tmp_path / "workers" / "gpu" / "inference.py"
        assert file_to_resource_name(f, tmp_path) == "workers_gpu_inference"

    def test_hyphenated_filename(self, tmp_path):
        """my-worker.py → my_worker (hyphens replaced with underscores for Python identifiers)"""
        f = tmp_path / "my-worker.py"
        assert file_to_resource_name(f, tmp_path) == "my_worker"

    def test_no_py_extension(self, tmp_path):
        """Result does not include .py extension"""
        f = tmp_path / "worker.py"
        result = file_to_resource_name(f, tmp_path)
        assert ".py" not in result

    def test_no_path_separators(self, tmp_path):
        """Result contains no / or os.sep characters"""
        f = tmp_path / "a" / "b" / "worker.py"
        result = file_to_resource_name(f, tmp_path)
        assert "/" not in result
        assert os.sep not in result


class TestFileToModulePath:
    """Tests for file_to_module_path utility."""

    def test_root_level_file(self, tmp_path):
        """gpu_worker.py → gpu_worker"""
        f = tmp_path / "gpu_worker.py"
        assert file_to_module_path(f, tmp_path) == "gpu_worker"

    def test_single_subdir(self, tmp_path):
        """longruns/stage1.py → longruns.stage1"""
        f = tmp_path / "longruns" / "stage1.py"
        assert file_to_module_path(f, tmp_path) == "longruns.stage1"

    def test_nested_subdir(self, tmp_path):
        """preprocess/first_pass.py → preprocess.first_pass"""
        f = tmp_path / "preprocess" / "first_pass.py"
        assert file_to_module_path(f, tmp_path) == "preprocess.first_pass"

    def test_deep_nested(self, tmp_path):
        """workers/gpu/inference.py → workers.gpu.inference"""
        f = tmp_path / "workers" / "gpu" / "inference.py"
        assert file_to_module_path(f, tmp_path) == "workers.gpu.inference"

    def test_no_py_extension(self, tmp_path):
        """Result does not include .py extension"""
        f = tmp_path / "worker.py"
        result = file_to_module_path(f, tmp_path)
        assert ".py" not in result

    def test_uses_dots_not_slashes(self, tmp_path):
        """Result uses dots as separators, not slashes"""
        f = tmp_path / "a" / "b" / "worker.py"
        result = file_to_module_path(f, tmp_path)
        assert "." in result
        assert "/" not in result
        assert os.sep not in result


class TestIsLbRouteHandlerField:
    """Tests that RemoteFunctionMetadata.is_lb_route_handler is set correctly."""

    def test_lb_function_with_method_and_path_is_handler(self, tmp_path):
        """An LB @remote function with method= and path= is marked as LB route handler."""
        from runpod_flash.cli.commands.build_utils.scanner import RemoteDecoratorScanner

        (tmp_path / "routes.py").write_text(
            """
from runpod_flash import CpuLiveLoadBalancer, remote

lb_config = CpuLiveLoadBalancer(name="my_lb")

@remote(lb_config, method="POST", path="/compute")
async def compute(data: dict) -> dict:
    return data
"""
        )

        scanner = RemoteDecoratorScanner(tmp_path)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 1
        assert functions[0].is_lb_route_handler is True

    def test_qb_function_is_not_handler(self, tmp_path):
        """A QB @remote function is NOT marked as LB route handler."""
        from runpod_flash.cli.commands.build_utils.scanner import RemoteDecoratorScanner

        (tmp_path / "worker.py").write_text(
            """
from runpod_flash import LiveServerless, GpuGroup, remote

gpu_config = LiveServerless(name="gpu_worker", gpus=[GpuGroup.ANY])

@remote(gpu_config)
async def process(data: dict) -> dict:
    return data
"""
        )

        scanner = RemoteDecoratorScanner(tmp_path)
        functions = scanner.discover_remote_functions()

        assert len(functions) == 1
        assert functions[0].is_lb_route_handler is False

    def test_init_py_files_excluded(self, tmp_path):
        """__init__.py files are excluded from scanning."""
        from runpod_flash.cli.commands.build_utils.scanner import RemoteDecoratorScanner

        (tmp_path / "__init__.py").write_text(
            """
from runpod_flash import LiveServerless, remote

gpu_config = LiveServerless(name="gpu_worker")

@remote(gpu_config)
async def process(data: dict) -> dict:
    return data
"""
        )
        (tmp_path / "worker.py").write_text(
            """
from runpod_flash import LiveServerless, GpuGroup, remote

gpu_config = LiveServerless(name="gpu_worker", gpus=[GpuGroup.ANY])

@remote(gpu_config)
async def process(data: dict) -> dict:
    return data
"""
        )

        scanner = RemoteDecoratorScanner(tmp_path)
        functions = scanner.discover_remote_functions()

        # Only the worker.py function should be discovered, not __init__.py
        assert len(functions) == 1
        assert functions[0].file_path.name == "worker.py"
