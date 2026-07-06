"""Discover the transitive closure of local (non-pip, non-stdlib) modules an
endpoint imports, so they can be bundled at deploy time or shipped inline for
live-serverless execution.

A "local" module is a ``.py`` file or package directory under the project root.
Anything that resolves to the standard library or an installed site-package is
treated as external and left to pip / the worker image — never bundled, never an
error.
"""

from __future__ import annotations

import ast  # noqa: F401
import logging  # noqa: F401
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..core.exceptions import LocalModuleResolutionError  # noqa: F401

log = logging.getLogger(__name__)

# Total inline module payload cap for the live path. Runpod /run payloads are
# limited (~10 MB); stay well under and fail loudly past this.
MAX_INLINE_MODULE_BYTES = 8 * 1024 * 1024  # 8 MiB


@dataclass
class ResolvedModules:
    """Result of a local-module resolution.

    files: POSIX relative path -> absolute path, for every local file to ship.
    warnings: human-readable notes (e.g. unresolvable dynamic imports).
    """

    files: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _top_level(name: str) -> str:
    return name.split(".", 1)[0]


def is_stdlib(name: str) -> bool:
    """True when *name*'s top-level package is part of the standard library."""
    return _top_level(name) in sys.stdlib_module_names


def local_path_for(dotted: str, search_dirs: list[Path]) -> Path | None:
    """Return the file backing a dotted module name under any search dir.

    Checks the module file (``a/b.py``) then the package init (``a/b/__init__.py``)
    in each search dir in order. Returns the first match, or ``None`` when the name
    does not correspond to a local file (i.e. it is external).
    """
    rel = Path(*dotted.split("."))
    for base in search_dirs:
        module_file = base / rel.with_suffix(".py")
        if module_file.is_file():
            return module_file
        package_init = base / rel / "__init__.py"
        if package_init.is_file():
            return package_init
    return None
