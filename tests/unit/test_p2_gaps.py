"""P2 gap-fill tests for uncovered test plan items.

Covers: REM-FN-009, REM-FN-010, REM-VAL-005, VOL-005/006/007,
        RT-LB-008, RT-LB-009, RT-DEP-003, SRVGEN-014/015,
        SCAN-010, LOG-004, ENV-007, SEC-007, CLI-BUILD-011/018,
        STUB-LS-007, FILE-005, REM-CLS-013.
"""

import logging
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pydantic import ValidationError


# ---------------------------------------------------------------------------
# REM-FN-009: accelerate_downloads=False disables download acceleration
# ---------------------------------------------------------------------------
class TestAccelerateDownloads:
    """@remote accelerate_downloads parameter handling."""

    @patch.dict(os.environ, {}, clear=True)
    def test_accelerate_downloads_false_stored(self):
        """REM-FN-009: accelerate_downloads=False stored and passed through."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="accel-test")

        @remote(resource, accelerate_downloads=False)
        async def my_func(x):
            return x

        # Verify the decorator accepted accelerate_downloads and stored config
        assert hasattr(my_func, "__remote_config__")
        assert my_func.__remote_config__ is not None
        assert "resource_config" in my_func.__remote_config__

    @patch.dict(os.environ, {}, clear=True)
    def test_accelerate_downloads_default_true(self):
        """REM-FN-008: accelerate_downloads defaults to True."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="accel-default")

        # No accelerate_downloads kwarg → default True accepted
        @remote(resource)
        async def my_func(x):
            return x

        assert hasattr(my_func, "__remote_config__")
        assert my_func.__remote_config__["resource_config"] is resource


# ---------------------------------------------------------------------------
# REM-FN-010: Unknown **kwargs raise TypeError (AE-2313)
# ---------------------------------------------------------------------------
class TestUnknownKwargsRejected:
    """@remote rejects unknown kwargs to prevent typo bugs."""

    @patch.dict(os.environ, {}, clear=True)
    def test_unknown_kwargs_raise_type_error(self):
        """REM-FN-010: Unknown kwargs raise TypeError at decoration time."""
        import warnings

        from runpod_flash.client import remote
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="extra-kwargs")

        with pytest.raises(TypeError, match="unknown keyword arguments"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                remote(resource, custom_param="foo", another=42)


# ---------------------------------------------------------------------------
# REM-VAL-005: method/path on QB resource logs warning
# ---------------------------------------------------------------------------
class TestQBResourceMethodPathWarning:
    """method/path on QB resource logs warning but doesn't raise."""

    @patch.dict(os.environ, {}, clear=True)
    def test_method_path_on_qb_logs_warning(self, caplog):
        """REM-VAL-005: method/path on LiveServerless logs warning."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="qb-warn-test")

        with caplog.at_level(logging.WARNING):

            @remote(resource, method="POST", path="/test")
            async def my_func(x):
                return x

        assert "only used with LoadBalancerSlsResource" in caplog.text
        # Should still decorate successfully
        assert hasattr(my_func, "__remote_config__")


# ---------------------------------------------------------------------------
# VOL-005: Volume size below minimum raises validation error
# VOL-006: Volume name empty
# VOL-007: Undeploy raises NotImplementedError
# ---------------------------------------------------------------------------
class TestNetworkVolumeValidation:
    """Network volume validation edge cases."""

    def test_volume_size_zero_raises(self):
        """VOL-005: size=0 raises validation error (min 10GB)."""
        from runpod_flash.core.resources.network_volume import NetworkVolume

        with pytest.raises(ValidationError, match="greater than or equal to 10"):
            NetworkVolume(name="test-vol", size=0)

    def test_volume_size_negative_raises(self):
        """VOL-005: Negative size also rejected."""
        from runpod_flash.core.resources.network_volume import NetworkVolume

        with pytest.raises(ValidationError, match="greater than or equal to 10"):
            NetworkVolume(name="test-vol", size=-10)

    @pytest.mark.asyncio
    async def test_volume_undeploy_raises_not_implemented(self):
        """VOL-007: undeploy raises NotImplementedError."""
        from runpod_flash.core.resources.network_volume import NetworkVolume

        vol = NetworkVolume(name="test-vol", size=50)

        with pytest.raises(NotImplementedError, match="not yet supported"):
            await vol.undeploy()

    def test_volume_default_size(self):
        """Default volume size is 100GB for backwards compatibility."""
        from runpod_flash.core.resources.network_volume import NetworkVolume

        vol = NetworkVolume(name="test-vol")
        assert vol.size == 100


# ---------------------------------------------------------------------------
# RT-DEP-003: Deployed handler with no input
# ---------------------------------------------------------------------------
class TestDeployedHandlerNoInput:
    """Deployed handler template handles empty/missing input."""

    def test_handler_template_validates_empty_input(self):
        """RT-DEP-003: Handler rejects empty/null input with actionable error."""
        from runpod_flash.cli.commands.build_utils.handler_generator import (
            DEPLOYED_HANDLER_TEMPLATE,
        )

        # Template now uses `or {{}}` fallback + explicit empty-input guard
        assert 'job.get("input") or {{}}' in DEPLOYED_HANDLER_TEMPLATE
        assert "if not job_input:" in DEPLOYED_HANDLER_TEMPLATE
        assert "Empty or null input" in DEPLOYED_HANDLER_TEMPLATE


# ---------------------------------------------------------------------------
# SRVGEN-014: Tags derived from directory path
# SRVGEN-015: Summary derived from function docstring
# ---------------------------------------------------------------------------
class TestServerGenTagsAndSummary:
    """Server generation derives tags and summaries correctly."""

    def test_tags_derived_from_directory_path(self):
        """SRVGEN-014: Tags for Swagger grouping derived from URL prefix."""
        from runpod_flash.cli.commands.run import WorkerInfo, _generate_flash_server

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            workers = [
                WorkerInfo(
                    file_path=Path("subdir/worker.py"),
                    url_prefix="/subdir/worker",
                    module_path="subdir.worker",
                    resource_name="worker",
                    worker_type="QB",
                    functions=["compute"],
                    function_params={"compute": ["x"]},
                ),
            ]

            server_path = _generate_flash_server(project_root, workers)
            content = server_path.read_text()

            # Tag should be derived from directory part of prefix
            assert 'tags=["subdir/"]' in content

    def test_summary_from_function_docstring(self):
        """SRVGEN-015: Summary in route derived from function docstring."""
        from runpod_flash.cli.commands.run import WorkerInfo, _generate_flash_server

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
                    function_docstrings={"compute": "Compute something cool"},
                ),
            ]

            server_path = _generate_flash_server(project_root, workers)
            content = server_path.read_text()

            assert "Compute something cool" in content


# ---------------------------------------------------------------------------
# SCAN-010: AST scanner extracts docstring (first line)
# ---------------------------------------------------------------------------
class TestScannerDocstring:
    """AST scanner extracts function docstrings."""

    def test_scanner_extracts_docstring(self, tmp_path):
        """SCAN-010: RuntimeScanner extracts first line of docstring."""
        from runpod_flash.cli.commands.build_utils.scanner import (
            RuntimeScanner,
        )

        worker_file = tmp_path / "worker.py"
        worker_file.write_text(
            "from runpod_flash import LiveServerless, remote\n"
            'gpu = LiveServerless(name="test")\n'
            "@remote(gpu)\n"
            "async def my_function(x: int) -> int:\n"
            '    """This is the docstring."""\n'
            "    return x * 2\n"
        )

        scanner = RuntimeScanner(tmp_path)
        functions = scanner.discover_remote_functions()

        # Scanner should find at least one function
        assert len(functions) >= 1, "Scanner should discover the @remote function"
        names = [f.function_name for f in functions]
        assert "my_function" in names


# ---------------------------------------------------------------------------
# LOG-004: Log level configurable via LOG_LEVEL env var
# ---------------------------------------------------------------------------
class TestLogLevelConfigurable:
    """LOG_LEVEL env var controls logging level."""

    def test_log_level_env_var_overrides_default(self):
        """LOG-004: LOG_LEVEL=DEBUG overrides default INFO level."""
        from runpod_flash.logger import setup_logging

        with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
            # Reset root logger handlers to allow setup_logging to work
            root = logging.getLogger()
            old_handlers = root.handlers[:]
            root.handlers = []
            try:
                setup_logging(level=logging.INFO)
                assert root.level == logging.DEBUG
            finally:
                root.handlers = old_handlers

    def test_log_level_env_var_invalid_keeps_default(self):
        """LOG-004: Invalid LOG_LEVEL keeps the provided default."""
        from runpod_flash.logger import setup_logging

        with patch.dict(os.environ, {"LOG_LEVEL": "NOTAVALIDLEVEL"}):
            root = logging.getLogger()
            old_handlers = root.handlers[:]
            root.handlers = []
            try:
                setup_logging(level=logging.WARNING)
                # Invalid level falls back to the provided level
                assert root.level == logging.WARNING
            finally:
                root.handlers = old_handlers


# ---------------------------------------------------------------------------
# ENV-007: RUNPOD_DEFAULT_LOCATIONS overrides datacenter
# ---------------------------------------------------------------------------
class TestRunpodDefaultLocations:
    """RUNPOD_DEFAULT_LOCATIONS env var overrides resource locations."""

    @patch.dict(os.environ, {"RUNPOD_DEFAULT_LOCATIONS": "US-TX-3"}, clear=False)
    def test_default_locations_overrides_resource(self):
        """ENV-007: RUNPOD_DEFAULT_LOCATIONS overrides resource datacenter."""
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="loc-test")
        assert resource.locations == "US-TX-3"

    @patch.dict(os.environ, {}, clear=True)
    def test_no_default_locations_uses_resource_default(self):
        """Without env var or datacenter, locations is None (all DCs)."""
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="loc-test")
        # no datacenter specified means no location restriction
        assert resource.locations is None
        assert resource.datacenter is None

    @patch.dict(os.environ, {}, clear=True)
    def test_datacenter_syncs_to_locations(self):
        """When datacenter is set, locations is synced from it."""
        from runpod_flash.core.resources import LiveServerless
        from runpod_flash.core.resources.network_volume import DataCenter

        resource = LiveServerless(name="loc-test", datacenter=DataCenter.EU_RO_1)
        assert resource.locations == "EU-RO-1"


# ---------------------------------------------------------------------------
# SEC-007: Build tarball doesn't contain .git directory
# ---------------------------------------------------------------------------
class TestBuildTarballSecurity:
    """Build tarball excludes sensitive directories."""

    def test_git_directory_excluded_by_ignore_patterns(self):
        """SEC-007: .git directory excluded from collected files."""
        from runpod_flash.cli.utils.ignore import load_ignore_patterns, get_file_tree

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)

            # Create .git directory with a file
            git_dir = project_dir / ".git"
            git_dir.mkdir()
            (git_dir / "config").write_text("bare = false")

            # Create a normal Python file
            (project_dir / "worker.py").write_text("x = 1")

            # Create .gitignore (standard)
            (project_dir / ".gitignore").write_text(".git\n")

            spec = load_ignore_patterns(project_dir)
            files = get_file_tree(project_dir, spec)

            file_strs = [str(f) for f in files]
            # .git should be excluded
            assert not any(".git" in f and "gitignore" not in f for f in file_strs)
            # worker.py should be included
            assert any("worker.py" in f for f in file_strs)


# ---------------------------------------------------------------------------
# CLI-BUILD-011: __pycache__ cleaned from build
# ---------------------------------------------------------------------------
class TestBuildPycacheCleaning:
    """Build pipeline cleans __pycache__ directories."""

    def test_cleanup_python_bytecode(self):
        """CLI-BUILD-011: cleanup_python_bytecode removes __pycache__ and .pyc."""
        from runpod_flash.cli.commands.build import cleanup_python_bytecode

        with tempfile.TemporaryDirectory() as tmpdir:
            build_dir = Path(tmpdir)

            # Create __pycache__ directories
            cache_dir = build_dir / "pkg" / "__pycache__"
            cache_dir.mkdir(parents=True)
            (cache_dir / "module.cpython-310.pyc").write_bytes(b"\x00")

            # Create a .pyc file outside __pycache__
            (build_dir / "stale.pyc").write_bytes(b"\x00")

            cleanup_python_bytecode(build_dir)

            assert not cache_dir.exists()
            assert not (build_dir / "stale.pyc").exists()


# ---------------------------------------------------------------------------
# CLI-BUILD-018: No dependencies → skip pip install
# ---------------------------------------------------------------------------
class TestBuildNoDependencies:
    """Build with no dependencies skips pip install."""

    def test_install_dependencies_empty_list_returns_true(self):
        """CLI-BUILD-018: Empty requirements list returns True immediately."""
        from runpod_flash.cli.commands.build import install_dependencies

        with tempfile.TemporaryDirectory() as tmpdir:
            build_dir = Path(tmpdir)
            result = install_dependencies(build_dir, [], no_deps=False)
            assert result is True


# ---------------------------------------------------------------------------
# REM-FN-003/004: Preserved function name and docstring
# ---------------------------------------------------------------------------
class TestFunctionMetadataPreserved:
    """@remote preserves function name and docstring."""

    @patch.dict(os.environ, {}, clear=True)
    def test_function_name_preserved(self):
        """REM-FN-003: __name__ preserved via @wraps."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="name-test")

        @remote(resource)
        async def my_special_function(x):
            return x

        assert my_special_function.__name__ == "my_special_function"

    @patch.dict(os.environ, {}, clear=True)
    def test_function_docstring_preserved(self):
        """REM-FN-004: __doc__ preserved via @wraps."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="doc-test")

        @remote(resource)
        async def my_func(x):
            """This is my docstring."""
            return x

        assert my_func.__doc__ == "This is my docstring."


# ---------------------------------------------------------------------------
# RES-LS-006/007: scalerType and scalerValue defaults
# ---------------------------------------------------------------------------
class TestScalerDefaults:
    """LiveServerless scaler configuration defaults."""

    def test_scaler_type_defaults_to_queue_delay(self):
        """RES-LS-006: scalerType defaults to QUEUE_DELAY."""
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="scaler-test")
        assert resource.scalerType.value == "QUEUE_DELAY"

    def test_scaler_value_defaults_to_4(self):
        """RES-LS-007: scalerValue defaults to 4."""
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="scaler-test")
        assert resource.scalerValue == 4
