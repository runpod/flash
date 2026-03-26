"""Tests for .runpod -> .flash state file migration."""

import cloudpickle
from pathlib import Path
from unittest.mock import patch

import pytest

from runpod_flash.core.resources import resource_manager
from runpod_flash.core.resources.resource_manager import ResourceManager


class TestStateMigration:
    """Test automatic migration of .runpod/resources.pkl to .flash/resources.pkl."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset ResourceManager singleton state between tests."""
        ResourceManager._resources = {}
        ResourceManager._resource_configs = {}
        ResourceManager._deployment_locks = {}
        ResourceManager._global_lock = None
        ResourceManager._lock_initialized = False
        ResourceManager._resources_initialized = False
        ResourceManager._instances = {}
        yield
        ResourceManager._resources = {}
        ResourceManager._resource_configs = {}
        ResourceManager._deployment_locks = {}
        ResourceManager._global_lock = None
        ResourceManager._lock_initialized = False
        ResourceManager._resources_initialized = False
        ResourceManager._instances = {}

    def test_migrates_legacy_state_file(self, tmp_path: Path):
        """Migration copies .runpod/resources.pkl to .flash/resources.pkl."""
        legacy_dir = tmp_path / ".runpod"
        legacy_dir.mkdir()
        legacy_file = legacy_dir / "resources.pkl"

        new_dir = tmp_path / ".flash"
        new_file = new_dir / "resources.pkl"

        # Write legacy state
        test_data = ({"endpoint-1": "resource-obj"}, {"endpoint-1": "config-hash"})
        with open(legacy_file, "wb") as f:
            cloudpickle.dump(test_data, f)

        with (
            patch.object(resource_manager, "FLASH_STATE_DIR", new_dir),
            patch.object(resource_manager, "RESOURCE_STATE_FILE", new_file),
            patch.object(resource_manager, "_LEGACY_STATE_DIR", legacy_dir),
            patch.object(
                resource_manager,
                "_LEGACY_STATE_FILE",
                legacy_file,
            ),
        ):
            resource_manager.migrate_legacy_state()

        assert new_file.exists()
        with open(new_file, "rb") as f:
            migrated = cloudpickle.load(f)
        assert migrated == test_data

    def test_skips_migration_when_new_state_exists(self, tmp_path: Path):
        """Migration does nothing if .flash/resources.pkl already exists."""
        legacy_dir = tmp_path / ".runpod"
        legacy_dir.mkdir()
        legacy_file = legacy_dir / "resources.pkl"

        new_dir = tmp_path / ".flash"
        new_dir.mkdir()
        new_file = new_dir / "resources.pkl"

        # Write both files with different data
        legacy_data = ({"old": "data"}, {})
        new_data = ({"new": "data"}, {})

        with open(legacy_file, "wb") as f:
            cloudpickle.dump(legacy_data, f)
        with open(new_file, "wb") as f:
            cloudpickle.dump(new_data, f)

        with (
            patch.object(resource_manager, "FLASH_STATE_DIR", new_dir),
            patch.object(resource_manager, "RESOURCE_STATE_FILE", new_file),
            patch.object(resource_manager, "_LEGACY_STATE_DIR", legacy_dir),
            patch.object(
                resource_manager,
                "_LEGACY_STATE_FILE",
                legacy_file,
            ),
        ):
            resource_manager.migrate_legacy_state()

        # New file should be unchanged
        with open(new_file, "rb") as f:
            result = cloudpickle.load(f)
        assert result == new_data

    def test_skips_migration_when_no_legacy_state(self, tmp_path: Path):
        """Migration does nothing if .runpod/resources.pkl does not exist."""
        legacy_dir = tmp_path / ".runpod"
        legacy_file = legacy_dir / "resources.pkl"

        new_dir = tmp_path / ".flash"
        new_file = new_dir / "resources.pkl"

        with (
            patch.object(resource_manager, "FLASH_STATE_DIR", new_dir),
            patch.object(resource_manager, "RESOURCE_STATE_FILE", new_file),
            patch.object(resource_manager, "_LEGACY_STATE_DIR", legacy_dir),
            patch.object(
                resource_manager,
                "_LEGACY_STATE_FILE",
                legacy_file,
            ),
        ):
            resource_manager.migrate_legacy_state()

        assert not new_file.exists()
