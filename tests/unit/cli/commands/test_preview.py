"""Unit tests for flash preview command."""

import json

import pytest

from unittest.mock import MagicMock, patch

from runpod_flash.cli.commands.preview import (
    CONTAINER_ARCHIVE_PATH,
    ContainerInfo,
    _assign_container_port,
    _display_preview_info,
    _load_manifest,
    _parse_resources_from_manifest,
    _verify_container_health,
)


class TestContainerInfo:
    """Tests for ContainerInfo dataclass."""

    def test_container_info_creation(self):
        """Test creating a ContainerInfo instance."""
        info = ContainerInfo(
            id="abc123",
            name="gpu_config",
            port=8001,
            is_load_balanced=False,
            url="http://localhost:8001",
        )

        assert info.id == "abc123"
        assert info.name == "gpu_config"
        assert info.port == 8001
        assert info.is_load_balanced is False
        assert info.url == "http://localhost:8001"

    def test_load_balanced_container_info(self):
        """Test creating load-balanced container info."""
        info = ContainerInfo(
            id="def456",
            name="load_balancer",
            port=8000,
            is_load_balanced=True,
            url="http://localhost:8000",
        )

        assert info.is_load_balanced is True
        assert info.port == 8000


class TestAssignContainerPort:
    """Tests for _assign_container_port function."""

    def test_load_balancer_gets_port_8000(self):
        """Test that load balancer always gets port 8000."""
        assert _assign_container_port("load_balancer", True) == 8000

    def test_gpu_config_gets_port_8001(self):
        """Test that gpu_config gets port 8001."""
        port = _assign_container_port("gpu_config", False)
        assert port == 8001

    def test_cpu_config_gets_port_8002(self):
        """Test that cpu_config gets port 8002."""
        port = _assign_container_port("cpu_config", False)
        assert port == 8002

    def test_unknown_resource_gets_deterministic_port(self):
        """Test that unknown resources get deterministic ports."""
        port1 = _assign_container_port("custom_worker", False)
        port2 = _assign_container_port("custom_worker", False)
        # Same resource name should get same port
        assert port1 == port2
        # Port should be in valid range
        assert 8000 < port1 < 8100


class TestLoadManifest:
    """Tests for _load_manifest function."""

    def test_load_valid_manifest(self, tmp_path):
        """Test loading a valid manifest file."""
        manifest = {"resources": {"gpu_config": {"functions": []}}}
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        loaded = _load_manifest(manifest_path)
        assert loaded == manifest

    def test_manifest_not_found(self, tmp_path):
        """Test error when manifest file doesn't exist."""
        import typer

        manifest_path = tmp_path / "nonexistent.json"

        with pytest.raises(typer.Exit):
            _load_manifest(manifest_path)

    def test_invalid_json(self, tmp_path):
        """Test error when manifest contains invalid JSON."""
        import typer

        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text("{ invalid json")

        with pytest.raises(typer.Exit):
            _load_manifest(manifest_path)


class TestParseResourcesFromManifest:
    """Tests for _parse_resources_from_manifest function."""

    def test_parse_empty_manifest(self):
        """Test parsing manifest with no resources creates default load balancer."""
        manifest = {"resources": {}}
        resources = _parse_resources_from_manifest(manifest)

        # Should create default load balancer when none specified
        assert "load_balancer" in resources
        assert resources["load_balancer"]["is_load_balanced"] is True

    def test_parse_manifest_with_gpu_config_creates_default_load_balancer(self):
        """Test parsing manifest with GPU resource but no load balancer."""
        manifest = {
            "resources": {
                "gpu_config": {
                    "imageName": "custom-gpu:latest",
                    "is_load_balanced": False,
                    "functions": [{"name": "gpu_fn", "module": "workers.gpu.endpoint"}],
                }
            }
        }

        resources = _parse_resources_from_manifest(manifest)

        # Should include default load balancer since none specified
        assert "load_balancer" in resources
        assert resources["load_balancer"]["is_load_balanced"] is True

        # Should include gpu_config
        assert "gpu_config" in resources
        assert resources["gpu_config"]["imageName"] == "custom-gpu:latest"
        assert resources["gpu_config"]["is_load_balanced"] is False

    def test_parse_manifest_with_explicit_load_balancer(self):
        """Test parsing manifest with explicit load balancer resource."""
        manifest = {
            "resources": {
                "my_custom_lb": {
                    "imageName": "custom-lb:latest",
                    "is_load_balanced": True,
                    "functions": [],
                },
                "gpu_config": {
                    "imageName": "gpu:latest",
                    "is_load_balanced": False,
                    "functions": [],
                },
            }
        }

        resources = _parse_resources_from_manifest(manifest)

        # Should NOT create default load balancer
        assert "load_balancer" not in resources

        # Should use explicit load balancer from manifest
        assert "my_custom_lb" in resources
        assert resources["my_custom_lb"]["is_load_balanced"] is True

        # Should include worker
        assert "gpu_config" in resources
        assert resources["gpu_config"]["is_load_balanced"] is False

    def test_parse_manifest_with_multiple_resources(self):
        """Test parsing manifest with multiple resources."""
        manifest = {
            "resources": {
                "gpu_config": {
                    "imageName": "gpu:latest",
                    "is_load_balanced": False,
                    "functions": [],
                },
                "cpu_config": {
                    "imageName": "cpu:latest",
                    "is_load_balanced": False,
                    "functions": [],
                },
            }
        }

        resources = _parse_resources_from_manifest(manifest)

        assert len(resources) == 3  # load_balancer (default) + gpu + cpu
        assert "load_balancer" in resources
        assert "gpu_config" in resources
        assert "cpu_config" in resources

    def test_parse_manifest_missing_image_name(self):
        """Test parsing resource without imageName uses default."""
        manifest = {
            "resources": {"gpu_config": {"is_load_balanced": False, "functions": []}}
        }

        resources = _parse_resources_from_manifest(manifest)

        assert "gpu_config" in resources
        # Should have a default imageName
        assert "imageName" in resources["gpu_config"]

    def test_parse_manifest_missing_is_load_balanced_defaults_false(self):
        """Test parsing resource without is_load_balanced defaults to False."""
        manifest = {
            "resources": {"gpu_config": {"imageName": "gpu:latest", "functions": []}}
        }

        resources = _parse_resources_from_manifest(manifest)

        assert "gpu_config" in resources
        assert resources["gpu_config"]["is_load_balanced"] is False
        # Should create default load balancer since none explicitly marked
        assert "load_balancer" in resources
        assert resources["load_balancer"]["is_load_balanced"] is True


class TestDisplayPreviewInfo:
    """Tests for _display_preview_info function."""

    def test_display_with_load_balancer_and_workers(self):
        """Test display with multiple containers."""
        containers = [
            ContainerInfo(
                id="abc123",
                name="load_balancer",
                port=8000,
                is_load_balanced=True,
                url="http://localhost:8000",
            ),
            ContainerInfo(
                id="def456",
                name="gpu_config",
                port=8001,
                is_load_balanced=False,
                url="http://localhost:8001",
            ),
        ]

        # Should not raise an exception
        _display_preview_info(containers)

    def test_display_sorts_load_balancer_first(self):
        """Test that display sorts load balancer first."""
        containers = [
            ContainerInfo(
                id="def456",
                name="gpu_config",
                port=8001,
                is_load_balanced=False,
                url="http://localhost:8001",
            ),
            ContainerInfo(
                id="abc123",
                name="load_balancer",
                port=8000,
                is_load_balanced=True,
                url="http://localhost:8000",
            ),
        ]

        # Should not raise an exception
        _display_preview_info(containers)

    def test_display_with_single_load_balancer(self):
        """Test display with only load balancer."""
        containers = [
            ContainerInfo(
                id="abc123",
                name="load_balancer",
                port=8000,
                is_load_balanced=True,
                url="http://localhost:8000",
            )
        ]

        # Should not raise an exception
        _display_preview_info(containers)


class TestVerifyContainerHealth:
    """Tests for _verify_container_health function."""

    @patch("runpod_flash.cli.commands.preview.subprocess.run")
    @patch("runpod_flash.cli.commands.preview.time.sleep")
    def test_container_running_succeeds(self, mock_sleep, mock_run):
        """Test that running container passes health check."""
        # Mock docker inspect to return 'running' status
        mock_run.return_value = MagicMock(
            stdout="running\n",
            stderr="",
        )

        # Should not raise
        _verify_container_health("abc123", "test_resource")
        mock_sleep.assert_called_once_with(2)

    @patch("runpod_flash.cli.commands.preview.subprocess.run")
    @patch("runpod_flash.cli.commands.preview.time.sleep")
    def test_container_exited_raises_error(self, mock_sleep, mock_run):
        """Test that exited container raises error."""
        # Mock docker inspect to return 'exited' status
        # First call returns 'exited', second call (logs) returns output
        mock_run.side_effect = [
            MagicMock(stdout="exited\n", stderr=""),
            MagicMock(stdout="Error unpacking archive", stderr=""),
        ]

        with pytest.raises(Exception, match="failed to start"):
            _verify_container_health("abc123", "test_resource")

    @patch("runpod_flash.cli.commands.preview.subprocess.run")
    @patch("runpod_flash.cli.commands.preview.time.sleep")
    def test_container_health_check_includes_logs(self, mock_sleep, mock_run):
        """Test that error message includes container logs."""
        error_log = "FileNotFoundError: artifact.tar.gz not found"
        # First call returns 'exited', second call returns logs
        mock_run.side_effect = [
            MagicMock(stdout="exited\n", stderr=""),
            MagicMock(stdout=error_log, stderr=""),
        ]

        with pytest.raises(Exception) as exc_info:
            _verify_container_health("abc123", "test_resource")

        assert error_log in str(exc_info.value)


class TestStartResourceContainer:
    """Tests for archive validation in _start_resource_container."""

    def test_archive_path_validation(self, tmp_path):
        """Test that missing archive raises FileNotFoundError."""
        from runpod_flash.cli.commands.preview import _start_resource_container

        build_dir = tmp_path / ".flash" / ".build"
        build_dir.mkdir(parents=True)

        # Archive does not exist
        resource_config = {"imageName": "test:latest"}

        with pytest.raises(FileNotFoundError, match="Archive not found"):
            _start_resource_container(
                resource_name="test",
                resource_config=resource_config,
                build_dir=build_dir,
                network="test-network",
            )

    @patch("runpod_flash.cli.commands.preview.subprocess.run")
    @patch("runpod_flash.cli.commands.preview._verify_container_health")
    def test_archive_mount_in_docker_command(self, mock_health, mock_run, tmp_path):
        """Test that archive is mounted at correct location."""
        from runpod_flash.cli.commands.preview import _start_resource_container

        build_dir = tmp_path / ".flash" / ".build"
        build_dir.mkdir(parents=True)

        # Create archive
        archive_path = tmp_path / ".flash" / "artifact.tar.gz"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_text("dummy archive")

        # Mock docker run
        mock_run.return_value = MagicMock(stdout="container123\n", stderr="")

        resource_config = {"imageName": "test:latest"}

        _start_resource_container(
            resource_name="test",
            resource_config=resource_config,
            build_dir=build_dir,
            network="test-network",
        )

        # Verify docker command includes archive mount
        command_list = mock_run.call_args.args[
            0
        ]  # First positional arg is the command list
        assert "-v" in command_list
        # Find the volume mount for archive
        v_indices = [i for i, arg in enumerate(command_list) if arg == "-v"]
        archive_mounts = [
            command_list[i + 1]
            for i in v_indices
            if "artifact.tar.gz" in command_list[i + 1]
        ]
        assert len(archive_mounts) > 0
        assert f"{CONTAINER_ARCHIVE_PATH}:ro" in archive_mounts[0]
