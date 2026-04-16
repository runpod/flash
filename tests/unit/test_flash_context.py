"""tests for flash_context module."""

import os
from pathlib import Path
from unittest import mock

import pytest

from runpod_flash.flash_context import (
    get_flash_context,
    get_flash_app,
    invalidate_config_cache,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """clear the lru_cache before each test."""
    invalidate_config_cache()
    yield
    invalidate_config_cache()


class TestGetFlashContext:
    def test_returns_none_when_no_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FLASH_APP", raising=False)
        monkeypatch.delenv("FLASH_ENV", raising=False)
        monkeypatch.delenv("FLASH_IS_LIVE_PROVISIONING", raising=False)

        assert get_flash_context() is None

    def test_returns_none_when_live_provisioning(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FLASH_IS_LIVE_PROVISIONING", "true")
        monkeypatch.setenv("FLASH_APP", "myapp")
        monkeypatch.setenv("FLASH_ENV", "prod")

        assert get_flash_context() is None

    def test_returns_context_from_env_vars(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FLASH_IS_LIVE_PROVISIONING", raising=False)
        monkeypatch.setenv("FLASH_APP", "myapp")
        monkeypatch.setenv("FLASH_ENV", "production")

        assert get_flash_context() == ("myapp", "production")

    def test_returns_context_from_flash_toml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FLASH_APP", raising=False)
        monkeypatch.delenv("FLASH_ENV", raising=False)
        monkeypatch.delenv("FLASH_IS_LIVE_PROVISIONING", raising=False)

        toml_path = tmp_path / "flash.toml"
        toml_path.write_text('app = "my-pipeline"\nenv = "staging"\n')

        assert get_flash_context() == ("my-pipeline", "staging")

    def test_env_var_overrides_flash_toml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FLASH_IS_LIVE_PROVISIONING", raising=False)
        monkeypatch.setenv("FLASH_ENV", "production")
        monkeypatch.delenv("FLASH_APP", raising=False)

        toml_path = tmp_path / "flash.toml"
        toml_path.write_text('app = "my-pipeline"\nenv = "staging"\n')

        assert get_flash_context() == ("my-pipeline", "production")

    def test_returns_none_when_only_app_set(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FLASH_APP", "myapp")
        monkeypatch.delenv("FLASH_ENV", raising=False)
        monkeypatch.delenv("FLASH_IS_LIVE_PROVISIONING", raising=False)

        assert get_flash_context() is None

    def test_returns_none_when_only_env_set(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FLASH_APP", raising=False)
        monkeypatch.setenv("FLASH_ENV", "prod")
        monkeypatch.delenv("FLASH_IS_LIVE_PROVISIONING", raising=False)

        assert get_flash_context() is None

    def test_live_provisioning_case_insensitive(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FLASH_IS_LIVE_PROVISIONING", "TRUE")
        monkeypatch.setenv("FLASH_APP", "myapp")
        monkeypatch.setenv("FLASH_ENV", "prod")

        assert get_flash_context() is None


class TestGetFlashApp:
    def test_from_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FLASH_APP", "from-env")

        assert get_flash_app() == "from-env"

    def test_from_flash_toml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FLASH_APP", raising=False)

        toml_path = tmp_path / "flash.toml"
        toml_path.write_text('app = "from-toml"\n')

        assert get_flash_app() == "from-toml"

    def test_returns_none_when_nothing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FLASH_APP", raising=False)

        assert get_flash_app() is None
