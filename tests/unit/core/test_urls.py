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


@pytest.fixture
def prod_runpod_endpoint(monkeypatch):
    """Pin runpod.endpoint_url_base to the prod default.

    ``runpod.endpoint_url_base`` is captured once at runpod-package import
    time and never re-read, so deleting ``RUNPOD_ENDPOINT_BASE_URL`` from
    the environment does not reset it. Tests that want the endpoint URL to
    look like prod must force it here; otherwise a leaked env var in the
    host shell or CI runner makes the resolved endpoint URL appear
    "overridden" and silently corrupts warning-capture assertions.
    """
    import runpod

    monkeypatch.setattr(runpod, "endpoint_url_base", "https://api.runpod.ai/v2")


@pytest.fixture
def custom_runpod_endpoint(monkeypatch):
    """Pin runpod.endpoint_url_base to a custom dev-like URL.

    Same caching caveat as ``prod_runpod_endpoint``: setting
    ``RUNPOD_ENDPOINT_BASE_URL`` via ``monkeypatch.setenv`` is insufficient
    because ``runpod.endpoint_url_base`` was already cached at import.
    """
    import runpod

    monkeypatch.setattr(runpod, "endpoint_url_base", "https://endpoint.custom.test/v2")


@pytest.fixture(autouse=True)
def clear_all_url_env(monkeypatch):
    """Every test starts with a clean URL env — no host leakage from shell/CI."""
    for name in (
        "RUNPOD_API_BASE_URL",
        "RUNPOD_ENDPOINT_BASE_URL",
        "RUNPOD_REST_API_URL",
        "RUNPOD_HAPI_URL",
        "RUNPOD_HAPI_BASE_URL",
        "RUNPOD_CONSOLE_URL",
        "CONSOLE_BASE_URL",
        "RUNPOD_URL_MIXED_OK",
        "RUNPOD_ENV",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def restore_urls_module():
    """Ensure each test's reload-state does not bleed into the next test."""
    yield
    if "runpod_flash.core.urls" in sys.modules:
        del sys.modules["runpod_flash.core.urls"]
    importlib.import_module("runpod_flash.core.urls")


class TestEnvUrlHelper:
import warnings


def _reload_urls_module():
    """Reload core.urls so module-level env reads pick up the current env."""
    if "runpod_flash.core.urls" in sys.modules:
        del sys.modules["runpod_flash.core.urls"]
    return importlib.import_module("runpod_flash.core.urls")


class TestEnvUrlHelper:
    """Tests for the _env_url helper in core/urls.py."""

    ``runpod.endpoint_url_base`` is captured once at runpod-package import
    time and never re-read, so deleting ``RUNPOD_ENDPOINT_BASE_URL`` from
    the environment does not reset it. Tests that want the endpoint URL to
    look like prod must force it here; otherwise a leaked env var in the
    host shell or CI runner makes the resolved endpoint URL appear
    "overridden" and silently corrupts warning-capture assertions.
    """
    import runpod

    monkeypatch.setattr(runpod, "endpoint_url_base", "https://api.runpod.ai/v2")


@pytest.fixture
def custom_runpod_endpoint(monkeypatch):
    """Pin runpod.endpoint_url_base to a custom dev-like URL.

    Same caching caveat as ``prod_runpod_endpoint``: setting
    ``RUNPOD_ENDPOINT_BASE_URL`` via ``monkeypatch.setenv`` is insufficient
    because ``runpod.endpoint_url_base`` was already cached at import.
    """
    import runpod

    monkeypatch.setattr(runpod, "endpoint_url_base", "https://endpoint.custom.test/v2")


@pytest.fixture(autouse=True)
def clear_all_url_env(monkeypatch):
    """Every test starts with a clean URL env — no host leakage from shell/CI."""
    for name in (
        "RUNPOD_API_BASE_URL",
        "RUNPOD_ENDPOINT_BASE_URL",
        "RUNPOD_REST_API_URL",
        "RUNPOD_HAPI_URL",
        "RUNPOD_HAPI_BASE_URL",
        "RUNPOD_CONSOLE_URL",
        "CONSOLE_BASE_URL",
        "RUNPOD_URL_MIXED_OK",
        "RUNPOD_ENV",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def restore_urls_module():
    """Ensure each test's reload-state does not bleed into the next test."""
    yield
    if "runpod_flash.core.urls" in sys.modules:
        del sys.modules["runpod_flash.core.urls"]
    importlib.import_module("runpod_flash.core.urls")


class TestEnvUrlHelper:
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
        deprecations = [
            w
            for w in captured
            if issubclass(w.category, DeprecationWarning)
            and "FLASH_TEST_OLD" in str(w.message)
            and "FLASH_TEST_NEW" in str(w.message)
        ]
        assert len(deprecations) == 1
        assert any(
            issubclass(w.category, DeprecationWarning)
            and "FLASH_TEST_OLD" in str(w.message)
            and "FLASH_TEST_NEW" in str(w.message)
        ]
        assert len(deprecations) == 1

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

    def test_multiple_trailing_slashes_stripped(self, monkeypatch):
        monkeypatch.setenv("FLASH_TEST_NEW", "https://new.example.com///")

        from runpod_flash.core.urls import _env_url

        result = _env_url("FLASH_TEST_NEW", None, "https://default.example.com")
        assert result == "https://new.example.com"

    def test_empty_string_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("FLASH_TEST_NEW", "")

        from runpod_flash.core.urls import _env_url

        result = _env_url("FLASH_TEST_NEW", None, "https://default.example.com")
        assert result == "https://default.example.com"

    def test_whitespace_only_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("FLASH_TEST_NEW", "   \t  ")

        from runpod_flash.core.urls import _env_url

        result = _env_url("FLASH_TEST_NEW", None, "https://default.example.com")
        assert result == "https://default.example.com"

    def test_empty_new_falls_through_to_old(self, monkeypatch):
        monkeypatch.setenv("FLASH_TEST_NEW", "")
        monkeypatch.setenv("FLASH_TEST_OLD", "https://old.example.com")

        from runpod_flash.core.urls import _env_url

        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            result = _env_url(
                "FLASH_TEST_NEW", "FLASH_TEST_OLD", "https://default.example.com"
            )
        assert result == "https://old.example.com"
        assert any(issubclass(w.category, DeprecationWarning) for w in captured)

    def test_malformed_url_raises(self, monkeypatch):
        monkeypatch.setenv("FLASH_TEST_NEW", "not-a-url")

        from runpod_flash.core.urls import _env_url

        with pytest.raises(ValueError, match="FLASH_TEST_NEW"):
            _env_url("FLASH_TEST_NEW", None, "https://default.example.com")

    def test_bare_scheme_raises(self, monkeypatch):
        monkeypatch.setenv("FLASH_TEST_NEW", "https://")

        from runpod_flash.core.urls import _env_url

        with pytest.raises(ValueError, match="netloc"):
            _env_url("FLASH_TEST_NEW", None, "https://default.example.com")


class TestEndpointDomainParser:
    def test_empty_input_falls_back_to_prod(self):
        from runpod_flash.core.urls import _endpoint_domain_from_base_url

        assert _endpoint_domain_from_base_url("") == "api.runpod.ai"

    def test_bare_hostname_is_accepted(self):
        from runpod_flash.core.urls import _endpoint_domain_from_base_url

        assert (
            _endpoint_domain_from_base_url("endpoint.dev.runpod.ai")
            == "endpoint.dev.runpod.ai"
        )

    def test_full_url_extracts_netloc(self):
        from runpod_flash.core.urls import _endpoint_domain_from_base_url

        assert (
            _endpoint_domain_from_base_url("https://api.runpod.ai/v2")
            == "api.runpod.ai"
        )

    def test_malformed_url_raises(self):
        from runpod_flash.core.urls import _endpoint_domain_from_base_url

        with pytest.raises(ValueError, match="empty netloc"):
            _endpoint_domain_from_base_url("https:///v2")


class TestValidateUrl:
    def test_valid_https_url_returns_stripped(self):
        from runpod_flash.core.urls import _validate_url

        assert _validate_url("https://host/", "X") == "https://host"

    def test_valid_http_url_accepted(self):
        from runpod_flash.core.urls import _validate_url

        assert _validate_url("http://host", "X") == "http://host"

    def test_unsupported_scheme_rejected(self):
        from runpod_flash.core.urls import _validate_url

        with pytest.raises(ValueError, match="X"):
            _validate_url("ftp://host", "X")

    def test_empty_netloc_rejected(self):
        from runpod_flash.core.urls import _validate_url

        with pytest.raises(ValueError, match="netloc"):
            _validate_url("https:///path", "X")

    def test_malformed_port_rejected(self):
        from runpod_flash.core.urls import _validate_url

        with pytest.raises(ValueError, match="malformed port"):
            _validate_url("https://host:8o80", "X")

    def test_valid_port_accepted(self):
        from runpod_flash.core.urls import _validate_url

        assert _validate_url("https://host:8080", "X") == "https://host:8080"


class TestIsOptedOut:
    @pytest.mark.parametrize(
        "value", ["1", "true", "TRUE", "True", "yes", "YES", "on", "ON"]
    )
    def test_truthy_values_opt_out(self, monkeypatch, value):
        monkeypatch.setenv("RUNPOD_URL_MIXED_OK", value)
        from runpod_flash.core.urls import _is_opted_out

        assert _is_opted_out() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "  "])
    def test_falsey_values_do_not_opt_out(self, monkeypatch, value):
        monkeypatch.setenv("RUNPOD_URL_MIXED_OK", value)
        from runpod_flash.core.urls import _is_opted_out

        assert _is_opted_out() is False

    def test_unset_does_not_opt_out(self, monkeypatch):
        monkeypatch.delenv("RUNPOD_URL_MIXED_OK", raising=False)
        from runpod_flash.core.urls import _is_opted_out

        assert _is_opted_out() is False


class TestUrlProfile:
    """_URL_PROFILE binds env name → resolved constant → prod default.

    Locks the wiring so a future contributor can't rename a constant without
    updating the profile (which would break the partial-override check).
    """

    def test_profile_contains_every_url_env(self, prod_runpod_endpoint):
        mod = _reload_urls_module()
        env_names = {name for name, _, _ in mod._URL_PROFILE}
        assert env_names == {
            "RUNPOD_API_BASE_URL",
            "RUNPOD_ENDPOINT_BASE_URL",
            "RUNPOD_REST_API_URL",
            "RUNPOD_HAPI_URL",
            "RUNPOD_CONSOLE_URL",
        }

    def test_profile_defaults_match_module_constants(self, prod_runpod_endpoint):
        mod = _reload_urls_module()
        defaults_by_env = {name: default for name, _, default in mod._URL_PROFILE}
        assert defaults_by_env == {
            "RUNPOD_API_BASE_URL": mod.DEFAULT_API_URL,
            "RUNPOD_ENDPOINT_BASE_URL": mod.DEFAULT_ENDPOINT_URL,
            "RUNPOD_REST_API_URL": mod.DEFAULT_REST_API_URL,
            "RUNPOD_HAPI_URL": mod.DEFAULT_HAPI_URL,
            "RUNPOD_CONSOLE_URL": mod.DEFAULT_CONSOLE_URL,
        }

    def test_profile_resolvers_match_module_constants(self, prod_runpod_endpoint):
        mod = _reload_urls_module()
        resolved_by_env = {name: resolver() for name, resolver, _ in mod._URL_PROFILE}
        assert resolved_by_env == {
            "RUNPOD_API_BASE_URL": mod.RUNPOD_API_URL,
            "RUNPOD_ENDPOINT_BASE_URL": mod.RUNPOD_ENDPOINT_URL,
            "RUNPOD_REST_API_URL": mod.RUNPOD_REST_API_URL,
            "RUNPOD_HAPI_URL": mod.RUNPOD_HAPI_URL,
            "RUNPOD_CONSOLE_URL": mod.RUNPOD_CONSOLE_URL,
        }


class TestConsoleDeprecationShim:
    """Validates the CONSOLE_BASE_URL → RUNPOD_CONSOLE_URL deprecation shim."""

    def test_new_console_url_honored(self, monkeypatch, prod_runpod_endpoint):
        monkeypatch.setenv("RUNPOD_CONSOLE_URL", "https://new-console.example.com")
        mod = _reload_urls_module()
        assert mod.RUNPOD_CONSOLE_URL == "https://new-console.example.com"

    def test_old_console_url_still_works_with_warning(
        self, monkeypatch, prod_runpod_endpoint
    ):

class TestConsoleDeprecationShim:
    """Validates the CONSOLE_BASE_URL → RUNPOD_CONSOLE_URL deprecation shim."""

    def test_new_console_url_honored(self, monkeypatch, prod_runpod_endpoint):
        monkeypatch.setenv("RUNPOD_CONSOLE_URL", "https://new-console.example.com")
        mod = _reload_urls_module()
        assert mod.RUNPOD_CONSOLE_URL == "https://new-console.example.com"

    def test_old_console_url_still_works_with_warning(
        self, monkeypatch, prod_runpod_endpoint
    ):
        monkeypatch.setenv("CONSOLE_BASE_URL", "https://old-console.example.com")
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            mod = _reload_urls_module()
        assert mod.RUNPOD_CONSOLE_URL == "https://old-console.example.com"
        deprecations = [
            w
            for w in captured
            if issubclass(w.category, DeprecationWarning)
            and "CONSOLE_BASE_URL" in str(w.message)
            and "RUNPOD_CONSOLE_URL" in str(w.message)
        ]
        assert len(deprecations) == 1

    def test_default_console_when_neither_set(self, prod_runpod_endpoint):
        mod = _reload_urls_module()
        assert mod.RUNPOD_CONSOLE_URL == "https://console.runpod.io"


class TestDerivedUrls:
    """GRAPHQL_URL and CONSOLE_URL respect their base overrides."""

    def test_graphql_url_tracks_api_base(self, monkeypatch, prod_runpod_endpoint):
        monkeypatch.setenv("RUNPOD_API_BASE_URL", "https://dev-api.runpod.io")
        mod = _reload_urls_module()
        assert mod.GRAPHQL_URL == "https://dev-api.runpod.io/graphql"

    def test_console_url_tracks_console_base(self, monkeypatch, prod_runpod_endpoint):
        monkeypatch.setenv("RUNPOD_CONSOLE_URL", "https://dev-console.runpod.io")
        mod = _reload_urls_module()
        assert (
            mod.CONSOLE_URL
            == "https://dev-console.runpod.io/serverless/user/endpoint/%s"
        )


class TestPartialOverrideWarning:
    """Partial overrides signal misconfiguration — one warning, silenceable."""

    def test_no_warning_when_all_at_default(self, prod_runpod_endpoint):
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            _reload_urls_module()
        assert not any(
            issubclass(w.category, RuntimeWarning)
            and "Partial Runpod URL override" in str(w.message)
            for w in captured
        )

    def test_warning_when_api_alone_overridden(self, monkeypatch, prod_runpod_endpoint):
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
        assert len(matches) == 1
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

    def test_warning_when_hapi_alone_overridden(
        self, monkeypatch, prod_runpod_endpoint
    ):
        monkeypatch.setenv("RUNPOD_HAPI_URL", "https://hapi.custom.test")
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            _reload_urls_module()

        matches = [
            w
            for w in captured
            if issubclass(w.category, RuntimeWarning)
            and "Partial Runpod URL override" in str(w.message)
        ]
        assert len(matches) == 1
        msg = str(matches[0].message)
        overridden_section = msg.split("Overridden:")[1].split("Still at default:")[0]
        assert "RUNPOD_HAPI_URL" in overridden_section

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

    def test_mixed_ok_opt_out_silences_warning(self, monkeypatch, prod_runpod_endpoint):
        monkeypatch.setenv("RUNPOD_API_BASE_URL", "https://api.custom.test")
        monkeypatch.setenv("RUNPOD_URL_MIXED_OK", "1")
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            _reload_urls_module()
        assert not any(
            issubclass(w.category, RuntimeWarning)
            and "Partial Runpod URL override" in str(w.message)
            for w in captured
        )


class TestRunpodEnvWithoutOverrides:
    """Warn when RUNPOD_ENV suggests non-prod but no URL envs are overridden."""

    def test_warning_when_runpod_env_set_without_any_override(
        self, monkeypatch, prod_runpod_endpoint
    ):
        monkeypatch.setenv("RUNPOD_ENV", "dev")
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            _reload_urls_module()
        matches = [
            w
            for w in captured
            if issubclass(w.category, RuntimeWarning)
            and "RUNPOD_ENV" in str(w.message)
            and "production" in str(w.message)
        ]
        assert len(matches) == 1

    def test_no_warning_when_runpod_env_prod(self, monkeypatch, prod_runpod_endpoint):
        monkeypatch.setenv("RUNPOD_ENV", "prod")
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            _reload_urls_module()
        assert not any(
            issubclass(w.category, RuntimeWarning)
            and "RUNPOD_ENV" in str(w.message)
            and "production" in str(w.message)
            for w in captured
        )

    def test_no_warning_when_runpod_env_and_override_both_set(
        self, monkeypatch, prod_runpod_endpoint
    ):
        monkeypatch.setenv("RUNPOD_ENV", "dev")
        monkeypatch.setenv("RUNPOD_HAPI_URL", "https://hapi.custom.test")
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            _reload_urls_module()
        assert not any(
            issubclass(w.category, RuntimeWarning)
            and "RUNPOD_ENV" in str(w.message)
            and "production" in str(w.message)
            for w in captured
        )

    def test_mixed_ok_opt_out_silences_runpod_env_warning(
        self, monkeypatch, prod_runpod_endpoint
    ):
        monkeypatch.setenv("RUNPOD_ENV", "dev")
        monkeypatch.setenv("RUNPOD_URL_MIXED_OK", "1")
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            _reload_urls_module()
        assert not any(
            issubclass(w.category, RuntimeWarning) and "RUNPOD_ENV" in str(w.message)
            for w in captured
        )
        assert any(
            issubclass(w.category, DeprecationWarning)
            and "CONSOLE_BASE_URL" in str(w.message)
            and "RUNPOD_CONSOLE_URL" in str(w.message)
        ]
        assert len(deprecations) == 1

    def test_default_console_when_neither_set(self, prod_runpod_endpoint):
        mod = _reload_urls_module()
        assert mod.RUNPOD_CONSOLE_URL == "https://console.runpod.io"


class TestDerivedUrls:
    """GRAPHQL_URL and CONSOLE_URL respect their base overrides."""

    def test_graphql_url_tracks_api_base(self, monkeypatch, prod_runpod_endpoint):
        monkeypatch.setenv("RUNPOD_API_BASE_URL", "https://dev-api.runpod.io")
        mod = _reload_urls_module()
        assert mod.GRAPHQL_URL == "https://dev-api.runpod.io/graphql"

    def test_console_url_tracks_console_base(self, monkeypatch, prod_runpod_endpoint):
        monkeypatch.setenv("RUNPOD_CONSOLE_URL", "https://dev-console.runpod.io")
        mod = _reload_urls_module()
        assert (
            mod.CONSOLE_URL
            == "https://dev-console.runpod.io/serverless/user/endpoint/%s"
        )


class TestPartialOverrideWarning:
    """Partial overrides signal misconfiguration — one warning, silenceable."""

    def test_no_warning_when_all_at_default(self, prod_runpod_endpoint):
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            _reload_urls_module()
        assert not any(
            issubclass(w.category, RuntimeWarning)
            and "Partial Runpod URL override" in str(w.message)
            for w in captured
        )

    def test_warning_when_api_alone_overridden(self, monkeypatch, prod_runpod_endpoint):
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
        assert len(matches) == 1
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

    def test_warning_when_hapi_alone_overridden(
        self, monkeypatch, prod_runpod_endpoint
    ):
        monkeypatch.setenv("RUNPOD_HAPI_URL", "https://hapi.custom.test")
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            _reload_urls_module()

        matches = [
            w
            for w in captured
            if issubclass(w.category, RuntimeWarning)
            and "Partial Runpod URL override" in str(w.message)
        ]
        assert len(matches) == 1
        msg = str(matches[0].message)
        overridden_section = msg.split("Overridden:")[1].split("Still at default:")[0]
        assert "RUNPOD_HAPI_URL" in overridden_section

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

    def test_mixed_ok_opt_out_silences_warning(self, monkeypatch, prod_runpod_endpoint):
        monkeypatch.setenv("RUNPOD_API_BASE_URL", "https://api.custom.test")
        monkeypatch.setenv("RUNPOD_URL_MIXED_OK", "1")
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            _reload_urls_module()
        assert not any(
            issubclass(w.category, RuntimeWarning)
            and "Partial Runpod URL override" in str(w.message)
            for w in captured
        )


class TestRunpodEnvWithoutOverrides:
    """Warn when RUNPOD_ENV suggests non-prod but no URL envs are overridden."""

    def test_warning_when_runpod_env_set_without_any_override(
        self, monkeypatch, prod_runpod_endpoint
    ):
        monkeypatch.setenv("RUNPOD_ENV", "dev")
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            _reload_urls_module()
        matches = [
            w
            for w in captured
            if issubclass(w.category, RuntimeWarning)
            and "RUNPOD_ENV" in str(w.message)
            and "production" in str(w.message)
        ]
        assert len(matches) == 1

    def test_no_warning_when_runpod_env_prod(self, monkeypatch, prod_runpod_endpoint):
        monkeypatch.setenv("RUNPOD_ENV", "prod")
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            _reload_urls_module()
        assert not any(
            issubclass(w.category, RuntimeWarning)
            and "RUNPOD_ENV" in str(w.message)
            and "production" in str(w.message)
            for w in captured
        )

    def test_no_warning_when_runpod_env_and_override_both_set(
        self, monkeypatch, prod_runpod_endpoint
    ):
        monkeypatch.setenv("RUNPOD_ENV", "dev")
        monkeypatch.setenv("RUNPOD_HAPI_URL", "https://hapi.custom.test")
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            _reload_urls_module()
        assert not any(
            issubclass(w.category, RuntimeWarning)
            and "RUNPOD_ENV" in str(w.message)
            and "production" in str(w.message)
            for w in captured
        )

    def test_mixed_ok_opt_out_silences_runpod_env_warning(
        self, monkeypatch, prod_runpod_endpoint
    ):
        monkeypatch.setenv("RUNPOD_ENV", "dev")
        monkeypatch.setenv("RUNPOD_URL_MIXED_OK", "1")
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            _reload_urls_module()
        assert not any(
            issubclass(w.category, RuntimeWarning) and "RUNPOD_ENV" in str(w.message)
            for w in captured
        )
