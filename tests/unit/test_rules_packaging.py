"""Test that rules files are discoverable in the installed package."""

from importlib import resources


class TestRulesPackaging:
    def test_rules_directory_exists(self):
        rules_dir = resources.files("runpod_flash.rules")
        assert rules_dir is not None

    def test_agents_md_readable(self):
        rules_file = resources.files("runpod_flash.rules") / "AGENTS.md"
        content = rules_file.read_text()
        assert "Flash Rules for AI Coding Agents" in content
        assert "@Endpoint" in content
