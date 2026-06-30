"""Unit tests for credential storage and retrieval."""

import logging
import os
import sys
from pathlib import Path
from unittest.mock import patch

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

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

    def test_preserves_runpodctl_top_level_keys(self, isolate_credentials_file):
        isolate_credentials_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_credentials_file.write_text(
            "apikey = 'rpa_runpodctl_key'\n"
            "apiurl = 'https://api.runpod.io/graphql'\n"
            "\n"
            "[default]\n"
            'api_key = "old-flash-key"\n'
        )
        save_api_key("new-flash-key")
        parsed = tomllib.loads(isolate_credentials_file.read_text())
        assert parsed["apikey"] == "rpa_runpodctl_key"
        assert parsed["apiurl"] == "https://api.runpod.io/graphql"
        assert parsed["default"]["api_key"] == "new-flash-key"

    def test_adds_default_section_when_missing(self, isolate_credentials_file):
        isolate_credentials_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_credentials_file.write_text(
            "apikey = 'rpa_runpodctl_key'\napiurl = 'https://api.runpod.io/graphql'\n"
        )
        save_api_key("flash-key")
        text = isolate_credentials_file.read_text()
        parsed = tomllib.loads(text)
        assert parsed["apikey"] == "rpa_runpodctl_key"
        assert parsed["apiurl"] == "https://api.runpod.io/graphql"
        assert parsed["default"]["api_key"] == "flash-key"

    def test_preserves_other_profile_sections(self, isolate_credentials_file):
        isolate_credentials_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_credentials_file.write_text(
            "[default]\n"
            'api_key = "old"\n'
            "\n"
            "[staging]\n"
            'api_key = "staging-key"\n'
            'extra = "preserved"\n'
        )
        save_api_key("new-default")
        parsed = tomllib.loads(isolate_credentials_file.read_text())
        assert parsed["default"]["api_key"] == "new-default"
        assert parsed["staging"]["api_key"] == "staging-key"
        assert parsed["staging"]["extra"] == "preserved"

    def test_creates_file_with_only_default_when_missing(
        self, isolate_credentials_file
    ):
        save_api_key("first-key")
        parsed = tomllib.loads(isolate_credentials_file.read_text())
        assert parsed == {"default": {"api_key": "first-key"}}

    def test_preserves_inline_comment_on_other_section_header(
        self, isolate_credentials_file
    ):
        """An inline comment on a later section header must not redirect the
        update onto that section. Regression for the regex section-boundary bug.
        """
        isolate_credentials_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_credentials_file.write_text(
            "[default]\n"
            'some_other_field = "x"\n'
            "\n"
            "[staging]  # production environment\n"
            'api_key = "staging-key"\n'
        )
        save_api_key("new-flash-key")
        parsed = tomllib.loads(isolate_credentials_file.read_text())
        assert parsed["default"]["api_key"] == "new-flash-key"
        assert parsed["staging"]["api_key"] == "staging-key"

    def test_updates_default_with_inline_comment_header(self, isolate_credentials_file):
        """`[default] # comment` must update in place, not append a duplicate
        `[default]` table that tomllib would refuse to load.
        """
        isolate_credentials_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_credentials_file.write_text(
            '[default] # flash profile\napi_key = "old"\n'
        )
        save_api_key("new-key")
        text = isolate_credentials_file.read_text()
        parsed = tomllib.loads(text)
        assert parsed["default"]["api_key"] == "new-key"
        assert text.count("[default]") == 1

    def test_handles_default_header_without_trailing_newline(
        self, isolate_credentials_file
    ):
        """A `[default]` header with no trailing newline must not concatenate
        the new key onto the header line.
        """
        isolate_credentials_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_credentials_file.write_text("[default]")
        save_api_key("new-key")
        parsed = tomllib.loads(isolate_credentials_file.read_text())
        assert parsed["default"]["api_key"] == "new-key"

    def test_roundtrips_api_key_with_backslash_and_quote(
        self, isolate_credentials_file
    ):
        """Keys containing backslash and double-quote must survive a write/read
        round-trip through a real TOML parser.
        """
        weird_key = r'a\b"c'
        save_api_key(weird_key)
        parsed = tomllib.loads(isolate_credentials_file.read_text())
        assert parsed["default"]["api_key"] == weird_key

    def test_roundtrips_api_key_with_control_char(self, isolate_credentials_file):
        """Keys containing control characters (e.g. a tab) must produce valid
        TOML rather than a file the next load rejects.
        """
        weird_key = "tok\ten\nwith-controls"
        save_api_key(weird_key)
        parsed = tomllib.loads(isolate_credentials_file.read_text())
        assert parsed["default"]["api_key"] == weird_key

    def test_preserves_crlf_line_endings(self, isolate_credentials_file):
        """A CRLF-edited config must not gain a stray LF-only line."""
        isolate_credentials_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_credentials_file.write_bytes(
            b"apikey = 'rpa_runpodctl_key'\r\n\r\n[default]\r\napi_key = \"old\"\r\n"
        )
        save_api_key("new-key")
        raw = isolate_credentials_file.read_bytes()
        assert b"\r\n" in raw
        assert b"\n" not in raw.replace(b"\r\n", b"")
        parsed = tomllib.loads(isolate_credentials_file.read_text())
        assert parsed["default"]["api_key"] == "new-key"
        assert parsed["apikey"] == "rpa_runpodctl_key"

    def test_inserts_api_key_into_default_without_existing_key(
        self, isolate_credentials_file
    ):
        """`[default]` with no `api_key` field gains one without disturbing
        sibling fields or other sections.
        """
        isolate_credentials_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_credentials_file.write_text(
            '[default]\nfoo = "bar"\n\n[other]\nx = 1\n'
        )
        save_api_key("new-key")
        parsed = tomllib.loads(isolate_credentials_file.read_text())
        assert parsed["default"]["api_key"] == "new-key"
        assert parsed["default"]["foo"] == "bar"
        assert parsed["other"]["x"] == 1

    def test_preserves_comments_and_formatting(self, isolate_credentials_file):
        """Comments and unrelated content survive the round-trip."""
        isolate_credentials_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_credentials_file.write_text(
            "# managed by runpodctl\n"
            "apikey = 'rpa_key'\n"
            "\n"
            "[default]\n"
            "# flash credentials\n"
            'api_key = "old"\n'
        )
        save_api_key("new-key")
        text = isolate_credentials_file.read_text()
        assert "# managed by runpodctl" in text
        assert "# flash credentials" in text

    def test_recovers_from_corrupt_existing_file(
        self, isolate_credentials_file, caplog
    ):
        """A malformed config (already unloadable) must not block login: fall
        back to a fresh minimal document and warn rather than raise.
        """
        isolate_credentials_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_credentials_file.write_text("not valid toml {{{{\n")
        with caplog.at_level(logging.WARNING):
            save_api_key("new-key")
        parsed = tomllib.loads(isolate_credentials_file.read_text())
        assert parsed == {"default": {"api_key": "new-key"}}
        assert any(record.levelno == logging.WARNING for record in caplog.records)
