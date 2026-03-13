"""Unit tests for credential storage and retrieval."""

import os
from pathlib import Path
from unittest.mock import patch

from runpod_flash.core.credentials import (
    get_api_key,
    get_credentials_path,
    save_api_key,
)


def _write_config_toml(path: Path, api_key: str, profile: str = "default") -> None:
    """Write a runpod-python format config.toml."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'[{profile}]\napi_key = "{api_key}"\n')


class TestGetCredentialsPath:
    def test_returns_runpod_config_path(self):
        path = get_credentials_path()
        assert path.name == "config.toml"


class TestGetApiKey:
    def test_env_var_takes_precedence(self, isolate_credentials_file):
        _write_config_toml(isolate_credentials_file, "stored-key")
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "env-key"}):
            assert get_api_key() == "env-key"

    def test_falls_back_to_credentials_file(self, isolate_credentials_file):
        _write_config_toml(isolate_credentials_file, "stored-key")
        assert get_api_key() == "stored-key"

    def test_returns_none_when_nothing_set(self):
        assert get_api_key() is None

    def test_ignores_blank_env_var(self, isolate_credentials_file):
        _write_config_toml(isolate_credentials_file, "stored-key")
        with patch.dict(os.environ, {"RUNPOD_API_KEY": "  "}):
            assert get_api_key() == "stored-key"

    def test_ignores_blank_stored_key(self, isolate_credentials_file):
        _write_config_toml(isolate_credentials_file, "  ")
        assert get_api_key() is None

    def test_handles_corrupt_credentials_file(self, isolate_credentials_file):
        isolate_credentials_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_credentials_file.write_text("not valid toml {{{{")
        assert get_api_key() is None


class TestSaveApiKey:
    def test_creates_file_and_directories(self, isolate_credentials_file):
        result = save_api_key("my-new-key")
        assert result == isolate_credentials_file
        assert isolate_credentials_file.exists()
        content = isolate_credentials_file.read_text()
        assert "my-new-key" in content

    def test_overwrites_existing_file(self, isolate_credentials_file):
        _write_config_toml(isolate_credentials_file, "old-key")
        save_api_key("new-key")
        content = isolate_credentials_file.read_text()
        assert "new-key" in content

    def test_sets_restrictive_permissions(self, isolate_credentials_file):
        save_api_key("secret")
        mode = oct(isolate_credentials_file.stat().st_mode & 0o777)
        assert mode == "0o600"
