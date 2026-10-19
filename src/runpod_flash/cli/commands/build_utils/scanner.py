"""project scanner for discovering @remote decorated functions and classes.

imports user modules and inspects live objects via their __remote_config__
attribute (stamped by @remote and Endpoint). this handles all python
language constructs without needing to rebuild an interpreter via AST.
"""

import ast
import functools
import importlib.util
import inspect
import itertools
import logging
import os
import sys
import textwrap
import threading
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from runpod_flash.cli.utils.ignore import get_file_tree, load_ignore_patterns
from runpod_flash.core.resources.load_balancer_sls_resource import (
    LoadBalancerSlsResource,
)
from runpod_flash.core.resources.serverless import ServerlessResource
from runpod_flash.endpoint import Endpoint

logger = logging.getLogger(__name__)

# maximum seconds to wait for a single module import before treating it as hung.
# module-level code that blocks (e.g. a db connection or time.sleep) would hang
# the build indefinitely without this guard.
MODULE_IMPORT_TIMEOUT_SECONDS = 30


def file_to_url_prefix(file_path: Path, project_root: Path) -> str:
    """e.g. longruns/stage1.py -> /longruns/stage1"""
    rel = file_path.relative_to(project_root).with_suffix("")
    return "/" + str(rel).replace(os.sep, "/")


def file_to_resource_name(file_path: Path, project_root: Path) -> str:
    """e.g. longruns/stage1.py -> longruns_stage1, my-worker.py -> my_worker"""
    rel = file_path.relative_to(project_root).with_suffix("")
    return str(rel).replace(os.sep, "_").replace("/", "_").replace("-", "_")


def file_to_module_path(file_path: Path, project_root: Path) -> str:
    """e.g. longruns/stage1.py -> longruns.stage1"""
    rel = file_path.relative_to(project_root).with_suffix("")
    return str(rel).replace(os.sep, ".").replace("/", ".")


# Decorator names that mark a function/class as a Flash endpoint entry point.
ENDPOINT_DECORATOR_NAMES: frozenset[str] = frozenset({"remote", "Endpoint"})


def defines_endpoint(py_file: Path) -> bool:
    """Check whether *py_file* defines a function/class decorated as a Flash endpoint.

    Recognizes ``@remote``, ``@remote(...)``, ``@Endpoint(...)``, and attribute
    forms (e.g. ``@rf.Endpoint``). Parses the file as AST only -- it does not
    import it, so decorators do not need to be resolvable.

    This is the AST-only counterpart to the scanner's live discovery
    (``discover_remote_functions``): the scanner imports modules and inspects
    stamped ``__remote_config__`` objects, which requires the imports to
    succeed. This helper is consulted precisely when imports may be broken (the
    pre-copy local-module validation), so it cannot go through the import path.

    Returns:
        True if an endpoint decorator is found, False if none is found or the
        file cannot be read/parsed.
    """
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return False

    for node in ast.walk(tree):
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(target, ast.Attribute):
                name = target.attr
            elif isinstance(target, ast.Name):
                name = target.id
            else:
                continue
            if name in ENDPOINT_DECORATOR_NAMES:
                return True

    return False


@dataclass
class RemoteFunctionMetadata:
    """Metadata about a @remote decorated function or class."""

    function_name: str
    module_path: str
    resource_config_name: str
    resource_type: str
    is_async: bool
    is_class: bool
    file_path: Path
    http_method: Optional[str] = None
    http_path: Optional[str] = None
    is_load_balanced: bool = False
    is_live_resource: bool = False
    config_variable: Optional[str] = None
    calls_remote_functions: bool = False
    called_remote_functions: List[str] = field(default_factory=list)
    is_lb_route_handler: bool = False
    class_methods: List[str] = field(default_factory=list)
    param_names: List[str] = field(default_factory=list)
    class_method_params: Dict[str, List[str]] = field(default_factory=dict)
    docstring: Optional[str] = None
    class_method_docstrings: Dict[str, Optional[str]] = field(default_factory=dict)
    local: bool = False


def _first_docstring_line(obj: Any) -> Optional[str]:
    """extract the first line of an object's docstring, or None."""
    doc = inspect.getdoc(obj)
    if doc:
        return doc.split("\n")[0].strip()
    return None


def _get_param_names(func: Any) -> List[str]:
    """extract parameter names from a callable, excluding 'self'."""
    try:
        sig = inspect.signature(func)
        return [
            name
            for name, param in sig.parameters.items()
            if name != "self"
            and param.kind
            not in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            )
        ]
    except (ValueError, TypeError):
        return []


def _unwrap_to_original(obj: Any) -> Any:
    """follow __wrapped__ to get the original function for signature/docstring."""
    return inspect.unwrap(obj, stop=lambda f: not hasattr(f, "__wrapped__"))


def _resource_type_name(resource_config: Any) -> str:
    """get the class name of a resource config, unwrapping Endpoint if needed."""
    if isinstance(resource_config, Endpoint):
        inner = resource_config._build_resource_config()
        return type(inner).__name__
    return type(resource_config).__name__


def _resource_name(resource_config: Any) -> str:
    """get the name from a resource config object."""
    if isinstance(resource_config, Endpoint):
        return resource_config.name or ""
    return getattr(resource_config, "name", "") or ""


def _is_lb_type(resource_config: Any) -> bool:
    """check if a resource config is a load-balanced type."""
    if isinstance(resource_config, Endpoint):
        return resource_config.is_load_balanced
    if isinstance(resource_config, LoadBalancerSlsResource):
        return True
    type_name = type(resource_config).__name__
    return type_name in (
        "LoadBalancerSlsResource",
        "CpuLoadBalancerSlsResource",
        "LiveLoadBalancer",
        "CpuLiveLoadBalancer",
    )


def _is_live_type(resource_config: Any) -> bool:
    """check if a resource config is a live (on-demand) type."""
    if isinstance(resource_config, Endpoint):
        return True
    type_name = type(resource_config).__name__
    return type_name in (
        "LiveServerless",
        "CpuLiveServerless",
        "LiveLoadBalancer",
        "CpuLiveLoadBalancer",
    )


def _extract_class_info(
    cls: type,
) -> tuple[List[str], Dict[str, List[str]], Dict[str, Optional[str]]]:
    """extract public methods, their params, and their docstrings from a class.

    uses vars(cls) to preserve source-definition order rather than
    inspect.getmembers which sorts alphabetically.
    """
    methods: List[str] = []
    method_params: Dict[str, List[str]] = {}
    method_docstrings: Dict[str, Optional[str]] = {}

    for name, member in vars(cls).items():
        if name.startswith("_"):
            continue
        if not (inspect.isfunction(member) or inspect.iscoroutinefunction(member)):
            continue
        methods.append(name)
        method_params[name] = _get_param_names(member)
        method_docstrings[name] = _first_docstring_line(member)

    return methods, method_params, method_docstrings


def _import_module_from_file(file_path: Path, module_name: str) -> Any:
    """import a python file as a module. returns the module or None on failure.

    temporarily injects into sys.modules for the duration of exec_module
    (so relative imports within the file resolve), then restores the
    previous entry to avoid leaking user modules into the cli process.

    runs exec_module in a daemon thread so hung module-level code
    (e.g. blocking db connections, time.sleep) doesn't stall the build.
    """
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if not spec or not spec.loader:
        return None

    module = importlib.util.module_from_spec(spec)
    old_module = sys.modules.get(module_name)
    sys.modules[module_name] = module

    exc_holder: list[Exception] = []

    def _do_import() -> None:
        try:
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        except Exception as e:
            exc_holder.append(e)

    t = threading.Thread(target=_do_import, daemon=True)
    t.start()
    t.join(timeout=MODULE_IMPORT_TIMEOUT_SECONDS)

    try:
        if t.is_alive():
            raise TimeoutError(
                f"import of {file_path.name} timed out after "
                f"{MODULE_IMPORT_TIMEOUT_SECONDS}s (module-level code may be blocking)"
            )

        if exc_holder:
            logger.debug("failed to import %s: %s", file_path.name, exc_holder[0])
            raise exc_holder[0]

        return module
    finally:
        _restore_module(module_name, old_module)


def _restore_module(module_name: str, old_module: Any) -> None:
    if old_module is not None:
        sys.modules[module_name] = old_module
    else:
        sys.modules.pop(module_name, None)


def _metadata_from_remote_config(
    obj: Any,
    attr_name: str,
    module_path: str,
    file_path: Path,
    variable_name: Optional[str] = None,
) -> Optional[RemoteFunctionMetadata]:
    """build RemoteFunctionMetadata from an object with __remote_config__.

    obj is the decorated function/class (or wrapper). attr_name is the
    module-level attribute name it was found under.
    """
    config = getattr(obj, "__remote_config__", None)
    if not isinstance(config, dict):
        return None

    resource_config = config.get("resource_config")
    if resource_config is None:
        return None

    method = config.get("method")
    path = config.get("path")
    is_lb_route = config.get("is_lb_route_handler", False)

    # determine if the decorated target is a class.
    # RemoteClassWrapper has _wrapped_class pointing at the original class.
    # for plain classes (e.g. local=True), use inspect.isclass.
    original = _unwrap_to_original(obj)
    is_class = False
    target_class = None

    if inspect.isclass(obj) and hasattr(obj, "_wrapped_class"):
        is_class = True
        target_class = obj._wrapped_class
    elif inspect.isclass(original):
        is_class = True
        target_class = original
    elif inspect.isclass(obj):
        is_class = True
        target_class = obj

    is_async = False
    if not is_class:
        is_async = inspect.iscoroutinefunction(original) or inspect.iscoroutinefunction(
            obj
        )
    elif is_class and target_class is not None:
        # A class is async if any of its public methods are coroutines.
        # This drives handler template selection for concurrent endpoints.
        is_async = any(
            inspect.iscoroutinefunction(m)
            for name, m in vars(target_class).items()
            if not name.startswith("_")
            and (inspect.isfunction(m) or inspect.iscoroutinefunction(m))
        )

    # function/class name: for classes, use the original class name.
    # for functions, use __name__ from the unwrapped function.
    if is_class and target_class is not None:
        func_name = target_class.__name__
    else:
        func_name = getattr(original, "__name__", None) or attr_name

    res_name = _resource_name(resource_config)
    res_type = _resource_type_name(resource_config)
    is_lb = _is_lb_type(resource_config) or (method is not None and path is not None)
    is_live = _is_live_type(resource_config)

    docstring_source = (
        target_class if is_class and target_class is not None else original
    )
    docstring = _first_docstring_line(docstring_source)

    class_methods: List[str] = []
    class_method_params: Dict[str, List[str]] = {}
    class_method_docstrings: Dict[str, Optional[str]] = {}
    param_names: List[str] = []

    if is_class and target_class is not None:
        class_methods, class_method_params, class_method_docstrings = (
            _extract_class_info(target_class)
        )
    elif not is_class:
        param_names = _get_param_names(original)

    local_flag = getattr(obj, "__flash_local__", False)

    return RemoteFunctionMetadata(
        function_name=func_name,
        module_path=module_path,
        resource_config_name=res_name,
        resource_type=res_type,
        is_async=is_async,
        is_class=is_class,
        file_path=file_path,
        http_method=method,
        http_path=path,
        is_load_balanced=is_lb,
        is_live_resource=is_live,
        config_variable=variable_name,
        is_lb_route_handler=is_lb_route,
        class_methods=class_methods,
        param_names=param_names,
        class_method_params=class_method_params,
        docstring=docstring,
        class_method_docstrings=class_method_docstrings,
        local=local_flag,
    )


def _find_endpoint_instances(module: Any) -> Dict[str, Endpoint]:
    """find all Endpoint instances in a module's namespace."""
    endpoints: Dict[str, Endpoint] = {}
    for name in dir(module):
        try:
            obj = getattr(module, name)
        except Exception:
            continue
        if isinstance(obj, Endpoint) and not obj.is_client:
            endpoints[name] = obj
    return endpoints


def _find_remote_decorated(module: Any) -> Dict[str, Any]:
    """find all objects with __remote_config__ in a module's namespace."""
    results: Dict[str, Any] = {}
    for name in dir(module):
        try:
            obj = getattr(module, name)
            if hasattr(obj, "__remote_config__"):
                results[name] = obj
        except Exception:
            continue
    return results


_API_KEY_ENV = "RUNPOD_API_KEY"
_UNANALYZED = "<unanalyzed>"
_MISSING = object()


@dataclass
class _CallScan:
    """shared state for one endpoint's cross-call analysis.

    project_modules maps each scanned module path to its module, or None when
    the file failed to import. the scanner removes those modules from
    sys.modules after importing them, so this is how analysis still finds
    them.
    """

    remote_function_names: Set[str]
    project_files: Optional[Set[Path]]
    project_modules: Dict[str, Any]
    cache: Dict[int, List[str]] = field(default_factory=dict)

    def lookup_module(self, name: str) -> Any:
        """the module for name, or None. scanned project modules win."""
        if name in self.project_modules:
            return self.project_modules[name]
        return sys.modules.get(name)

    def is_project_module(self, name: str) -> bool:
        """true if name is a scanned module or a package that contains one."""
        prefix = name + "."
        return any(
            key == name or key.startswith(prefix) for key in self.project_modules
        )


def _resolve(expr: ast.expr, namespace: Dict[str, Any], scan: _CallScan) -> Any:
    """resolve a Name, or an attribute of a module (pkg.utils.helper), to its object."""
    if isinstance(expr, ast.Name):
        return namespace.get(expr.id, _MISSING)
    if isinstance(expr, ast.Attribute):
        base = _resolve(expr.value, namespace, scan)
        if isinstance(base, types.ModuleType):
            obj = getattr(base, expr.attr, _MISSING)
            if obj is _MISSING:
                # a scanned submodule is not set as an attribute of its package
                obj = scan.lookup_module(f"{base.__name__}.{expr.attr}")
            return _MISSING if obj is None else obj
    return _MISSING


def _is_client_endpoint(obj: Any) -> bool:
    return isinstance(obj, Endpoint) and obj.is_client


def _is_runpod_sdk(obj: Any) -> bool:
    """true for the runpod SDK module or anything defined in it."""
    try:
        if isinstance(obj, types.ModuleType):
            name = obj.__name__
        else:
            name = getattr(obj, "__module__", None) or ""
    except Exception:
        return False
    return isinstance(name, str) and _is_runpod_module_name(name)


def _is_remote(obj: Any) -> bool:
    """true for an @remote / @Endpoint decorated function or class."""
    try:
        return obj is not _MISSING and hasattr(obj, "__remote_config__")
    except Exception:
        return False


def _in_project(source_file: Optional[str], scan: _CallScan) -> bool:
    return (
        bool(scan.project_files)
        and source_file is not None
        and Path(source_file).resolve() in scan.project_files  # type: ignore[operator]
    )


def _project_function(obj: Any, scan: _CallScan) -> Any:
    """return obj if it is a plain function defined in one of the scanned files.

    limiting this to scanned files keeps helper analysis out of library code,
    including virtualenvs or bundled packages that live inside the project.
    """
    if _is_remote(obj):
        return None
    obj = _unwrap(obj)
    if not isinstance(obj, types.FunctionType) or _is_remote(obj):
        return None
    try:
        source_file = inspect.getsourcefile(obj)
    except Exception:
        return None
    return obj if _in_project(source_file, scan) else None


def _project_class(obj: Any, scan: _CallScan) -> Tuple[Any, Any]:
    """return (class, module) if obj is a project class or an instance of one."""
    if obj is _MISSING or isinstance(obj, types.ModuleType) or _is_remote(obj):
        return None, None
    try:
        cls = obj if inspect.isclass(obj) else type(obj)
        module = scan.lookup_module(cls.__module__)
        source_file = getattr(module, "__file__", None)
    except Exception:
        return None, None
    if _is_remote(cls) or not _in_project(source_file, scan):
        return None, None
    return cls, module


def _is_client_endpoint_construction(
    call: ast.Call, namespace: Dict[str, Any], scan: _CallScan
) -> bool:
    """match Endpoint(id=...) or Endpoint(image=...) built inline, incl. aliases."""
    func = call.func
    literal = (isinstance(func, ast.Name) and func.id == "Endpoint") or (
        isinstance(func, ast.Attribute) and func.attr == "Endpoint"
    )
    if not literal and _resolve(func, namespace, scan) is not Endpoint:
        return False
    return any(kw.arg in ("id", "image") for kw in call.keywords)


def _local_imports(
    node: ast.AST, namespace: Dict[str, Any], scan: _CallScan
) -> Tuple[Dict[str, Any], bool, bool]:
    """resolve imports made inside node against already-loaded modules.

    returns (name -> object overlay, whether the runpod SDK is imported,
    whether a project import could not be resolved). only loaded modules are
    consulted, so analysis never imports new code.
    """
    overlay: Dict[str, Any] = {}
    uses_runpod = False
    unresolved = False
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            for alias in child.names:
                if _is_runpod_module_name(alias.name):
                    uses_runpod = True
                if alias.asname:
                    name, bound = alias.name, alias.asname
                else:
                    name = bound = alias.name.split(".")[0]
                module = scan.lookup_module(name)
                if module is not None:
                    overlay[bound] = module
                elif scan.is_project_module(alias.name):
                    unresolved = True
        elif isinstance(child, ast.ImportFrom):
            if child.level:
                try:
                    name = importlib.util.resolve_name(
                        "." * child.level + (child.module or ""),
                        namespace.get("__package__"),
                    )
                except (ImportError, ValueError):
                    unresolved = True
                    continue
            elif child.module:
                name = child.module
            else:
                continue
            if _is_runpod_module_name(name):
                uses_runpod = True
            # a relative import always names project code
            in_project = bool(child.level) or scan.is_project_module(name)
            module = scan.lookup_module(name)
            if module is None:
                unresolved = unresolved or in_project
                continue
            for alias in child.names:
                obj = getattr(module, alias.name, _MISSING)
                if obj is _MISSING:
                    submodule = f"{name}.{alias.name}"
                    obj = scan.lookup_module(submodule)
                    if obj is None:
                        unresolved = (
                            unresolved
                            or in_project
                            or scan.is_project_module(submodule)
                        )
                        continue
                overlay[alias.asname or alias.name] = obj
    return overlay, uses_runpod, unresolved


def _is_runpod_module_name(name: str) -> bool:
    return name == "runpod" or name.startswith("runpod.")


def _object_needs_key(obj: Any, scan: _CallScan) -> bool:
    """true if referencing obj means the worker needs RUNPOD_API_KEY.

    a project class, or an instance of one, needs it when any of its methods
    or instance attributes would. the whole class is analyzed because calls
    through self cannot be resolved statically.
    """
    return _needs_key(obj, scan, set())


# cap on container items followed, so a large config dict stays cheap
_MAX_CONTAINER_ITEMS = 1000


def _needs_key(obj: Any, scan: _CallScan, seen: Set[int]) -> bool:
    if _is_remote(obj) or _is_client_endpoint(obj):
        return True
    if id(obj) in seen:
        return False
    seen.add(id(obj))
    # vllm.runsync, functools.partial(vllm.runsync), {"vllm": vllm}, and
    # wrappers that set __wrapped__ (functools.lru_cache, functools.wraps)
    if isinstance(obj, types.MethodType):
        return _needs_key(obj.__self__, scan, seen)
    if isinstance(obj, functools.partial):
        parts = [obj.func, *obj.args, *obj.keywords.values()]
        return any(_needs_key(part, scan, seen) for part in parts)
    if isinstance(obj, (dict, list, tuple, set, frozenset)):
        items = obj.values() if isinstance(obj, dict) else obj
        return any(
            _needs_key(item, scan, seen)
            for item in itertools.islice(items, _MAX_CONTAINER_ITEMS)
        )
    unwrapped = _unwrap(obj)
    if unwrapped is not obj:
        return _needs_key(unwrapped, scan, seen)
    cls, module = _project_class(obj, scan)
    if cls is None:
        return False
    if _class_targets(cls, module, scan):
        return True
    if inspect.isclass(obj):
        return False
    try:
        attrs = list(vars(obj).values())
    except TypeError:
        return False
    # holder.inner.ep: follow instance attributes into nested project objects
    return any(_needs_key(value, scan, seen) for value in attrs)


def _unwrap(obj: Any) -> Any:
    """the function under functools.wraps / lru_cache style wrappers, else obj."""
    if inspect.isclass(obj):
        return obj
    try:
        return inspect.unwrap(obj)
    except Exception:
        return obj


def _remote_call_targets(
    node: ast.AST, namespace: Dict[str, Any], scan: _CallScan
) -> List[str]:
    """names of the things in node that need RUNPOD_API_KEY on the worker."""
    called: List[str] = []

    def add(target: str) -> None:
        if target not in called:
            called.append(target)

    overlay, uses_runpod, unresolved = _local_imports(node, namespace, scan)
    if unresolved:
        add(_UNANALYZED)
    if uses_runpod:
        add("runpod")
    if overlay:
        namespace = {**namespace, **overlay}

    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and child.value == _API_KEY_ENV:
            add(_API_KEY_ENV)
        elif isinstance(child, ast.Call):
            if (
                isinstance(child.func, ast.Name)
                and child.func.id in scan.remote_function_names
            ):
                add(child.func.id)
            if _is_client_endpoint_construction(child, namespace, scan):
                add("Endpoint")
            helper = _project_function(_resolve(child.func, namespace, scan), scan)
            if helper is not None and _helper_targets(helper, scan):
                add(helper.__name__)
        elif isinstance(child, ast.Name):
            obj = _resolve(child, namespace, scan)
            if _is_runpod_sdk(obj) or _object_needs_key(obj, scan):
                add(child.id)
        elif isinstance(child, ast.Attribute):
            # tasks.square(x), pkg.tasks.square(x), or utils.vllm.runsync(x)
            obj = _resolve(child, namespace, scan)
            if _object_needs_key(obj, scan):
                add(ast.unparse(child))
    return called


def _helper_targets(func: Any, scan: _CallScan) -> List[str]:
    """analyze a project helper function, resolving names in its own module."""
    key = id(func)
    if key in scan.cache:
        return scan.cache[key]
    scan.cache[key] = []  # break recursion cycles
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    except Exception:
        # e.g. a lambda inside a multi-line call: getsource returns a fragment
        scan.cache[key] = [_UNANALYZED]
        return scan.cache[key]
    scan.cache[key] = _remote_call_targets(tree, func.__globals__, scan)
    return scan.cache[key]


def _class_targets(cls: Any, module: Any, scan: _CallScan) -> List[str]:
    """analyze every method of a project class, resolving names in its module."""
    key = id(cls)
    if key in scan.cache:
        return scan.cache[key]
    scan.cache[key] = []  # break recursion cycles
    try:
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        nodes = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef) and n.name == cls.__name__
        ]
    except Exception:
        nodes = []
    if not nodes:
        scan.cache[key] = [_UNANALYZED]
        return scan.cache[key]
    targets: List[str] = []
    for class_node in nodes:
        for target in _remote_call_targets(class_node, vars(module), scan):
            if target not in targets:
                targets.append(target)
    scan.cache[key] = targets
    return targets


def _analyze_cross_calls_ast(
    file_path: Path,
    function_names: Set[str],
    remote_function_names: Set[str],
    namespace: Optional[Dict[str, Any]] = None,
    project_files: Optional[Set[Path]] = None,
    project_modules: Optional[Dict[str, Any]] = None,
) -> Dict[str, List[str]]:
    """find which functions need RUNPOD_API_KEY on the worker, via AST.

    returns a dict of function_name -> list of what triggered it. a function
    needs the key when it references another @remote function or class
    (directly, aliased, or through a module), uses a client-mode Endpoint
    (id= or image=), uses the runpod SDK, reads RUNPOD_API_KEY, or calls a
    project helper or project class that does any of these. namespace is the
    module's globals, used to resolve names; project_files (resolved paths)
    limits helper analysis to scanned project code; project_modules maps
    scanned module paths to their modules. detection errs toward giving the
    key, since a missing key fails at runtime with a 401: a function, helper,
    or project import that cannot be analyzed is reported as needing it.
    """
    ns = namespace or {}
    result: Dict[str, List[str]] = {}
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except Exception:
        return result

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if node.name not in function_names:
            continue

        # fresh per function: a helper cached mid-cycle can hold a partial
        # result that is only correct within the traversal that produced it.
        scan = _CallScan(remote_function_names, project_files, project_modules or {})
        try:
            called = _remote_call_targets(node, ns, scan)
        except Exception as e:
            logger.debug(f"cross-call analysis failed for {node.name}: {e}")
            called = [_UNANALYZED]
        if called:
            result[node.name] = called

    return result


class RuntimeScanner:
    """discovers @remote decorated functions and Endpoint instances by importing modules.

    imports each python file in the project, inspects live objects for
    __remote_config__ attributes and Endpoint instances, and produces
    RemoteFunctionMetadata for the build system.
    """

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.resource_configs: Dict[str, str] = {}
        self.resource_types: Dict[str, str] = {}
        self.resource_flags: Dict[str, Dict[str, bool]] = {}
        self.resource_variables: Dict[str, str] = {}
        # populated after discover_remote_functions() runs
        self.import_errors: Dict[str, str] = {}
        # client-mode Endpoints (image=..., id=None) keyed by endpoint name;
        # each value carries var_name/file_path/module_path for the manifest.
        self.client_endpoints: Dict[str, Dict[str, Any]] = {}

    def discover_remote_functions(self) -> List[RemoteFunctionMetadata]:
        """discover all @remote decorated functions and classes by importing modules."""
        spec = load_ignore_patterns(self.project_dir)
        all_files = get_file_tree(self.project_dir, spec)
        py_files = sorted(
            f for f in all_files if f.suffix == ".py" and f.name != "__init__.py"
        )

        root_str = str(self.project_dir)
        added_to_path = root_str not in sys.path
        if added_to_path:
            sys.path.insert(0, root_str)

        synthetic_packages = self._register_parent_packages(py_files)

        functions: List[RemoteFunctionMetadata] = []
        seen_functions: Set[str] = set()
        failed_files: List[Path] = []
        namespaces: Dict[Path, Dict[str, Any]] = {}
        # module path -> module (None if the import failed), for analysis
        project_modules: Dict[str, Any] = {}

        try:
            for py_file in py_files:
                module_path = file_to_module_path(py_file, self.project_dir)
                project_modules[module_path] = None
                try:
                    module = _import_module_from_file(py_file, module_path)
                except Exception as e:
                    failed_files.append(py_file)
                    rel_path = os.path.relpath(py_file, self.project_dir)
                    self.import_errors[rel_path] = f"{type(e).__name__}: {e}"
                    continue
                if module is None:
                    failed_files.append(py_file)
                    continue
                project_modules[module_path] = module

                file_functions = self._extract_from_module(
                    module, module_path, py_file, seen_functions
                )
                functions.extend(file_functions)
                namespaces[py_file] = vars(module)

            # cross-call analysis
            remote_names = {f.function_name for f in functions}
            # __init__.py files are not scanned for endpoints, but helpers
            # defined in a package __init__ still need analysis
            project_files = {f.resolve() for f in all_files if f.suffix == ".py"}
            files_with_functions: Dict[Path, Set[str]] = {}
            for f in functions:
                files_with_functions.setdefault(f.file_path, set()).add(f.function_name)

            for file_path, func_names in files_with_functions.items():
                calls = _analyze_cross_calls_ast(
                    file_path,
                    func_names,
                    remote_names,
                    namespaces.get(file_path),
                    project_files,
                    project_modules,
                )
                for f in functions:
                    if f.file_path == file_path and f.function_name in calls:
                        f.calls_remote_functions = True
                        f.called_remote_functions = calls[f.function_name]

        finally:
            if added_to_path:
                try:
                    sys.path.remove(root_str)
                except ValueError:
                    pass
            for pkg_name in synthetic_packages:
                sys.modules.pop(pkg_name, None)

        self._populate_resource_dicts(functions)
        return functions

    def _register_parent_packages(self, py_files: List[Path]) -> List[str]:
        """register synthetic parent packages in sys.modules for dotted imports.

        when a file lives in a subdirectory (e.g. workers/gpu.py), python
        needs a 'workers' package in sys.modules for the dotted module name
        'workers.gpu' to resolve. instead of creating __init__.py files on
        disk, we inject empty module objects into sys.modules.

        returns the list of package names that were added so the caller
        can remove them after scanning.
        """
        added: List[str] = []
        for f in py_files:
            rel = f.relative_to(self.project_dir)
            parts = rel.parent.parts
            for i in range(len(parts)):
                pkg_name = ".".join(parts[: i + 1])
                if pkg_name not in sys.modules:
                    pkg = types.ModuleType(pkg_name)
                    pkg.__path__ = [str(self.project_dir / Path(*parts[: i + 1]))]
                    pkg.__package__ = pkg_name
                    sys.modules[pkg_name] = pkg
                    added.append(pkg_name)
        return added

    def _extract_from_module(
        self,
        module: Any,
        module_path: str,
        file_path: Path,
        seen: Set[str],
    ) -> List[RemoteFunctionMetadata]:
        """extract RemoteFunctionMetadata from a single imported module."""
        results: List[RemoteFunctionMetadata] = []

        self._collect_client_endpoints(module, module_path, file_path)

        remote_objects = _find_remote_decorated(module)
        endpoint_instances = _find_endpoint_instances(module)

        # map resource_config object id -> variable name
        config_to_varname: Dict[int, str] = {}
        for member_name in dir(module):
            try:
                member = getattr(module, member_name)
            except Exception:
                continue
            if isinstance(member, ServerlessResource):
                config_to_varname[id(member)] = member_name
            elif isinstance(member, Endpoint) and not member.is_client:
                config_to_varname[id(member)] = member_name
                # also map the internal cached resource config so that
                # functions decorated via @ep.get("/path") can trace back
                # to this variable name through their __remote_config__
                cached = getattr(member, "_cached_resource_config", None)
                if cached is not None:
                    config_to_varname[id(cached)] = member_name

        for attr_name, obj in remote_objects.items():
            dedup_key = f"{module_path}:{attr_name}"
            if dedup_key in seen:
                continue

            config = getattr(obj, "__remote_config__", {})
            resource_config = config.get("resource_config")

            var_name: Optional[str] = None
            if resource_config is not None:
                var_name = config_to_varname.get(id(resource_config))
                if var_name is None and isinstance(resource_config, Endpoint):
                    var_name = config_to_varname.get(id(resource_config))
                if var_name is None and hasattr(resource_config, "name"):
                    for ep_name, ep in endpoint_instances.items():
                        if ep is resource_config or (
                            hasattr(ep, "name")
                            and ep.name == getattr(resource_config, "name", None)
                        ):
                            var_name = ep_name
                            break

            meta = _metadata_from_remote_config(
                obj, attr_name, module_path, file_path, variable_name=var_name
            )
            if meta is not None:
                seen.add(dedup_key)
                results.append(meta)

        return results

    def _collect_client_endpoints(
        self, module: Any, module_path: str, file_path: Path
    ) -> None:
        """record client-mode Endpoints (image=..., no id) for the manifest.

        client-mode endpoints declare an external service image; they have no
        decorated functions, but `flash deploy` should still provision them.
        id= endpoints are excluded: they attach to an already-existing
        endpoint, so there is nothing to provision.

        Re-exports (``from defs import ep`` in a second file) surface as a
        distinct object with the same name and image because each scanned file
        is imported fresh; those keep the first record. The same name with a
        *different* image is a genuine collision and fails the build.
        """
        for member_name in dir(module):
            try:
                member = getattr(module, member_name)
            except Exception:
                continue
            if (
                not isinstance(member, Endpoint)
                or member.image is None
                or member.id is not None
            ):
                continue
            # image-based endpoints always carry a name: Endpoint.__init__
            # raises when name is None and image is set.
            name = member.name
            existing = self.client_endpoints.get(name)
            record = {
                "var_name": member_name,
                "file_path": file_path,
                "module_path": module_path,
                "object_id": id(member),
                "image": member.image,
            }
            if existing is None:
                self.client_endpoints[name] = record
                continue
            if existing["object_id"] == id(member):
                continue  # aliased under a second variable name
            if existing["file_path"] == file_path:
                # two distinct objects with the same name in one file: last wins
                self.client_endpoints[name] = record
                continue
            if existing["image"] == member.image:
                # re-exported from another file; keep the first record
                continue
            raise ValueError(
                f"endpoint '{name}' is defined in multiple files: "
                f"{existing['file_path']}, {file_path}. "
                f"each endpoint name must be unique across the project."
            )

    def _populate_resource_dicts(self, functions: List[RemoteFunctionMetadata]) -> None:
        """populate resource tracking dicts for ManifestBuilder compatibility."""
        for f in functions:
            name = f.resource_config_name
            if name in self.resource_configs:
                continue

            self.resource_configs[name] = name
            self.resource_types[name] = f.resource_type
            self.resource_flags[name] = {
                "is_load_balanced": f.is_load_balanced,
                "is_live_resource": f.is_live_resource,
            }
            if f.config_variable:
                self.resource_variables[name] = f.config_variable
