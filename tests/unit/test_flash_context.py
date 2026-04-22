"""tests for flash_context module."""

from pathlib import Path

from runpod_flash.flash_context import get_flash_app, get_flash_context


class TestGetFlashContext:
    def test_defaults_when_no_env(self, monkeypatch):
        monkeypatch.delenv("FLASH_APP", raising=False)
        monkeypatch.delenv("FLASH_ENV", raising=False)
        monkeypatch.delenv("FLASH_IS_LIVE_PROVISIONING", raising=False)

        app, env = get_flash_context()
        assert app == Path.cwd().name
        assert env == "production"

    def test_returns_none_when_live_provisioning(self, monkeypatch):
        monkeypatch.setenv("FLASH_IS_LIVE_PROVISIONING", "true")
        monkeypatch.setenv("FLASH_APP", "myapp")
        monkeypatch.setenv("FLASH_ENV", "prod")

        assert get_flash_context() is None

    def test_returns_context_from_env_vars(self, monkeypatch):
        monkeypatch.delenv("FLASH_IS_LIVE_PROVISIONING", raising=False)
        monkeypatch.setenv("FLASH_APP", "myapp")
        monkeypatch.setenv("FLASH_ENV", "production")

        assert get_flash_context() == ("myapp", "production")

    def test_defaults_env_when_only_app_set(self, monkeypatch):
        monkeypatch.setenv("FLASH_APP", "myapp")
        monkeypatch.delenv("FLASH_ENV", raising=False)
        monkeypatch.delenv("FLASH_IS_LIVE_PROVISIONING", raising=False)

        assert get_flash_context() == ("myapp", "production")

    def test_defaults_app_when_only_env_set(self, monkeypatch):
        monkeypatch.delenv("FLASH_APP", raising=False)
        monkeypatch.setenv("FLASH_ENV", "staging")
        monkeypatch.delenv("FLASH_IS_LIVE_PROVISIONING", raising=False)

        app, env = get_flash_context()
        assert app == Path.cwd().name
        assert env == "staging"

    def test_live_provisioning_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("FLASH_IS_LIVE_PROVISIONING", "TRUE")
        monkeypatch.setenv("FLASH_APP", "myapp")
        monkeypatch.setenv("FLASH_ENV", "prod")

        assert get_flash_context() is None


class TestGetFlashApp:
    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("FLASH_APP", "from-env")

        assert get_flash_app() == "from-env"

    def test_returns_none_when_nothing(self, monkeypatch):
        monkeypatch.delenv("FLASH_APP", raising=False)

        assert get_flash_app() is None
