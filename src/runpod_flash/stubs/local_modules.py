"""Discover the transitive closure of local (non-pip, non-stdlib) modules an
endpoint imports, so they can be bundled at deploy time or shipped inline for
live-serverless execution.

A "local" module is a ``.py`` file or package directory under the project root.
Anything that resolves to the standard library or an installed site-package is
treated as external and left to pip / the worker image — never bundled, never an
error.
"""

from __future__ import annotations

import ast
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..core.exceptions import LocalModuleResolutionError

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


def resolve_local_modules(
    source: str, source_file: str | Path, project_root: str | Path
) -> ResolvedModules:
    """Resolve the transitive set of local module files imported by *source*.

    Args:
        source: Python source to scan (a function body or a whole module).
        source_file: File *source* came from; its directory is the base for
            sibling and relative-import resolution.
        project_root: Only files under this root are considered local; included
            paths are made relative to it. For the live path this is the source
            file's directory; for the build path it is the Flash project dir.

    Returns:
        ResolvedModules with the file map (POSIX relative path -> absolute path)
        and any warnings.

    Raises:
        LocalModuleResolutionError: a relative import, a local package submodule,
            or a local file outside the project root could not be handled.
    """
    root = Path(project_root).resolve()
    start_dir = Path(source_file).resolve().parent
    result = ResolvedModules()
    visited: set[Path] = set()
    _walk(source, start_dir, root, result, visited, origin=str(source_file))
    return result


def _walk(
    source: str,
    current_dir: Path,
    root: Path,
    result: ResolvedModules,
    visited: set[Path],
    origin: str,
) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise LocalModuleResolutionError(
            f"Could not parse {origin} while resolving local imports: {exc}"
        ) from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _consider(alias.name, 0, current_dir, root, result, visited, origin)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0 and node.module is None:
                # `from . import a, b` — each name is a candidate local submodule
                for alias in node.names:
                    _consider(
                        alias.name,
                        node.level,
                        current_dir,
                        root,
                        result,
                        visited,
                        origin,
                    )
            else:
                _consider(
                    node.module or "",
                    node.level,
                    current_dir,
                    root,
                    result,
                    visited,
                    origin,
                )
        elif isinstance(node, ast.Call):
            _consider_dynamic(node, current_dir, root, result, visited, origin)


def _consider(
    dotted: str,
    level: int,
    current_dir: Path,
    root: Path,
    result: ResolvedModules,
    visited: set[Path],
    origin: str,
) -> None:
    if level == 0:
        if not dotted or is_stdlib(dotted):
            return
        path = local_path_for(dotted, [current_dir, root])
        if path is None:
            return  # external (pip / worker image); not our concern
    else:
        base = current_dir
        for _ in range(level - 1):
            base = base.parent
        if dotted:
            path = local_path_for(dotted, [base])
        else:
            candidate = base / "__init__.py"
            path = candidate if candidate.is_file() else None
        if path is None:
            raise LocalModuleResolutionError(
                f"{origin}: relative import (level={level}, module={dotted!r}) "
                f"could not be resolved to a local file under {base}"
            )
    _include(path, root, result, visited)


def _consider_dynamic(
    node: ast.Call,
    current_dir: Path,
    root: Path,
    result: ResolvedModules,
    visited: set[Path],
    origin: str,
) -> None:
    func = node.func
    is_import_module = isinstance(func, ast.Attribute) and func.attr == "import_module"
    is_dunder_import = isinstance(func, ast.Name) and func.id == "__import__"
    if not (is_import_module or is_dunder_import):
        return
    if (
        node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        _consider(node.args[0].value, 0, current_dir, root, result, visited, origin)
    else:
        lineno = getattr(node, "lineno", "?")
        result.warnings.append(
            f"{origin}:{lineno}: unresolvable dynamic import (non-literal argument); "
            f"ensure the module is on the worker image or bundle it explicitly"
        )


def _include(
    path: Path, root: Path, result: ResolvedModules, visited: set[Path]
) -> None:
    path = path.resolve()
    if path in visited:
        return
    try:
        rel = path.relative_to(root)
    except ValueError as exc:
        raise LocalModuleResolutionError(
            f"Imported local module {path} lives outside the project root {root} "
            f"and cannot be included; move it under the project or use `flash deploy`."
        ) from exc
    visited.add(path)
    result.files[rel.as_posix()] = str(path)
    _include_ancestor_inits(path, root, result, visited)
    _walk(
        path.read_text(encoding="utf-8"),
        path.parent,
        root,
        result,
        visited,
        origin=str(path),
    )


def _include_ancestor_inits(
    path: Path, root: Path, result: ResolvedModules, visited: set[Path]
) -> None:
    parent = path.parent
    while parent != root and root in parent.parents:
        init = parent / "__init__.py"
        if init.is_file() and init.resolve() not in visited:
            _include(init, root, result, visited)
        parent = parent.parent
