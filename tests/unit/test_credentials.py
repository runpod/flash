"""Unit tests for credential storage and retrieval."""

import os
from pathlib import Path
from unittest.mock import patch

from runpod_flash.core.credentials import (
    get_api_key,
    get_credentials_path,
    save_api_key,
)


class TestGetCredentialsPath:
    def test_default_path(self):
        with patch.dict(os.environ, {}, clear=True):
            path = get_credentials_path()
            assert path == Path.home() / ".config" / "runpod" / "credentials.toml"

    def test_xdg_config_home(self, tmp_path):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path)}, clear=True):
            path = get_credentials_path()
            assert path == tmp_path / "runpod" / "credentials.toml"

    def test_custom_credentials_file(self, tmp_path):
        custom = tmp_path / "custom.toml"
        with patch.dict(
            os.environ, {"RUNPOD_CREDENTIALS_FILE": str(custom)}, clear=True
        ):
            path = get_credentials_path()
            assert path == custom


class TestGetApiKey:
    def test_env_var_takes_precedence(self, tmp_path):
        creds = tmp_path / "credentials.toml"
        creds.write_text('api_key = "stored-key"\n')
        with patch.dict(
            os.environ,
            {"RUNPOD_API_KEY": "env-key", "RUNPOD_CREDENTIALS_FILE": str(creds)},
            clear=True,
        ):
            assert get_api_key() == "env-key"

    def test_falls_back_to_credentials_file(self, tmp_path):
        creds = tmp_path / "credentials.toml"
        creds.write_text('api_key = "stored-key"\n')
        with patch.dict(
            os.environ, {"RUNPOD_CREDENTIALS_FILE": str(creds)}, clear=True
        ):
            assert get_api_key() == "stored-key"

    def test_returns_none_when_nothing_set(self, tmp_path):
        creds = tmp_path / "nonexistent.toml"
        with patch.dict(
            os.environ, {"RUNPOD_CREDENTIALS_FILE": str(creds)}, clear=True
        ):
            assert get_api_key() is None

    def test_ignores_blank_env_var(self, tmp_path):
        creds = tmp_path / "credentials.toml"
        creds.write_text('api_key = "stored-key"\n')
        with patch.dict(
            os.environ,
            {"RUNPOD_API_KEY": "  ", "RUNPOD_CREDENTIALS_FILE": str(creds)},
            clear=True,
        ):
            assert get_api_key() == "stored-key"

    def test_ignores_blank_stored_key(self, tmp_path):
        creds = tmp_path / "credentials.toml"
        creds.write_text('api_key = "  "\n')
        with patch.dict(
            os.environ, {"RUNPOD_CREDENTIALS_FILE": str(creds)}, clear=True
        ):
            assert get_api_key() is None

    def test_handles_corrupt_credentials_file(self, tmp_path):
        creds = tmp_path / "credentials.toml"
        creds.write_text("not valid toml {{{{")
        with patch.dict(
            os.environ, {"RUNPOD_CREDENTIALS_FILE": str(creds)}, clear=True
        ):
            assert get_api_key() is None


class TestSaveApiKey:
    def test_creates_file_and_directories(self, tmp_path):
        creds = tmp_path / "deep" / "nested" / "credentials.toml"
        with patch.dict(
            os.environ, {"RUNPOD_CREDENTIALS_FILE": str(creds)}, clear=True
        ):
            result = save_api_key("my-new-key")
            assert result == creds
            assert creds.exists()
            assert 'api_key = "my-new-key"' in creds.read_text()

    def test_overwrites_existing_file(self, tmp_path):
        creds = tmp_path / "credentials.toml"
        creds.write_text('api_key = "old-key"\n')
        with patch.dict(
            os.environ, {"RUNPOD_CREDENTIALS_FILE": str(creds)}, clear=True
        ):
            save_api_key("new-key")
            assert 'api_key = "new-key"' in creds.read_text()

    def test_sets_restrictive_permissions(self, tmp_path):
        creds = tmp_path / "credentials.toml"
        with patch.dict(
            os.environ, {"RUNPOD_CREDENTIALS_FILE": str(creds)}, clear=True
        ):
            save_api_key("secret")
            mode = oct(creds.stat().st_mode & 0o777)
            assert mode == "0o600"
