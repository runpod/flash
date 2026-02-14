"""Configuration management for runpod-flash CLI."""

from pathlib import Path
from typing import NamedTuple


class FlashPaths(NamedTuple):
    """Paths for runpod-flash configuration and data."""

    flash_dir: Path
    config_file: Path
    deployments_file: Path
    logs_dir: Path

    def ensure_flash_dir(self) -> None:
        """Ensure the .flash directory and logs subdirectory exist."""
        self.flash_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)


def get_paths() -> FlashPaths:
    """Get standardized paths for runpod-flash configuration."""
    flash_dir = Path.cwd() / ".flash"
    config_file = flash_dir / "config.json"
    deployments_file = flash_dir / "deployments.json"
    logs_dir = flash_dir / "logs"

    return FlashPaths(
        flash_dir=flash_dir,
        config_file=config_file,
        deployments_file=deployments_file,
        logs_dir=logs_dir,
    )
