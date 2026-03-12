"""Tests for legacy XDG credential migration."""

from pathlib import Path
from unittest.mock import patch

from runpod_flash.core.credentials import (
    check_and_migrate_legacy_credentials,
    get_api_key,
)


def _write_old_xdg_creds(path: Path, api_key: str) -> None:
    """Write credentials in old flash format (flat TOML, no profile)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'api_key = "{api_key}"\n')


def _write_config_toml(path: Path, api_key: str) -> None:
    """Write credentials in runpod-python format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'[default]\napi_key = "{api_key}"\n')


class TestLegacyMigration:
    def test_migrates_old_xdg_credentials(self, tmp_path, isolate_credentials_file):
        old_path = tmp_path / ".config" / "runpod" / "credentials.toml"
        _write_old_xdg_creds(old_path, "legacy-key")

        with patch(
            "runpod_flash.core.credentials._OLD_XDG_PATHS",
            (old_path,),
        ):
            check_and_migrate_legacy_credentials()

        assert not old_path.exists()
        assert get_api_key() == "legacy-key"

    def test_skips_migration_when_new_file_has_key(
        self, tmp_path, isolate_credentials_file
    ):
        old_path = tmp_path / ".config" / "runpod" / "credentials.toml"
        _write_old_xdg_creds(old_path, "old-key")
        _write_config_toml(isolate_credentials_file, "new-key")

        with patch(
            "runpod_flash.core.credentials._OLD_XDG_PATHS",
            (old_path,),
        ):
            check_and_migrate_legacy_credentials()

        assert old_path.exists()
        assert get_api_key() == "new-key"

    def test_skips_when_no_old_file(self):
        check_and_migrate_legacy_credentials()

    def test_skips_when_old_file_has_blank_key(self, tmp_path, isolate_credentials_file):
        old_path = tmp_path / ".config" / "runpod" / "credentials.toml"
        _write_old_xdg_creds(old_path, "  ")

        with patch(
            "runpod_flash.core.credentials._OLD_XDG_PATHS",
            (old_path,),
        ):
            check_and_migrate_legacy_credentials()

        assert old_path.exists()

    def test_skips_when_old_file_is_corrupt(self, tmp_path, isolate_credentials_file):
        old_path = tmp_path / ".config" / "runpod" / "credentials.toml"
        old_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.write_text("not valid toml {{{{")

        with patch(
            "runpod_flash.core.credentials._OLD_XDG_PATHS",
            (old_path,),
        ):
            check_and_migrate_legacy_credentials()

        assert old_path.exists()

    def test_cleans_up_empty_parent_directory(self, tmp_path, isolate_credentials_file):
        old_dir = tmp_path / ".config" / "runpod"
        old_path = old_dir / "credentials.toml"
        _write_old_xdg_creds(old_path, "legacy-key")

        with patch(
            "runpod_flash.core.credentials._OLD_XDG_PATHS",
            (old_path,),
        ):
            check_and_migrate_legacy_credentials()

        assert not old_path.exists()
        assert not old_dir.exists()
