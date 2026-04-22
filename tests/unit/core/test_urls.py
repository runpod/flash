"""Unit tests for runpod_flash.core.urls."""

import importlib
import sys
import warnings

import pytest


def _reload_urls_module():
    """Reload core.urls so module-level env reads pick up the current env."""
    if "runpod_flash.core.urls" in sys.modules:
        del sys.modules["runpod_flash.core.urls"]
    return importlib.import_module("runpod_flash.core.urls")


class TestEnvUrlHelper:
    """Tests for the _env_url helper in core/urls.py."""

    def test_new_name_read_when_set(self, monkeypatch):
        monkeypatch.setenv("FLASH_TEST_NEW", "https://new.example.com")
        monkeypatch.delenv("FLASH_TEST_OLD", raising=False)

        from runpod_flash.core.urls import _env_url

        result = _env_url(
            "FLASH_TEST_NEW", "FLASH_TEST_OLD", "https://default.example.com"
        )
        assert result == "https://new.example.com"

    def test_old_name_fallback_emits_deprecation_warning(self, monkeypatch):
        monkeypatch.delenv("FLASH_TEST_NEW", raising=False)
        monkeypatch.setenv("FLASH_TEST_OLD", "https://old.example.com")

        from runpod_flash.core.urls import _env_url

        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            result = _env_url(
                "FLASH_TEST_NEW", "FLASH_TEST_OLD", "https://default.example.com"
            )

        assert result == "https://old.example.com"
        assert any(
            issubclass(w.category, DeprecationWarning)
            and "FLASH_TEST_OLD" in str(w.message)
            and "FLASH_TEST_NEW" in str(w.message)
            for w in captured
        )

    def test_new_wins_over_old_and_no_warning(self, monkeypatch):
        monkeypatch.setenv("FLASH_TEST_NEW", "https://new.example.com")
        monkeypatch.setenv("FLASH_TEST_OLD", "https://old.example.com")

        from runpod_flash.core.urls import _env_url

        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            result = _env_url(
                "FLASH_TEST_NEW", "FLASH_TEST_OLD", "https://default.example.com"
            )

        assert result == "https://new.example.com"
        assert not any(issubclass(w.category, DeprecationWarning) for w in captured)

    def test_default_when_neither_set(self, monkeypatch):
        monkeypatch.delenv("FLASH_TEST_NEW", raising=False)
        monkeypatch.delenv("FLASH_TEST_OLD", raising=False)

        from runpod_flash.core.urls import _env_url

        result = _env_url(
            "FLASH_TEST_NEW", "FLASH_TEST_OLD", "https://default.example.com"
        )
        assert result == "https://default.example.com"

    def test_old_none_skips_fallback(self, monkeypatch):
        monkeypatch.delenv("FLASH_TEST_NEW", raising=False)
        monkeypatch.setenv("FLASH_TEST_OLD", "https://old.example.com")

        from runpod_flash.core.urls import _env_url

        result = _env_url("FLASH_TEST_NEW", None, "https://default.example.com")
        assert result == "https://default.example.com"

    def test_trailing_slash_stripped(self, monkeypatch):
        monkeypatch.setenv("FLASH_TEST_NEW", "https://new.example.com/")

        from runpod_flash.core.urls import _env_url

        result = _env_url("FLASH_TEST_NEW", None, "https://default.example.com")
        assert result == "https://new.example.com"


class TestConsoleDeprecationShim:
    """CONSOLE_BASE_URL is the only env var with a deprecation shim today."""

    def test_new_console_url_honored(self, monkeypatch):
        monkeypatch.setenv("RUNPOD_CONSOLE_URL", "https://new-console.example.com")
        monkeypatch.delenv("CONSOLE_BASE_URL", raising=False)
        mod = _reload_urls_module()
        assert mod.RUNPOD_CONSOLE_URL == "https://new-console.example.com"

    def test_old_console_url_still_works_with_warning(self, monkeypatch):
        monkeypatch.delenv("RUNPOD_CONSOLE_URL", raising=False)
        monkeypatch.setenv("CONSOLE_BASE_URL", "https://old-console.example.com")
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            mod = _reload_urls_module()
        assert mod.RUNPOD_CONSOLE_URL == "https://old-console.example.com"
        assert any(
            issubclass(w.category, DeprecationWarning)
            and "CONSOLE_BASE_URL" in str(w.message)
            and "RUNPOD_CONSOLE_URL" in str(w.message)
            for w in captured
        )

    def test_default_console_when_neither_set(self, monkeypatch):
        monkeypatch.delenv("RUNPOD_CONSOLE_URL", raising=False)
        monkeypatch.delenv("CONSOLE_BASE_URL", raising=False)
        mod = _reload_urls_module()
        assert mod.RUNPOD_CONSOLE_URL == "https://console.runpod.io"


class TestPartialOverrideWarning:
    """A partial URL override is a common misconfiguration signal."""

    @pytest.fixture(autouse=True)
    def clear_all_url_env(self, monkeypatch):
        for name in (
            "RUNPOD_API_BASE_URL",
            "RUNPOD_ENDPOINT_BASE_URL",
            "RUNPOD_REST_API_URL",
            "RUNPOD_HAPI_URL",
            "RUNPOD_HAPI_BASE_URL",
            "RUNPOD_CONSOLE_URL",
            "CONSOLE_BASE_URL",
        ):
            monkeypatch.delenv(name, raising=False)

    @pytest.fixture
    def prod_runpod_endpoint(self, monkeypatch):
        """Pin runpod.endpoint_url_base to prod default.

        ``runpod.endpoint_url_base`` is captured once at runpod-package
        import time and never re-read, so deleting ``RUNPOD_ENDPOINT_BASE_URL``
        from the environment does not reset it. Tests that want the endpoint
        URL to look like prod must force it here; otherwise a leaked env var
        in the host shell or CI runner makes the resolved endpoint URL
        "overridden" and silently corrupts assertions.
        """
        import runpod

        monkeypatch.setattr(runpod, "endpoint_url_base", "https://api.runpod.ai/v2")

    @pytest.fixture
    def custom_runpod_endpoint(self, monkeypatch):
        """Pin runpod.endpoint_url_base to a custom dev-like URL.

        Same caching caveat as ``prod_runpod_endpoint``: setting
        ``RUNPOD_ENDPOINT_BASE_URL`` via ``monkeypatch.setenv`` is not
        sufficient because ``runpod.endpoint_url_base`` was already cached.
        """
        import runpod

        monkeypatch.setattr(
            runpod, "endpoint_url_base", "https://endpoint.custom.test/v2"
        )

    def test_no_warning_when_all_at_default(self, prod_runpod_endpoint):
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            _reload_urls_module()
        assert not any(
            issubclass(w.category, RuntimeWarning)
            and "Partial Runpod URL override" in str(w.message)
            for w in captured
        )

    def test_warning_when_partially_overridden(self, monkeypatch, prod_runpod_endpoint):
        monkeypatch.setenv("RUNPOD_API_BASE_URL", "https://api.custom.test")

        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            _reload_urls_module()

        matches = [
            w
            for w in captured
            if issubclass(w.category, RuntimeWarning)
            and "Partial Runpod URL override" in str(w.message)
        ]
        assert matches, "Expected a partial-override RuntimeWarning"
        msg = str(matches[0].message)
        overridden_section = msg.split("Overridden:")[1].split("Still at default:")[0]
        default_section = msg.split("Still at default:")[1]
        assert "RUNPOD_API_BASE_URL" in overridden_section
        for name in (
            "RUNPOD_ENDPOINT_BASE_URL",
            "RUNPOD_REST_API_URL",
            "RUNPOD_HAPI_URL",
            "RUNPOD_CONSOLE_URL",
        ):
            assert name in default_section, f"{name} miscategorized"

    def test_no_warning_when_all_overridden(self, monkeypatch, custom_runpod_endpoint):
        monkeypatch.setenv("RUNPOD_API_BASE_URL", "https://api.custom.test")
        monkeypatch.setenv(
            "RUNPOD_ENDPOINT_BASE_URL", "https://endpoint.custom.test/v2"
        )
        monkeypatch.setenv("RUNPOD_REST_API_URL", "https://rest.custom.test/v1")
        monkeypatch.setenv("RUNPOD_HAPI_URL", "https://hapi.custom.test")
        monkeypatch.setenv("RUNPOD_CONSOLE_URL", "https://console.custom.test")

        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            _reload_urls_module()
        assert not any(
            issubclass(w.category, RuntimeWarning)
            and "Partial Runpod URL override" in str(w.message)
            for w in captured
        )
