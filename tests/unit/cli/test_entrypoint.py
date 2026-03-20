"""Tests for the CLI entrypoint wrapper that catches corrupted credentials."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from runpod_flash.cli.entrypoint import main


class TestEntrypoint:
    """Tests for runpod_flash.cli.entrypoint.main."""

    def test_normal_import_runs_app(self):
        """When import succeeds, the Typer app is invoked."""
        mock_app = MagicMock()
        mock_module = MagicMock()
        mock_module.app = mock_app

        with patch.dict(sys.modules, {"runpod_flash.cli.main": mock_module}):
            main()

        mock_app.assert_called_once()

    def test_corrupted_toml_shows_clean_error(self, capsys):
        """Import-time TOMLDecodeError surfaces a clean message, not a traceback."""
        # Create a ValueError whose class looks like a TOML decode error.
        # tomli.TOMLDecodeError is a ValueError subclass with module "tomli._parser".
        toml_exc_cls = type(
            "TOMLDecodeError", (ValueError,), {"__module__": "tomli._parser"}
        )
        toml_error = toml_exc_cls("Invalid value at line 1 col 9")

        # Remove the module from cache so the import inside main() re-executes
        saved = sys.modules.pop("runpod_flash.cli.main", None)
        try:
            with patch.dict(sys.modules, {"runpod_flash.cli.main": None}):
                # Patch __import__ to raise when the entrypoint tries to import main
                real_import = __import__

                def patched_import(name, *args, **kwargs):
                    if name == "runpod_flash.cli.main":
                        raise toml_error
                    return real_import(name, *args, **kwargs)

                with patch("builtins.__import__", side_effect=patched_import):
                    with pytest.raises(SystemExit) as exc_info:
                        main()

            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "corrupted" in captured.err
            assert "flash login" in captured.err
        finally:
            if saved is not None:
                sys.modules["runpod_flash.cli.main"] = saved

    def test_non_toml_value_error_propagates(self):
        """A ValueError unrelated to TOML is not caught."""
        saved = sys.modules.pop("runpod_flash.cli.main", None)
        try:
            with patch.dict(sys.modules, {"runpod_flash.cli.main": None}):
                real_import = __import__

                def patched_import(name, *args, **kwargs):
                    if name == "runpod_flash.cli.main":
                        raise ValueError("something completely different")
                    return real_import(name, *args, **kwargs)

                with patch("builtins.__import__", side_effect=patched_import):
                    with pytest.raises(
                        ValueError, match="something completely different"
                    ):
                        main()
        finally:
            if saved is not None:
                sys.modules["runpod_flash.cli.main"] = saved
