"""Tests for runpod_flash.rules.install_agent_files."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from runpod_flash.rules import install_agent_files


class TestInstallAgentFiles:
    def test_writes_agents_md_when_absent(self, tmp_path: Path) -> None:
        written = install_agent_files(tmp_path)

        agents = tmp_path / "AGENTS.md"
        assert agents in written
        assert agents.is_file()
        assert "Use the Flash CLI" in agents.read_text(encoding="utf-8")

    def test_does_not_overwrite_existing_agents_md(self, tmp_path: Path) -> None:
        agents = tmp_path / "AGENTS.md"
        agents.write_text("user's own content", encoding="utf-8")

        written = install_agent_files(tmp_path)

        assert agents not in written
        assert agents.read_text(encoding="utf-8") == "user's own content"

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="symlinks require developer mode on Windows",
    )
    def test_creates_claude_md_symlink_when_absent(self, tmp_path: Path) -> None:
        written = install_agent_files(tmp_path)

        claude = tmp_path / "CLAUDE.md"
        assert claude in written
        assert claude.is_symlink()
        assert os.readlink(claude) == "AGENTS.md"

    def test_does_not_replace_existing_claude_md(self, tmp_path: Path) -> None:
        claude = tmp_path / "CLAUDE.md"
        claude.write_text("user's own claude rules", encoding="utf-8")

        written = install_agent_files(tmp_path)

        assert claude not in written
        assert not claude.is_symlink()
        assert claude.read_text(encoding="utf-8") == "user's own claude rules"

    def test_symlink_failure_does_not_break_install(self, tmp_path: Path) -> None:
        with patch("runpod_flash.rules.os.symlink", side_effect=OSError("denied")):
            written = install_agent_files(tmp_path)

        agents = tmp_path / "AGENTS.md"
        claude = tmp_path / "CLAUDE.md"
        assert agents in written
        assert agents.is_file()
        assert not claude.exists()

    def test_idempotent_second_call(self, tmp_path: Path) -> None:
        install_agent_files(tmp_path)
        written_again = install_agent_files(tmp_path)

        assert written_again == []

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="symlinks require developer mode on Windows",
    )
    def test_broken_claude_md_symlink_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        claude = tmp_path / "CLAUDE.md"
        os.symlink("nonexistent.md", claude)
        assert claude.is_symlink() and not claude.exists()

        with caplog.at_level(logging.WARNING, logger="runpod_flash.rules"):
            written = install_agent_files(tmp_path)

        assert claude not in written
        assert claude.is_symlink()
        assert os.readlink(claude) == "nonexistent.md"
        assert any("broken symlink" in r.message for r in caplog.records)

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="symlinks require developer mode on Windows",
    )
    def test_broken_agents_md_symlink_logs_warning_and_skips_write(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        agents = tmp_path / "AGENTS.md"
        os.symlink("nonexistent.md", agents)
        assert agents.is_symlink() and not agents.exists()

        with caplog.at_level(logging.WARNING, logger="runpod_flash.rules"):
            written = install_agent_files(tmp_path)

        assert agents not in written
        assert agents.is_symlink()
        assert os.readlink(agents) == "nonexistent.md"
        assert any("broken symlink" in r.message for r in caplog.records)

    def test_missing_packaged_agents_md_raises_clear_error(
        self, tmp_path: Path
    ) -> None:
        with patch(
            "runpod_flash.rules.resources.files",
            side_effect=FileNotFoundError("not found"),
        ):
            with pytest.raises(FileNotFoundError, match="wheel may be incomplete"):
                install_agent_files(tmp_path)
