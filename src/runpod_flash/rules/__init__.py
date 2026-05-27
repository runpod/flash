"""Flash agent rules — install AGENTS.md and (best-effort) CLAUDE.md symlink."""

from __future__ import annotations

import logging
import os
from importlib import resources
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["install_agent_files"]


def _read_packaged_agents_md() -> str:
    try:
        return (resources.files("runpod_flash.rules") / "AGENTS.md").read_text(
            encoding="utf-8"
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            "AGENTS.md not found in runpod_flash.rules package data. "
            "The installed wheel may be incomplete."
        ) from exc


def install_agent_files(target_dir: Path) -> list[Path]:
    """Write AGENTS.md and a CLAUDE.md symlink into target_dir if absent.

    Returns the list of paths actually created. Idempotent: if both files
    exist (or CLAUDE.md already exists in any form), they are left alone.

    Symlink failure (e.g. Windows without developer mode) is non-fatal —
    AGENTS.md is still written and the failure is logged.
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []

    agents = target_dir / "AGENTS.md"
    if agents.is_symlink() and not agents.exists():
        logger.warning(
            "AGENTS.md is a broken symlink at %s. Repair manually or remove it.",
            agents,
        )
    elif not agents.exists():
        agents.write_text(_read_packaged_agents_md(), encoding="utf-8")
        created.append(agents)

    claude = target_dir / "CLAUDE.md"
    if claude.is_symlink() and not claude.exists():
        logger.warning(
            "CLAUDE.md is a broken symlink at %s. Repair manually or remove it.",
            claude,
        )
    elif claude.is_file() and not claude.is_symlink():
        # Real CLAUDE.md exists — Claude Code will read it instead of AGENTS.md,
        # so the user is silently orphaned from Flash rules in Claude Code while
        # Cursor/Codex/Aider/Amp still pick them up via AGENTS.md.
        logger.info(
            "CLAUDE.md already exists at %s as a regular file (not a symlink). "
            "Claude Code will use it and not see Flash rules in AGENTS.md. "
            "To inherit Flash rules, append with: cat AGENTS.md >> CLAUDE.md "
            "(or replace it with a symlink: ln -sf AGENTS.md CLAUDE.md).",
            claude,
        )
    elif not claude.exists():
        try:
            # Relative target keeps the symlink valid when the project is moved
            # or copied (with symlink-preserving tools). An absolute path would
            # break on any relocation.
            os.symlink("AGENTS.md", claude)
            created.append(claude)
        except OSError as exc:
            logger.warning(
                "Could not create CLAUDE.md symlink (%s). "
                "Claude Code users can run: ln -s AGENTS.md CLAUDE.md",
                exc,
            )

    return created
