"""Tests for flash rules CLI command."""

from unittest.mock import patch

from runpod_flash.cli.commands.rules import rules_command


class TestRulesCommand:
    def test_generates_agent_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        with (
            patch(
                "runpod_flash.cli.commands.rules.generate_agent_files",
                return_value=["CLAUDE.md", ".cursorrules"],
            ) as mock_gen,
            patch(
                "runpod_flash.cli.commands.rules._get_version",
                return_value="1.9.1",
            ),
            patch("runpod_flash.cli.commands.rules.update_dynamic_context"),
            patch("runpod_flash.cli.commands.rules.console"),
        ):
            rules_command()

        mock_gen.assert_called_once_with(tmp_path, "1.9.1")

    def test_no_files_written_shows_warning(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        with (
            patch(
                "runpod_flash.cli.commands.rules.generate_agent_files",
                return_value=[],
            ),
            patch(
                "runpod_flash.cli.commands.rules._get_version",
                return_value="1.9.1",
            ),
            patch("runpod_flash.cli.commands.rules.update_dynamic_context"),
            patch(
                "runpod_flash.cli.commands.rules.console",
            ) as mock_console,
        ):
            rules_command()

        mock_console.print.assert_called_with(
            "[yellow]No agent files generated (all disabled).[/yellow]"
        )

    def test_calls_update_dynamic_context(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        with (
            patch(
                "runpod_flash.cli.commands.rules.generate_agent_files",
                return_value=["CLAUDE.md"],
            ),
            patch(
                "runpod_flash.cli.commands.rules._get_version",
                return_value="1.9.1",
            ),
            patch(
                "runpod_flash.cli.commands.rules.update_dynamic_context",
            ) as mock_update,
            patch("runpod_flash.cli.commands.rules.console"),
        ):
            rules_command()

        mock_update.assert_called_once_with(tmp_path)
