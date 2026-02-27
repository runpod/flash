"""P1 gap-fill tests for uncovered test plan items.

Covers: CLI-INIT-001/002/003/004, REM-FN-005, REM-FN-006, REM-CLS-005,
        REM-VAL-003, REM-VAL-004, RES-LS-001, RES-CPU-006, RT-LB-006.
"""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# CLI-INIT-001/002/003: Skeleton templates have correct structure
# ---------------------------------------------------------------------------
class TestSkeletonTemplateStructure:
    """Validates the content of flash init skeleton templates."""

    def _get_template_dir(self):
        from runpod_flash.cli.utils.skeleton import create_project_skeleton

        return (
            Path(create_project_skeleton.__code__.co_filename).parent
            / "skeleton_template"
        )

    def test_gpu_worker_template_structure(self):
        """CLI-INIT-001: GPU worker template uses LiveServerless + GpuType."""
        template = self._get_template_dir() / "gpu_worker.py"
        content = template.read_text()

        assert "from runpod_flash import" in content
        assert "LiveServerless" in content
        assert "GpuType" in content
        assert "@remote" in content
        assert "async def gpu_hello" in content

    def test_cpu_worker_template_structure(self):
        """CLI-INIT-002: CPU worker template uses CpuLiveServerless."""
        template = self._get_template_dir() / "cpu_worker.py"
        content = template.read_text()

        assert "CpuLiveServerless" in content
        assert "@remote" in content
        assert "async def cpu_hello" in content

    def test_lb_worker_template_structure(self):
        """CLI-INIT-003: LB worker template uses method/path routing."""
        template = self._get_template_dir() / "lb_worker.py"
        content = template.read_text()

        assert "CpuLiveLoadBalancer" in content
        assert 'method="POST"' in content
        assert 'path="/process"' in content
        assert 'method="GET"' in content
        assert 'path="/health"' in content

    def test_pyproject_toml_has_runpod_flash_dependency(self):
        """CLI-INIT-004: pyproject.toml includes runpod-flash dependency."""
        template = self._get_template_dir() / "pyproject.toml"
        content = template.read_text()

        assert "runpod-flash" in content
        assert "{{project_name}}" in content

    def test_create_project_skeleton_copies_all_templates(self, tmp_path):
        """Skeleton creation copies template files to target directory."""
        from runpod_flash.cli.utils.skeleton import create_project_skeleton

        created = create_project_skeleton(tmp_path)

        assert len(created) > 0
        assert (tmp_path / "gpu_worker.py").exists()
        assert (tmp_path / "cpu_worker.py").exists()
        assert (tmp_path / "lb_worker.py").exists()
        assert (tmp_path / "pyproject.toml").exists()

    def test_project_name_substitution(self, tmp_path):
        """{{project_name}} placeholder replaced with directory name."""
        from runpod_flash.cli.utils.skeleton import create_project_skeleton

        project_dir = tmp_path / "my_cool_project"
        project_dir.mkdir()
        create_project_skeleton(project_dir)

        pyproject = (project_dir / "pyproject.toml").read_text()
        assert "my_cool_project" in pyproject
        assert "{{project_name}}" not in pyproject


# ---------------------------------------------------------------------------
# REM-FN-005: __remote_config__ stored on decorated function
# ---------------------------------------------------------------------------
class TestRemoteConfigAttribute:
    """@remote decorator stores __remote_config__ with correct fields."""

    @patch.dict(os.environ, {}, clear=True)
    def test_remote_config_stored_on_function(self):
        """REM-FN-005: __remote_config__ contains resource_config, method, path, deps."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="test-fn-config")

        @remote(resource, dependencies=["numpy"], system_dependencies=["ffmpeg"])
        async def my_func(x: int) -> int:
            return x * 2

        assert hasattr(my_func, "__remote_config__")
        config = my_func.__remote_config__
        assert config["resource_config"] is resource
        assert config["dependencies"] == ["numpy"]
        assert config["system_dependencies"] == ["ffmpeg"]
        assert config["method"] is None
        assert config["path"] is None


# ---------------------------------------------------------------------------
# REM-CLS-005: Private methods raise AttributeError
# ---------------------------------------------------------------------------
class TestRemoteClassPrivateMethods:
    """RemoteClassWrapper blocks access to private methods."""

    def test_private_method_raises_attribute_error(self):
        """REM-CLS-005: Accessing _private_method on wrapper raises AttributeError."""
        from runpod_flash.execute_class import create_remote_class

        class MyModel:
            def predict(self, data):
                return data

            def _internal(self):
                return "secret"

        mock_resource = MagicMock()
        Wrapper = create_remote_class(MyModel, mock_resource, [], [], True, {})
        instance = Wrapper()

        with pytest.raises(AttributeError, match="has no attribute '_internal'"):
            instance._internal

    def test_dunder_methods_raise_attribute_error(self):
        """Double-underscore attributes also raise AttributeError."""
        from runpod_flash.execute_class import create_remote_class

        class MyModel:
            def predict(self, data):
                return data

        mock_resource = MagicMock()
        Wrapper = create_remote_class(MyModel, mock_resource, [], [], True, {})
        instance = Wrapper()

        with pytest.raises(AttributeError):
            instance.__secret__


# ---------------------------------------------------------------------------
# REM-VAL-003: path not starting with / raises ValueError
# REM-VAL-004: Invalid HTTP method raises ValueError
# ---------------------------------------------------------------------------
class TestRemoteValidation:
    """@remote parameter validation for LB resources."""

    def test_path_without_leading_slash_raises(self):
        """REM-VAL-003: path='predict' (no leading /) raises ValueError."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import LoadBalancerSlsResource

        lb = LoadBalancerSlsResource(name="test-lb", imageName="runpod/test:latest")

        with pytest.raises(ValueError, match="must start with '/'"):

            @remote(lb, method="POST", path="predict")
            def handler(data):
                return data

    def test_invalid_http_method_raises(self):
        """REM-VAL-004: Invalid HTTP method raises ValueError."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import LoadBalancerSlsResource

        lb = LoadBalancerSlsResource(name="test-lb", imageName="runpod/test:latest")

        with pytest.raises(ValueError):

            @remote(lb, method="INVALID", path="/test")
            def handler(data):
                return data


# ---------------------------------------------------------------------------
# RES-LS-001: LiveServerless default field values
# ---------------------------------------------------------------------------
class TestLiveServerlessDefaults:
    """LiveServerless has correct default values."""

    def test_default_workers_min(self):
        """RES-LS-001: workersMin defaults to 0."""
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="defaults-test")
        assert resource.workersMin == 0

    def test_default_workers_max(self):
        """RES-LS-001: workersMax defaults to 1."""
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="defaults-test")
        assert resource.workersMax == 1

    def test_default_idle_timeout(self):
        """RES-LS-001: idleTimeout defaults to 60."""
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="defaults-test")
        assert resource.idleTimeout == 60


# ---------------------------------------------------------------------------
# SCALE-006: workersMin > workersMax validation
# ---------------------------------------------------------------------------
class TestWorkerBoundsValidation:
    """workersMin must not exceed workersMax."""

    def test_workers_min_exceeds_max_raises(self):
        """SCALE-006: workersMin > workersMax raises ValueError."""
        import pytest
        from runpod_flash.core.resources import LiveServerless

        with pytest.raises(
            ValueError, match="workersMin.*cannot be greater than.*workersMax"
        ):
            LiveServerless(name="bad-bounds", workersMin=5, workersMax=1)

    def test_workers_min_equals_max_ok(self):
        """SCALE-006: workersMin == workersMax is valid."""
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="equal-bounds", workersMin=2, workersMax=2)
        assert resource.workersMin == 2
        assert resource.workersMax == 2

    def test_workers_min_less_than_max_ok(self):
        """SCALE-006: workersMin < workersMax is valid."""
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="normal-bounds", workersMin=0, workersMax=3)
        assert resource.workersMin == 0
        assert resource.workersMax == 3

    def test_cpu_workers_min_exceeds_max_raises(self):
        """SCALE-006: Validation applies to CPU resources too."""
        import pytest
        from runpod_flash.core.resources import CpuLiveServerless

        with pytest.raises(
            ValueError, match="workersMin.*cannot be greater than.*workersMax"
        ):
            CpuLiveServerless(name="cpu-bad-bounds", workersMin=3, workersMax=1)


# ---------------------------------------------------------------------------
# RES-CPU-006: containerDiskInGb exceeding limit raises ValueError
# ---------------------------------------------------------------------------
class TestCpuDiskSizeValidation:
    """CPU container disk size validation."""

    def test_disk_exceeding_limit_raises(self):
        """RES-CPU-006: containerDiskInGb over instance limit raises ValueError."""
        from runpod_flash.core.resources import CpuLiveServerless
        from runpod_flash.core.resources.cpu import CpuInstanceType

        resource = CpuLiveServerless(
            name="disk-test",
            instanceIds=[CpuInstanceType.CPU3G_1_4],  # max 10GB
        )
        # Override disk size to exceed limit
        resource.template.containerDiskInGb = 100

        with pytest.raises(ValueError, match="exceeds the maximum"):
            resource.validate_cpu_container_disk_size()

    def test_disk_within_limit_ok(self):
        """Disk size within limit does not raise."""
        from runpod_flash.core.resources import CpuLiveServerless
        from runpod_flash.core.resources.cpu import CpuInstanceType

        resource = CpuLiveServerless(
            name="disk-ok",
            instanceIds=[CpuInstanceType.CPU3G_8_32],  # max 80GB
        )
        resource.template.containerDiskInGb = 50

        # Should not raise
        resource.validate_cpu_container_disk_size()


# ---------------------------------------------------------------------------
# REM-FN-006: Dependencies list passed through to stub call
# ---------------------------------------------------------------------------
class TestDependenciesPassedToStub:
    """@remote passes dependencies and system_dependencies to stub."""

    @patch.dict(os.environ, {}, clear=True)
    @patch("runpod_flash.client._resolve_deployed_endpoint_id", return_value=None)
    @patch("runpod_flash.client.ResourceManager")
    @patch("runpod_flash.client.stub_resource")
    @pytest.mark.asyncio
    async def test_dependencies_passed_to_stub_call(
        self, mock_stub_resource, mock_rm_cls, mock_resolve
    ):
        """REM-FN-006: dependencies list forwarded to stub invocation."""
        from runpod_flash.client import remote
        from runpod_flash.core.resources import LiveServerless

        resource = LiveServerless(name="dep-test")
        mock_rm = AsyncMock()
        mock_rm.get_or_deploy_resource.return_value = MagicMock()
        mock_rm_cls.return_value = mock_rm

        mock_stub = AsyncMock(return_value=42)
        mock_stub_resource.return_value = mock_stub

        @remote(
            resource, dependencies=["torch", "numpy"], system_dependencies=["ffmpeg"]
        )
        async def compute(x):
            return x

        await compute(5)

        # Verify stub was called with dependencies as args
        mock_stub.assert_awaited_once()
        call_args = mock_stub.call_args
        # stub(func, dependencies, system_dependencies, accelerate, *args, **kwargs)
        assert call_args[0][1] == ["torch", "numpy"]  # dependencies
        assert call_args[0][2] == ["ffmpeg"]  # system_dependencies


# ---------------------------------------------------------------------------
# RT-LB-006: Generated LB handler includes /ping endpoint
# ---------------------------------------------------------------------------
class TestLBHandlerPingEndpoint:
    """Generated LB handler template includes /ping health check."""

    def test_lb_handler_template_has_ping(self):
        """RT-LB-006: Generated LB handler includes /ping → 200 response."""
        from runpod_flash.cli.commands.build_utils.lb_handler_generator import (
            LB_HANDLER_TEMPLATE,
        )

        assert "/ping" in LB_HANDLER_TEMPLATE
        assert "def ping" in LB_HANDLER_TEMPLATE
