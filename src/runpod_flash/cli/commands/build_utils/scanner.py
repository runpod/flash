"""project scanner for discovering @remote decorated functions and classes.

imports user modules and inspects live objects via their __remote_config__
attribute (stamped by @remote and Endpoint). this handles all python
language constructs without needing to rebuild an interpreter via AST.
"""

import ast
import importlib.util
import inspect
import logging
import os
import signal
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

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

    on unix, raises TimeoutError if the module takes longer than
    MODULE_IMPORT_TIMEOUT_SECONDS to execute. on windows the timeout
    is skipped because signal.SIGALRM is not available.
    """
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if not spec or not spec.loader:
        return None

    module = importlib.util.module_from_spec(spec)
    old_module = sys.modules.get(module_name)
    sys.modules[module_name] = module

    use_alarm = hasattr(signal, "SIGALRM")
    old_handler = None

    def _timeout_handler(signum: int, frame: Any) -> None:
        raise TimeoutError(
            f"import of {file_path.name} timed out after "
            f"{MODULE_IMPORT_TIMEOUT_SECONDS}s (module-level code may be blocking)"
        )

    try:
        if use_alarm:
            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(MODULE_IMPORT_TIMEOUT_SECONDS)

        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module
    except TimeoutError:
        raise
    except Exception as e:
        logger.debug("failed to import %s: %s", file_path.name, e)
        raise
    finally:
        if use_alarm:
            signal.alarm(0)
            if old_handler is not None:
                signal.signal(signal.SIGALRM, old_handler)
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


def _analyze_cross_calls_ast(
    file_path: Path,
    function_names: Set[str],
    remote_function_names: Set[str],
) -> Dict[str, List[str]]:
    """find which functions call other @remote functions via AST.

    returns a dict of function_name -> list of called remote function names.
    only matches direct calls (foo()), not attribute calls (obj.foo()).
    """
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

        called: List[str] = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                if child.func.id in remote_function_names:
                    if child.func.id not in called:
                        called.append(child.func.id)
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

        try:
            for py_file in py_files:
                module_path = file_to_module_path(py_file, self.project_dir)
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

                file_functions = self._extract_from_module(
                    module, module_path, py_file, seen_functions
                )
                functions.extend(file_functions)

            # cross-call analysis
            remote_names = {f.function_name for f in functions}
            files_with_functions: Dict[Path, Set[str]] = {}
            for f in functions:
                files_with_functions.setdefault(f.file_path, set()).add(f.function_name)

            for file_path, func_names in files_with_functions.items():
                calls = _analyze_cross_calls_ast(file_path, func_names, remote_names)
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
