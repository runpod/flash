"""Unit tests for ResourceDiscovery."""

import pytest
from textwrap import dedent

from runpod_flash.core.discovery import ResourceDiscovery, _SKIP_DIRS
from runpod_flash.core.resources.serverless import ServerlessResource


def _worker_source(resource_name: str, var_prefix: str = "cfg") -> str:
    """Generate a Python source file with a single @remote-decorated function."""
    return dedent(f"""\
        from runpod_flash.client import remote
        from runpod_flash.core.resources.serverless import ServerlessResource

        {var_prefix}_config = ServerlessResource(
            name="{resource_name}",
            gpuCount=1,
            workersMax=3,
            workersMin=0,
            flashboot=False,
        )

        @remote(resource_config={var_prefix}_config)
        async def {var_prefix}_task():
            return "{resource_name}"
    """)


class TestResourceDiscovery:
    """Test ResourceDiscovery functionality."""

    @pytest.fixture
    def temp_entry_point(self, tmp_path):
        """Create temporary entry point file for testing."""
        entry_file = tmp_path / "main.py"
        return entry_file

    @pytest.fixture
    def sample_resource_config(self):
        """Create sample resource config for testing."""
        return ServerlessResource(
            name="test-gpu",
            gpuCount=1,
            workersMax=3,
            workersMin=0,
            flashboot=False,
        )

    def test_discover_no_remote_decorators(self, temp_entry_point):
        """Test discovery when no @remote decorators exist."""
        temp_entry_point.write_text(
            dedent(
                """
                from fastapi import FastAPI

                app = FastAPI()

                @app.get("/")
                def root():
                    return {"message": "Hello"}
                """
            )
        )

        discovery = ResourceDiscovery(str(temp_entry_point))
        resources = discovery.discover()

        assert resources == []

    def test_discover_single_remote_decorator(self, temp_entry_point):
        """Test discovery of single @remote decorator."""
        temp_entry_point.write_text(
            dedent(
                """
                from runpod_flash.client import remote
                from runpod_flash.core.resources.serverless import ServerlessResource

                gpu_config = ServerlessResource(
                    name="test-gpu",
                    gpuCount=1,
                    workersMax=3,
                    workersMin=0,
                    flashboot=False,
                )

                @remote(resource_config=gpu_config)
                async def gpu_task():
                    return "result"
                """
            )
        )

        discovery = ResourceDiscovery(str(temp_entry_point))
        resources = discovery.discover()

        assert len(resources) == 1
        assert isinstance(resources[0], ServerlessResource)
        assert resources[0].name == "test-gpu"

    def test_discover_multiple_remote_decorators(self, temp_entry_point):
        """Test discovery of multiple @remote decorators."""
        temp_entry_point.write_text(
            dedent(
                """
                from runpod_flash.client import remote
                from runpod_flash.core.resources.serverless import ServerlessResource

                gpu_config = ServerlessResource(
                    name="gpu-endpoint",
                    gpuCount=1,
                    workersMax=3,
                    workersMin=0,
                    flashboot=False,
                )

                cpu_config = ServerlessResource(
                    name="cpu-endpoint",
                    gpuCount=0,
                    workersMax=5,
                    workersMin=1,
                    flashboot=False,
                )

                @remote(resource_config=gpu_config)
                async def gpu_task():
                    return "gpu result"

                @remote(resource_config=cpu_config)
                async def cpu_task():
                    return "cpu result"
                """
            )
        )

        discovery = ResourceDiscovery(str(temp_entry_point))
        resources = discovery.discover()

        assert len(resources) == 2
        names = {r.name for r in resources}
        assert names == {"gpu-endpoint", "cpu-endpoint"}

    def test_discover_positional_argument(self, temp_entry_point):
        """Test discovery with positional argument @remote(config)."""
        temp_entry_point.write_text(
            dedent(
                """
                from runpod_flash.client import remote
                from runpod_flash.core.resources.serverless import ServerlessResource

                my_config = ServerlessResource(
                    name="test-endpoint",
                    gpuCount=1,
                    workersMax=3,
                    workersMin=0,
                    flashboot=False,
                )

                @remote(my_config)
                async def my_task():
                    return "result"
                """
            )
        )

        discovery = ResourceDiscovery(str(temp_entry_point))
        resources = discovery.discover()

        assert len(resources) == 1
        assert resources[0].name == "test-endpoint"

    def test_discover_invalid_import(self, temp_entry_point):
        """Test discovery handles invalid imports gracefully."""
        temp_entry_point.write_text(
            dedent(
                """
                import nonexistent_module

                from runpod_flash.client import remote
                """
            )
        )

        discovery = ResourceDiscovery(str(temp_entry_point))
        resources = discovery.discover()

        # Should handle import error gracefully
        assert isinstance(resources, list)

    def test_discover_cache(self, temp_entry_point):
        """Test that discovery results are cached."""
        temp_entry_point.write_text(
            dedent(
                """
                from runpod_flash.client import remote
                from runpod_flash.core.resources.serverless import ServerlessResource

                config = ServerlessResource(
                    name="cached-endpoint",
                    gpuCount=1,
                    workersMax=3,
                    workersMin=0,
                    flashboot=False,
                )

                @remote(config)
                async def task():
                    return "result"
                """
            )
        )

        discovery = ResourceDiscovery(str(temp_entry_point))

        # First call
        resources1 = discovery.discover()
        assert len(resources1) == 1

        # Second call should use cache
        resources2 = discovery.discover()
        assert resources1 == resources2

    def test_clear_cache(self, temp_entry_point):
        """Test clearing discovery cache."""
        temp_entry_point.write_text(
            dedent(
                """
                from runpod_flash.client import remote
                from runpod_flash.core.resources.serverless import ServerlessResource

                config = ServerlessResource(
                    name="test-endpoint",
                    gpuCount=1,
                    workersMax=3,
                    workersMin=0,
                    flashboot=False,
                )

                @remote(config)
                async def task():
                    return "result"
                """
            )
        )

        discovery = ResourceDiscovery(str(temp_entry_point))
        resources = discovery.discover()
        assert len(resources) == 1

        # Clear cache
        discovery.clear_cache()
        assert discovery._cache == {}

    def test_discover_with_syntax_error(self, temp_entry_point):
        """Test discovery handles syntax errors gracefully."""
        temp_entry_point.write_text(
            dedent(
                """
                def invalid_syntax(
                    # Missing closing parenthesis
                """
            )
        )

        discovery = ResourceDiscovery(str(temp_entry_point))
        resources = discovery.discover()

        # Should handle parse error gracefully
        assert isinstance(resources, list)

    def test_discover_non_deployable_resource(self, temp_entry_point):
        """Test discovery skips non-DeployableResource objects."""
        temp_entry_point.write_text(
            dedent(
                """
                from runpod_flash.client import remote

                # Not a DeployableResource
                config = {"name": "not-a-resource"}

                @remote(resource_config=config)
                async def task():
                    return "result"
                """
            )
        )

        discovery = ResourceDiscovery(str(temp_entry_point))
        resources = discovery.discover()

        # Should skip non-DeployableResource
        assert resources == []

    def test_max_depth_limiting(self, tmp_path):
        """Test that recursive scanning respects max_depth."""
        # Create nested module structure
        entry_file = tmp_path / "main.py"
        level1_file = tmp_path / "level1.py"
        level2_file = tmp_path / "level2.py"
        level3_file = tmp_path / "level3.py"

        entry_file.write_text("import level1")
        level1_file.write_text("import level2")
        level2_file.write_text("import level3")
        level3_file.write_text("# Too deep")

        discovery = ResourceDiscovery(str(entry_file), max_depth=2)
        resources = discovery.discover()

        # Should respect max_depth and not crash
        assert isinstance(resources, list)

    def test_discover_with_directory_scan(self, tmp_path):
        """Test directory scanning fallback for dynamic imports."""
        # Create entry point without @remote decorators
        entry_file = tmp_path / "main.py"
        entry_file.write_text(
            dedent(
                """
                # Dynamic imports using importlib.util
                import importlib.util
                """
            )
        )

        # Create worker file in subdirectory with @remote decorator
        workers_dir = tmp_path / "workers"
        workers_dir.mkdir()
        worker_file = workers_dir / "gpu_worker.py"
        worker_file.write_text(
            dedent(
                """
                from runpod_flash.client import remote
                from runpod_flash.core.resources.serverless import ServerlessResource

                gpu_config = ServerlessResource(
                    name="test-gpu-worker",
                    gpuCount=1,
                    workersMax=3,
                    workersMin=0,
                    flashboot=False,
                )

                @remote(resource_config=gpu_config)
                async def gpu_task():
                    return "result"
                """
            )
        )

        discovery = ResourceDiscovery(str(entry_file))
        resources = discovery.discover()

        # Should find resource via directory scanning
        assert len(resources) == 1
        assert resources[0].name == "test-gpu-worker"


class TestDiscoverDirectory:
    """Tests for ResourceDiscovery.discover_directory single-pass scanning."""

    def test_single_file_with_remote(self, tmp_path):
        """Finds a resource from a single file in the directory."""
        (tmp_path / "worker.py").write_text(_worker_source("alpha"))

        resources = ResourceDiscovery.discover_directory(tmp_path)

        assert len(resources) == 1
        assert resources[0].name == "alpha"

    def test_multiple_files_different_resources(self, tmp_path):
        """Finds distinct resources across multiple files."""
        (tmp_path / "worker_a.py").write_text(_worker_source("alpha"))
        (tmp_path / "worker_b.py").write_text(_worker_source("bravo"))

        resources = ResourceDiscovery.discover_directory(tmp_path)

        assert len(resources) == 2
        names = {r.name for r in resources}
        assert names == {"alpha", "bravo"}

    def test_deduplicates_same_resource_across_files(self, tmp_path):
        """Identical resource configs in two files are returned once."""
        # Both files define a resource with the same name and fields,
        # producing the same resource_id hash.
        (tmp_path / "a.py").write_text(_worker_source("shared", var_prefix="a"))
        (tmp_path / "b.py").write_text(_worker_source("shared", var_prefix="b"))

        resources = ResourceDiscovery.discover_directory(tmp_path)

        assert len(resources) == 1
        assert resources[0].name == "shared"

    def test_skips_files_without_decorators(self, tmp_path):
        """Files without @remote or Endpoint( are skipped entirely."""
        (tmp_path / "utils.py").write_text("def helper(): return 42\n")
        (tmp_path / "worker.py").write_text(_worker_source("found"))

        resources = ResourceDiscovery.discover_directory(tmp_path)

        assert len(resources) == 1
        assert resources[0].name == "found"

    def test_skips_venv_and_hidden_dirs(self, tmp_path):
        """Files inside _SKIP_DIRS are not scanned."""
        # Resource inside .venv should be ignored
        venv_dir = tmp_path / ".venv" / "lib"
        venv_dir.mkdir(parents=True)
        (venv_dir / "worker.py").write_text(_worker_source("hidden"))

        # Resource in project root should be found
        (tmp_path / "worker.py").write_text(_worker_source("visible"))

        resources = ResourceDiscovery.discover_directory(tmp_path)

        assert len(resources) == 1
        assert resources[0].name == "visible"

    @pytest.mark.parametrize("skip_dir", sorted(_SKIP_DIRS))
    def test_all_skip_dirs_are_excluded(self, tmp_path, skip_dir):
        """Every directory in _SKIP_DIRS is actually skipped."""
        nested = tmp_path / skip_dir / "sub"
        nested.mkdir(parents=True)
        (nested / "worker.py").write_text(_worker_source("should-skip"))

        resources = ResourceDiscovery.discover_directory(tmp_path)

        assert resources == []

    def test_empty_directory(self, tmp_path):
        """Returns empty list for directory with no Python files."""
        resources = ResourceDiscovery.discover_directory(tmp_path)

        assert resources == []

    def test_nested_subdirectory(self, tmp_path):
        """Finds resources in nested subdirectories."""
        deep = tmp_path / "pkg" / "workers"
        deep.mkdir(parents=True)
        (deep / "gpu.py").write_text(_worker_source("deep-worker"))

        resources = ResourceDiscovery.discover_directory(tmp_path)

        assert len(resources) == 1
        assert resources[0].name == "deep-worker"

    def test_syntax_error_file_skipped_gracefully(self, tmp_path):
        """A file with a syntax error doesn't break scanning of other files."""
        (tmp_path / "broken.py").write_text("@remote(\ndef broken(")
        (tmp_path / "good.py").write_text(_worker_source("survivor"))

        resources = ResourceDiscovery.discover_directory(tmp_path)

        assert len(resources) == 1
        assert resources[0].name == "survivor"

    def test_non_deployable_resource_skipped(self, tmp_path):
        """Variables that aren't DeployableResource instances are excluded."""
        (tmp_path / "fake.py").write_text(
            dedent("""\
                from runpod_flash.client import remote

                config = {"name": "not-a-resource"}

                @remote(resource_config=config)
                async def task():
                    return "result"
            """)
        )

        resources = ResourceDiscovery.discover_directory(tmp_path)

        assert resources == []

    def test_reproduces_original_bug_three_files_one_resource(self, tmp_path):
        """Regression: project with 3 files and 1 resource returns exactly 1.

        Before the fix, each file triggered an independent discovery pass,
        and files without @remote fell back to directory scanning, causing
        the same resource to appear once per non-remote file.
        """
        (tmp_path / "main.py").write_text("import importlib.util\n")
        (tmp_path / "utils.py").write_text("def helper(): pass\n")

        workers_dir = tmp_path / "workers"
        workers_dir.mkdir()
        (workers_dir / "gpu.py").write_text(_worker_source("the-one"))

        resources = ResourceDiscovery.discover_directory(tmp_path)

        assert len(resources) == 1
        assert resources[0].name == "the-one"

    def test_duplicate_stems_resolved_independently(self, tmp_path):
        """Files with the same stem in different dirs don't collide in sys.modules."""
        pkg_a = tmp_path / "pkg_a"
        pkg_b = tmp_path / "pkg_b"
        pkg_a.mkdir()
        pkg_b.mkdir()

        (pkg_a / "worker.py").write_text(_worker_source("alpha", var_prefix="a"))
        (pkg_b / "worker.py").write_text(_worker_source("bravo", var_prefix="b"))

        resources = ResourceDiscovery.discover_directory(tmp_path)

        assert len(resources) == 2
        names = {r.name for r in resources}
        assert names == {"alpha", "bravo"}
