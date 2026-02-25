"""Module context extraction for @remote function scope augmentation.

When a @remote function references module-level imports, constants, helpers,
or classes, those definitions are unavailable inside the worker's empty
exec() namespace. This module analyzes the source file's AST to identify
which top-level definitions the function actually needs, then extracts
them in original module order so they can be prepended to the function source.

The worker receives a self-contained source string — no protocol or worker
changes required.
"""

import ast
import inspect
import logging
import os
import textwrap
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Cache: file_path -> (mtime, parsed_ast, source_lines)
_MODULE_AST_CACHE: dict[str, tuple[float, ast.Module, list[str]]] = {}

# Python builtins to exclude from "referenced but not defined locally" analysis
_BUILTINS = (
    set(dir(__builtins__)) if isinstance(__builtins__, dict) else set(dir(__builtins__))
)


@dataclass
class ModuleDefinition:
    """A top-level definition extracted from a module."""

    name: str
    names_defined: set[str]
    names_referenced: set[str]
    start_line: int  # 0-indexed
    end_line: int  # 0-indexed, exclusive
    source: str


def extract_module_context(
    func: object,
    function_source: str,
    *,
    exclude_names: set[str] | None = None,
) -> str:
    """Extract module-level definitions that *function_source* references.

    Parses the module where *func* is defined, catalogs top-level definitions,
    determines which names the function body references but doesn't define
    locally, then transitively resolves dependencies and returns their source
    in original module order.

    Args:
        func: The original (unwrapped) function object.
        function_source: Dedented source code of the function.
        exclude_names: Names to exclude from needed-names resolution (e.g.
            @remote dependencies whose imports should not be extracted because
            stubs will provide them).

    Returns:
        Extracted module-level source to prepend, or empty string if none needed
        or if extraction fails (graceful degradation).
    """
    try:
        source_file = inspect.getfile(inspect.unwrap(func))
    except (TypeError, OSError):
        return ""

    if not os.path.isfile(source_file):
        return ""

    try:
        tree, lines = _get_module_ast(source_file)
    except (SyntaxError, OSError, UnicodeDecodeError):
        log.debug("Failed to parse module %s, skipping context extraction", source_file)
        return ""

    try:
        definitions = _catalog_top_level_definitions(tree, lines)
        needed_names = _collect_referenced_names(function_source)
        if exclude_names:
            needed_names -= exclude_names
        resolved = _resolve_transitive_deps(needed_names, definitions)

        if not resolved:
            return ""

        return _extract_ordered_source(resolved, lines)
    except Exception:
        log.debug("Module context extraction failed for %s", source_file, exc_info=True)
        return ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_module_ast(path: str) -> tuple[ast.Module, list[str]]:
    """Parse a module file into an AST, with mtime-based caching."""
    mtime = os.path.getmtime(path)

    cached = _MODULE_AST_CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1], cached[2]

    with open(path) as f:
        source = f.read()

    lines = source.splitlines()
    tree = ast.parse(source, filename=path)

    _MODULE_AST_CACHE[path] = (mtime, tree, lines)
    return tree, lines


def _catalog_top_level_definitions(
    tree: ast.Module, lines: list[str]
) -> list[ModuleDefinition]:
    """Walk top-level statements and build a catalog of definitions.

    Skips:
    - `if __name__ == "__main__":` blocks
    - `@remote`-decorated functions/classes (handled by stubs)
    - Bare expressions (side-effect calls like `logging.basicConfig()`)
    """
    definitions: list[ModuleDefinition] = []

    for node in tree.body:
        if _is_main_guard(node):
            continue

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _has_remote_decorator(node):
                continue
            names_defined = {node.name}
            names_referenced = _names_in_body(node) - names_defined
            defn = _make_definition(node, names_defined, names_referenced, lines)
            definitions.append(defn)

        elif isinstance(node, ast.ClassDef):
            if _has_remote_decorator(node):
                continue
            names_defined = {node.name}
            # References in bases and body
            refs = set()
            for base in node.bases:
                refs.update(_names_in_node(base))
            refs.update(_names_in_class_body(node))
            refs -= names_defined
            defn = _make_definition(node, names_defined, refs, lines)
            definitions.append(defn)

        elif isinstance(node, ast.Import):
            names_defined = set()
            for alias in node.names:
                name = alias.asname if alias.asname else alias.name
                names_defined.add(name)
            defn = _make_definition(node, names_defined, set(), lines)
            definitions.append(defn)

        elif isinstance(node, ast.ImportFrom):
            names_defined = set()
            for alias in node.names:
                name = alias.asname if alias.asname else alias.name
                names_defined.add(name)
            defn = _make_definition(node, names_defined, set(), lines)
            definitions.append(defn)

        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            names_defined = _assignment_targets(node)
            if not names_defined:
                continue
            names_referenced = _names_in_assignment_value(node)
            defn = _make_definition(node, names_defined, names_referenced, lines)
            definitions.append(defn)

        # Skip: ast.Expr (bare expressions), ast.If (non-main-guard), etc.

    return definitions


def _collect_referenced_names(function_source: str) -> set[str]:
    """Collect names the function body references but doesn't define locally.

    Subtracts: parameters, local assignments, comprehension variables,
    import names within the function, and builtins.
    """
    tree = ast.parse(function_source)

    # Find the function definition
    func_node = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_node = node
            break

    if func_node is None:
        return set()

    # Names defined locally inside the function
    local_names = set()

    # Parameters
    for arg in func_node.args.args:
        local_names.add(arg.arg)
    for arg in func_node.args.posonlyargs:
        local_names.add(arg.arg)
    for arg in func_node.args.kwonlyargs:
        local_names.add(arg.arg)
    if func_node.args.vararg:
        local_names.add(func_node.args.vararg.arg)
    if func_node.args.kwarg:
        local_names.add(func_node.args.kwarg.arg)

    # Walk the function body for local definitions
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                local_names.update(_target_names(target))
        elif isinstance(node, ast.AnnAssign) and node.target:
            local_names.update(_target_names(node.target))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.asname if alias.asname else alias.name
                local_names.add(name)
        elif isinstance(node, ast.For):
            local_names.update(_target_names(node.target))
        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars:
                    local_names.update(_target_names(item.optional_vars))
        elif isinstance(
            node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)
        ):
            for gen in node.generators:
                local_names.update(_target_names(gen.target))
        elif isinstance(node, ast.NamedExpr):
            local_names.update(_target_names(node.target))

    # All Name references in the function body
    all_refs = set()
    for node in ast.walk(func_node):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            all_refs.add(node.id)

    return all_refs - local_names - _BUILTINS


def _resolve_transitive_deps(
    needed: set[str], definitions: list[ModuleDefinition]
) -> list[ModuleDefinition]:
    """Resolve needed names transitively through the definition graph.

    If the function needs helper A, and A references constant B, both A and B
    are included. Uses a visited set to prevent infinite loops.
    """
    # Build lookup: name -> definition
    name_to_def: dict[str, ModuleDefinition] = {}
    for defn in definitions:
        for name in defn.names_defined:
            name_to_def[name] = defn

    resolved: set[int] = set()  # track by id to avoid duplicates
    result: list[ModuleDefinition] = []

    def _resolve(names: set[str]) -> None:
        for name in names:
            defn = name_to_def.get(name)
            if defn is None:
                continue
            defn_id = id(defn)
            if defn_id in resolved:
                continue
            resolved.add(defn_id)
            # Recurse into this definition's own references
            _resolve(defn.names_referenced)
            result.append(defn)

    _resolve(needed)
    return result


def _extract_ordered_source(
    definitions: list[ModuleDefinition], lines: list[str]
) -> str:
    """Join definitions in original module order, dedented."""
    # Sort by start_line to preserve module order
    ordered = sorted(definitions, key=lambda d: d.start_line)

    parts = []
    for defn in ordered:
        parts.append(defn.source)

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# AST node helpers
# ---------------------------------------------------------------------------


def _is_main_guard(node: ast.stmt) -> bool:
    """Check if node is `if __name__ == "__main__":`."""
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if isinstance(test, ast.Compare):
        if (
            isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__"
        ):
            return True
    return False


def _has_remote_decorator(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> bool:
    """Check if any decorator on the node is named 'remote'."""
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == "remote":
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == "remote":
            return True
        # Handle @remote(...) call form
        if isinstance(dec, ast.Call):
            if isinstance(dec.func, ast.Name) and dec.func.id == "remote":
                return True
            if isinstance(dec.func, ast.Attribute) and dec.func.attr == "remote":
                return True
    return False


def _make_definition(
    node: ast.stmt,
    names_defined: set[str],
    names_referenced: set[str],
    lines: list[str],
) -> ModuleDefinition:
    """Create a ModuleDefinition from an AST node."""
    start = node.lineno - 1  # AST is 1-indexed
    end = node.end_lineno  # end_lineno is inclusive in AST, we use exclusive

    source_lines = lines[start:end]
    source = textwrap.dedent("\n".join(source_lines))

    return ModuleDefinition(
        name=next(iter(names_defined), ""),
        names_defined=names_defined,
        names_referenced=names_referenced,
        start_line=start,
        end_line=end,
        source=source,
    )


def _names_in_body(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Collect all Name(Load) references in a function/async function body."""
    refs = set()
    for node in ast.walk(func_node):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            refs.add(node.id)
    return refs


def _names_in_class_body(class_node: ast.ClassDef) -> set[str]:
    """Collect all Name(Load) references in a class body."""
    refs = set()
    for node in ast.walk(class_node):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            refs.add(node.id)
    return refs


def _names_in_node(node: ast.expr) -> set[str]:
    """Collect all Name(Load) references in an expression."""
    refs = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            refs.add(child.id)
    return refs


def _assignment_targets(node: ast.Assign | ast.AnnAssign) -> set[str]:
    """Extract target names from an assignment."""
    names = set()
    if isinstance(node, ast.Assign):
        for target in node.targets:
            names.update(_target_names(target))
    elif isinstance(node, ast.AnnAssign) and node.target:
        names.update(_target_names(node.target))
    return names


def _target_names(target: ast.expr) -> set[str]:
    """Extract names from an assignment target (handles tuples, lists)."""
    names = set()
    if isinstance(target, ast.Name):
        names.add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            names.update(_target_names(elt))
    elif isinstance(target, ast.Starred):
        names.update(_target_names(target.value))
    return names


def _names_in_assignment_value(node: ast.Assign | ast.AnnAssign) -> set[str]:
    """Collect Name(Load) references in the value side of an assignment."""
    refs = set()
    value = node.value if isinstance(node, ast.Assign) else node.value
    if value is not None:
        for child in ast.walk(value):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                refs.add(child.id)
    return refs
