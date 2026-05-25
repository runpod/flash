"""Flash agent rules — install AGENTS.md and (best-effort) CLAUDE.md symlink."""

from __future__ import annotations

import logging
import os
from importlib import resources
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["install_agent_files"]


def _read_packaged_agents_md() -> str:
    return (resources.files("runpod_flash.rules") / "AGENTS.md").read_text(
        encoding="utf-8"
    )


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
    if not agents.exists():
        agents.write_text(_read_packaged_agents_md(), encoding="utf-8")
        created.append(agents)

    claude = target_dir / "CLAUDE.md"
    if not claude.exists() and not claude.is_symlink():
        try:
            os.symlink("AGENTS.md", claude)
            created.append(claude)
        except OSError as exc:
            logger.warning(
                "Could not create CLAUDE.md symlink (%s). "
                "Claude Code users can run: ln -s AGENTS.md CLAUDE.md",
                exc,
            )

    return created
