"""Unit tests for runpod_flash.core.urls."""

import warnings


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
