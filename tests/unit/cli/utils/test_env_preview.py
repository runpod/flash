"""Tests for deploy-time env preview utilities."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runpod_flash.cli.utils.env_preview import (
    collect_env_for_preview,
    mask_env_value,
)


class TestMaskValue:
    """Tests for mask_env_value(key, value)."""

    @pytest.mark.parametrize(
        "key",
        ["API_TOKEN", "SECRET_KEY", "MY_PASSWORD", "AUTH_CREDENTIAL", "HF_TOKEN"],
    )
    def test_secret_keys_are_masked(self, key: str) -> None:
        value = "hf_abc1234567890"
        result = mask_env_value(key, value)
        assert result == "hf_abc...****"

    def test_short_secret_value_fully_masked(self) -> None:
        result = mask_env_value("API_KEY", "short")
        assert result == "****"

    def test_exactly_six_chars_fully_masked(self) -> None:
        result = mask_env_value("API_KEY", "abcdef")
        assert result == "****"

    def test_seven_chars_partially_masked(self) -> None:
        result = mask_env_value("API_KEY", "abcdefg")
        assert result == "abcdef...****"

    def test_non_secret_key_returns_unchanged(self) -> None:
        result = mask_env_value("DATABASE_URL", "postgres://localhost:5432/db")
        assert result == "postgres://localhost:5432/db"

    @pytest.mark.parametrize(
        "key",
        ["api_token", "Api_Key", "my_SECRET", "user_password", "CREDENTIAL_store"],
    )
    def test_case_insensitive_matching(self, key: str) -> None:
        value = "some_long_secret_value"
        result = mask_env_value(key, value)
        assert result == "some_l...****"

    def test_key_containing_token_mid_word(self) -> None:
        """TOKEN in TOKENIZER should still match."""
        result = mask_env_value("TOKENIZER_PATH", "long_enough_value")
        assert result == "long_e...****"

    def test_empty_value_non_secret(self) -> None:
        result = mask_env_value("SOME_VAR", "")
        assert result == ""

    def test_empty_value_secret_key(self) -> None:
        result = mask_env_value("API_KEY", "")
        assert result == "****"


class TestCollectEnvForPreview:
    """Tests for collect_env_for_preview(manifest)."""

    def test_empty_manifest_returns_empty_dict(self) -> None:
        result = collect_env_for_preview({})
        assert result == {}

    def test_manifest_with_no_resources_key(self) -> None:
        result = collect_env_for_preview({"version": "1.0"})
        assert result == {}

    def test_resource_with_explicit_env(self) -> None:
        manifest = {
            "resources": {
                "my-worker": {
                    "env": {"MODEL_NAME": "gpt2", "BATCH_SIZE": "32"},
                },
            },
        }
        result = collect_env_for_preview(manifest)
        assert "my-worker" in result
        entries = result["my-worker"]
        assert ("BATCH_SIZE", "32", "user") in entries
        assert ("MODEL_NAME", "gpt2", "user") in entries

    def test_resource_with_no_env(self) -> None:
        manifest = {
            "resources": {
                "my-worker": {},
            },
        }
        result = collect_env_for_preview(manifest)
        assert result["my-worker"] == []

    @patch(
        "runpod_flash.core.credentials.get_api_key", return_value="rp_test_key_12345"
    )
    def test_remote_calls_resource_gets_api_key_injected(
        self, mock_get_api_key: object
    ) -> None:
        manifest = {
            "resources": {
                "mothership": {
                    "makes_remote_calls": True,
                },
            },
        }
        result = collect_env_for_preview(manifest)
        entries = result["mothership"]
        assert ("RUNPOD_API_KEY", "rp_test_key_12345", "flash") in entries

    @patch("runpod_flash.core.credentials.get_api_key", return_value=None)
    def test_remote_calls_no_api_key_available(self, mock_get_api_key: object) -> None:
        manifest = {
            "resources": {
                "mothership": {
                    "makes_remote_calls": True,
                },
            },
        }
        result = collect_env_for_preview(manifest)
        entries = result["mothership"]
        keys = [k for k, _, _ in entries]
        assert "RUNPOD_API_KEY" not in keys

    def test_load_balanced_resource_gets_module_path_injected(self) -> None:
        manifest = {
            "resources": {
                "gpu-worker": {
                    "is_load_balanced": True,
                    "module_path": "app.worker:MyModel",
                },
            },
        }
        result = collect_env_for_preview(manifest)
        entries = result["gpu-worker"]
        assert ("FLASH_MODULE_PATH", "app.worker:MyModel", "flash") in entries

    def test_load_balanced_without_module_path_no_injection(self) -> None:
        manifest = {
            "resources": {
                "gpu-worker": {
                    "is_load_balanced": True,
                },
            },
        }
        result = collect_env_for_preview(manifest)
        entries = result["gpu-worker"]
        keys = [k for k, _, _ in entries]
        assert "FLASH_MODULE_PATH" not in keys

    @patch("runpod_flash.core.credentials.get_api_key", return_value="rp_key_999")
    def test_user_env_overrides_flash_injection(self, mock_get_api_key: object) -> None:
        """If user already set RUNPOD_API_KEY, flash should not inject it."""
        manifest = {
            "resources": {
                "mothership": {
                    "makes_remote_calls": True,
                    "env": {"RUNPOD_API_KEY": "user_provided_key"},
                },
            },
        }
        result = collect_env_for_preview(manifest)
        entries = result["mothership"]
        api_key_entries = [(k, v, s) for k, v, s in entries if k == "RUNPOD_API_KEY"]
        assert len(api_key_entries) == 1
        assert api_key_entries[0] == ("RUNPOD_API_KEY", "user_provided_key", "user")

    def test_user_env_values_sorted_by_key(self) -> None:
        manifest = {
            "resources": {
                "worker": {
                    "env": {"ZEBRA": "1", "APPLE": "2", "MANGO": "3"},
                },
            },
        }
        result = collect_env_for_preview(manifest)
        keys = [k for k, _, _ in result["worker"]]
        assert keys == ["APPLE", "MANGO", "ZEBRA"]
