"""AST scanner for discovering @remote decorated functions and classes."""

import ast
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from runpod_flash.cli.utils.ignore import get_file_tree, load_ignore_patterns

logger = logging.getLogger(__name__)


def file_to_url_prefix(file_path: Path, project_root: Path) -> str:
    """Derive the local dev server URL prefix from a source file path.

    Args:
        file_path: Absolute path to the Python source file
        project_root: Absolute path to the project root directory

    Returns:
        URL prefix starting with "/" (e.g., /longruns/stage1)

    Example:
        longruns/stage1.py  →  /longruns/stage1
    """
    rel = file_path.relative_to(project_root).with_suffix("")
    return "/" + str(rel).replace(os.sep, "/")


def file_to_resource_name(file_path: Path, project_root: Path) -> str:
    """Derive the manifest resource name from a source file path.

    Slashes and hyphens are replaced with underscores to produce a valid
    Python identifier suitable for use as a resource name.

    Args:
        file_path: Absolute path to the Python source file
        project_root: Absolute path to the project root directory

    Returns:
        Resource name using underscores (e.g., longruns_stage1)

    Example:
        longruns/stage1.py  →  longruns_stage1
        my-worker.py        →  my_worker
    """
    rel = file_path.relative_to(project_root).with_suffix("")
    return str(rel).replace(os.sep, "_").replace("/", "_").replace("-", "_")


def file_to_module_path(file_path: Path, project_root: Path) -> str:
    """Derive the Python dotted module path from a source file path.

    Args:
        file_path: Absolute path to the Python source file
        project_root: Absolute path to the project root directory

    Returns:
        Dotted module path (e.g., longruns.stage1)

    Example:
        longruns/stage1.py  →  longruns.stage1
    """
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
    http_method: Optional[str] = None  # HTTP method for LB endpoints: GET, POST, etc.
    http_path: Optional[str] = None  # HTTP path for LB endpoints: /api/process
    is_load_balanced: bool = False  # LoadBalancerSlsResource or LiveLoadBalancer
    is_live_resource: bool = (
        False  # LiveLoadBalancer (vs deployed LoadBalancerSlsResource)
    )
    config_variable: Optional[str] = None  # Variable name like "gpu_config"
    calls_remote_functions: bool = (
        False  # Does this function call other @remote functions?
    )
    called_remote_functions: List[str] = field(
        default_factory=list
    )  # Names of @remote functions called
    is_lb_route_handler: bool = (
        False  # LB @remote with method= and path= — runs directly as HTTP handler
    )
    class_methods: List[str] = field(
        default_factory=list
    )  # Public methods for @remote classes
    param_names: List[str] = field(
        default_factory=list
    )  # Function params excluding self
    class_method_params: Dict[str, List[str]] = field(
        default_factory=dict
    )  # method_name -> param_names (for classes)
    docstring: Optional[str] = None  # First line of function/class docstring
    class_method_docstrings: Dict[str, Optional[str]] = field(
        default_factory=dict
    )  # method_name -> first line of docstring


class RemoteDecoratorScanner:
    """Scans Python files for @remote decorators and extracts metadata."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.py_files: List[Path] = []
        self.resource_configs: Dict[str, str] = {}  # name -> name
        self.resource_types: Dict[str, str] = {}  # name -> type
        self.resource_flags: Dict[str, Dict[str, bool]] = {}  # name -> {flag: bool}
        self.resource_variables: Dict[str, str] = {}  # name -> variable_name

    def discover_remote_functions(self) -> List[RemoteFunctionMetadata]:
        """Discover all @remote decorated functions and classes."""
        functions = []

        # Use .gitignore / .flashignore aware file walker with early directory pruning.
        # This avoids descending into .venv, __pycache__, .flash, etc.
        spec = load_ignore_patterns(self.project_dir)
        all_files = get_file_tree(self.project_dir, spec)
        self.py_files = [
            f for f in all_files if f.suffix == ".py" and f.name != "__init__.py"
        ]

        # First pass: extract all resource configs from all files
        for py_file in self.py_files:
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content)
                self._extract_resource_configs(tree, py_file)
            except UnicodeDecodeError:
                pass
            except SyntaxError as e:
                logger.warning(f"Syntax error in {py_file}: {e}")
            except Exception:
                pass

        # Second pass: extract @remote decorated functions
        for py_file in self.py_files:
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content)
                functions.extend(self._extract_remote_functions(tree, py_file))
            except UnicodeDecodeError:
                pass
            except SyntaxError as e:
                logger.warning(f"Syntax error in {py_file}: {e}")
            except Exception:
                pass

        # Third pass: analyze function call graphs
        remote_function_names = {f.function_name for f in functions}
        for py_file in self.py_files:
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content)

                # Build a map of function name -> function node for this file (single pass)
                func_node_map: Dict[str, ast.AST] = {}
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        # Store first occurrence if multiple functions share same name
                        func_node_map.setdefault(node.name, node)

                # Find each @remote function and analyze its calls
                for func_meta in [f for f in functions if f.file_path == py_file]:
                    node = func_node_map.get(func_meta.function_name)
                    if node is not None:
                        self._analyze_function_calls(
                            node, func_meta, remote_function_names
                        )
            except UnicodeDecodeError:
                pass
            except SyntaxError as e:
                logger.warning(f"Syntax error in {py_file}: {e}")
            except Exception:
                pass

        return functions

    def _extract_resource_configs(self, tree: ast.AST, py_file: Path) -> None:
        """Extract resource config variable assignments and determine type flags.

        This method extracts resource configurations and determines is_load_balanced
        and is_live_resource flags using string-based type matching.
        """
        module_path = self._get_module_path(py_file)

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                # Look for assignments like: gpu_config = LiveServerless(...) or api = LiveLoadBalancer(...)
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        variable_name = target.id
                        config_type = self._get_call_type(node.value)

                        # Accept any class that looks like a resource config (DeployableResource)
                        if config_type and self._is_resource_config_type(config_type):
                            # Extract the resource's name parameter (the actual identifier)
                            # If extraction fails, fall back to variable name
                            resource_name = self._extract_resource_name(node.value)
                            if not resource_name:
                                resource_name = variable_name

                            # Store mapping using the resource's name (or variable name as fallback)
                            self.resource_configs[resource_name] = resource_name
                            self.resource_types[resource_name] = config_type

                            # Store variable name for test-mothership config discovery
                            self.resource_variables[resource_name] = variable_name

                            # Also store variable name mapping for local lookups in same module
                            var_key = f"{module_path}:{variable_name}"
                            self.resource_configs[var_key] = resource_name
                            self.resource_types[var_key] = config_type
                            self.resource_variables[var_key] = variable_name

                            # Determine boolean flags using string-based type checking
                            # This is determined by isinstance() at scan time in production,
                            # but we use string matching for reliability
                            is_load_balanced = config_type in [
                                "LoadBalancerSlsResource",
                                "LiveLoadBalancer",
                                "CpuLiveLoadBalancer",
                            ]
                            is_live_resource = config_type in [
                                "LiveLoadBalancer",
                                "CpuLiveLoadBalancer",
                            ]

                            # Store flags for this resource
                            self.resource_flags[resource_name] = {
                                "is_load_balanced": is_load_balanced,
                                "is_live_resource": is_live_resource,
                            }
                            # Also store for variable key
                            self.resource_flags[var_key] = {
                                "is_load_balanced": is_load_balanced,
                                "is_live_resource": is_live_resource,
                            }

    def _extract_remote_functions(
        self, tree: ast.AST, py_file: Path
    ) -> List[RemoteFunctionMetadata]:
        """Extract @remote decorated functions and classes."""
        module_path = self._get_module_path(py_file)
        functions = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # Check if this node has @remote decorator
                remote_decorator = self._find_remote_decorator(node.decorator_list)

                if remote_decorator:
                    # Extract resource config name from decorator
                    resource_config_name = self._extract_resource_config_name(
                        remote_decorator, module_path
                    )

                    if resource_config_name:
                        is_async = isinstance(node, ast.AsyncFunctionDef)
                        is_class = isinstance(node, ast.ClassDef)

                        # Get resource type for this config
                        resource_type = self._get_resource_type(resource_config_name)

                        # Extract HTTP routing metadata (for LB endpoints)
                        http_method, http_path = self._extract_http_routing(
                            remote_decorator
                        )

                        # Get flags for this resource
                        flags = self.resource_flags.get(
                            resource_config_name,
                            {"is_load_balanced": False, "is_live_resource": False},
                        )

                        # An LB route handler is an LB @remote function that has
                        # both method= and path= declared. Its body runs directly
                        # on the LB endpoint — it is NOT a remote dispatch stub.
                        is_lb_route_handler = (
                            flags["is_load_balanced"]
                            and http_method is not None
                            and http_path is not None
                        )

                        # Extract docstring (first line only)
                        raw_docstring = ast.get_docstring(node)
                        docstring: Optional[str] = None
                        if raw_docstring:
                            docstring = raw_docstring.split("\n")[0].strip()

                        # Extract public methods for @remote classes
                        class_methods: List[str] = []
                        class_method_params: Dict[str, List[str]] = {}
                        class_method_docstrings: Dict[str, Optional[str]] = {}
                        if is_class:
                            for n in node.body:
                                if isinstance(
                                    n, (ast.FunctionDef, ast.AsyncFunctionDef)
                                ) and not n.name.startswith("_"):
                                    class_methods.append(n.name)
                                    class_method_params[n.name] = [
                                        arg.arg
                                        for arg in n.args.args
                                        if arg.arg != "self"
                                    ]
                                    raw_method_doc = ast.get_docstring(n)
                                    if raw_method_doc:
                                        class_method_docstrings[n.name] = (
                                            raw_method_doc.split("\n")[0].strip()
                                        )
                                    else:
                                        class_method_docstrings[n.name] = None

                        # Extract param names for functions (not classes)
                        param_names: List[str] = []
                        if not is_class and isinstance(
                            node, (ast.FunctionDef, ast.AsyncFunctionDef)
                        ):
                            param_names = [
                                arg.arg for arg in node.args.args if arg.arg != "self"
                            ]

                        metadata = RemoteFunctionMetadata(
                            function_name=node.name,
                            module_path=module_path,
                            resource_config_name=resource_config_name,
                            resource_type=resource_type,
                            is_async=is_async,
                            is_class=is_class,
                            file_path=py_file,
                            http_method=http_method,
                            http_path=http_path,
                            is_load_balanced=flags["is_load_balanced"],
                            is_live_resource=flags["is_live_resource"],
                            config_variable=self.resource_variables.get(
                                resource_config_name
                            ),
                            is_lb_route_handler=is_lb_route_handler,
                            class_methods=class_methods,
                            param_names=param_names,
                            class_method_params=class_method_params,
                            docstring=docstring,
                            class_method_docstrings=class_method_docstrings,
                        )
                        functions.append(metadata)

        return functions

    def _find_remote_decorator(self, decorators: List[ast.expr]) -> Optional[ast.expr]:
        """Find @remote decorator in a list of decorators."""
        for decorator in decorators:
            # Handle @remote or @remote(...)
            if isinstance(decorator, ast.Name):
                if decorator.id == "remote":
                    return decorator
            elif isinstance(decorator, ast.Call):
                if isinstance(decorator.func, ast.Name):
                    if decorator.func.id == "remote":
                        return decorator
                elif isinstance(decorator.func, ast.Attribute):
                    if decorator.func.attr == "remote":
                        return decorator

        return None

    def _extract_resource_config_name(
        self, decorator: ast.expr, module_path: str
    ) -> Optional[str]:
        """Extract resource_config name from @remote decorator."""
        if isinstance(decorator, ast.Name):
            # @remote without arguments
            return None

        if isinstance(decorator, ast.Call):
            # @remote(...) with arguments
            # Look for resource_config= or first positional arg
            for keyword in decorator.keywords:
                if keyword.arg == "resource_config":
                    return self._extract_name_from_expr(keyword.value, module_path)

            # Try first positional argument
            if decorator.args:
                return self._extract_name_from_expr(decorator.args[0], module_path)

        return None

    def _extract_name_from_expr(
        self, expr: ast.expr, module_path: str
    ) -> Optional[str]:
        """Extract config name from an expression (Name or Call).

        Returns the resource's name (from the name= parameter), not the variable name.
        """
        if isinstance(expr, ast.Name):
            # Variable reference: @remote(gpu_config)
            variable_name = expr.id

            # Try module-scoped lookup first (current module)
            var_key = f"{module_path}:{variable_name}"
            if var_key in self.resource_configs:
                # Return the actual resource name (mapped from variable)
                return self.resource_configs[var_key]

            # Try simple name lookup
            if variable_name in self.resource_configs:
                return self.resource_configs[variable_name]

            # Fall back to the variable name itself (unresolved reference)
            return variable_name

        elif isinstance(expr, ast.Call):
            # Direct instantiation: @remote(LiveServerless(name="gpu_config"))
            # Extract the name= parameter
            resource_name = self._extract_resource_name(expr)
            if resource_name:
                return resource_name

        return None

    # All ServerlessResource subclasses exported by runpod_flash.__init__.py.
    # Checked at test time by test_resource_config_types_matches_exports().
    _RESOURCE_CONFIG_TYPES = frozenset(
        {
            "ServerlessEndpoint",
            "CpuServerlessEndpoint",
            "LoadBalancerSlsResource",
            "CpuLoadBalancerSlsResource",
            "LiveServerless",
            "CpuLiveServerless",
            "LiveLoadBalancer",
            "CpuLiveLoadBalancer",
        }
    )

    def _is_resource_config_type(self, type_name: str) -> bool:
        """Check if a type name is a known ServerlessResource subclass."""
        return type_name in self._RESOURCE_CONFIG_TYPES

    def _get_call_type(self, expr: ast.expr) -> Optional[str]:
        """Get the type name of a call expression."""
        if isinstance(expr, ast.Call):
            if isinstance(expr.func, ast.Name):
                return expr.func.id
            elif isinstance(expr.func, ast.Attribute):
                return expr.func.attr

        return None

    def _extract_resource_name(self, expr: ast.expr) -> Optional[str]:
        """Extract the 'name' parameter from a resource config instantiation.

        For example, from LiveServerless(name="01_01_gpu_worker", ...)
        returns "01_01_gpu_worker".
        """
        if isinstance(expr, ast.Call):
            for keyword in expr.keywords:
                if keyword.arg == "name":
                    if isinstance(keyword.value, ast.Constant):
                        return keyword.value.value
        return None

    def _analyze_function_calls(
        self,
        func_node: ast.AST,
        function_metadata: RemoteFunctionMetadata,
        remote_function_names: set[str],
    ) -> None:
        """Analyze if a function calls other @remote functions.

        Args:
            func_node: AST node for the function
            function_metadata: Metadata to update with call information
            remote_function_names: Set of all @remote function names
        """
        # Walk AST looking for function calls
        for node in ast.walk(func_node):
            if isinstance(node, ast.Call):
                # Handle direct calls: some_function()
                if isinstance(node.func, ast.Name):
                    called_name = node.func.id
                    if called_name in remote_function_names:
                        function_metadata.calls_remote_functions = True
                        if called_name not in function_metadata.called_remote_functions:
                            function_metadata.called_remote_functions.append(
                                called_name
                            )

                # Handle attribute calls: obj.some_function()
                elif isinstance(node.func, ast.Attribute):
                    called_name = node.func.attr
                    if called_name in remote_function_names:
                        function_metadata.calls_remote_functions = True
                        if called_name not in function_metadata.called_remote_functions:
                            function_metadata.called_remote_functions.append(
                                called_name
                            )

    def _get_resource_type(self, resource_config_name: str) -> str:
        """Get the resource type for a given config name."""
        if resource_config_name in self.resource_types:
            return self.resource_types[resource_config_name]
        # Default to LiveServerless if type not found
        return "LiveServerless"

    def _sanitize_resource_name(self, name: str) -> str:
        """Sanitize resource config name for use in filenames.

        Replaces invalid filename characters with underscores and ensures
        the name starts with a letter or underscore (valid for Python identifiers).

        Args:
            name: Raw resource config name

        Returns:
            Sanitized name safe for use in filenames and as Python identifiers
        """
        # Replace invalid characters with underscores
        sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)

        # Ensure it starts with a letter or underscore
        if sanitized and not (sanitized[0].isalpha() or sanitized[0] == "_"):
            sanitized = f"_{sanitized}"

        return sanitized or "_"

    def _get_module_path(self, py_file: Path) -> str:
        """Convert file path to module path."""
        try:
            # Get relative path from project directory
            rel_path = py_file.relative_to(self.project_dir)

            # Remove .py extension and convert / to .
            module = str(rel_path.with_suffix("")).replace("/", ".").replace("\\", ".")

            return module
        except ValueError:
            # If relative_to fails, just use filename
            return py_file.stem

    def _extract_http_routing(
        self, decorator: ast.expr
    ) -> tuple[Optional[str], Optional[str]]:
        """Extract HTTP method and path from @remote decorator.

        Returns:
            Tuple of (method, path) or (None, None) if not found.
            method: GET, POST, PUT, DELETE, PATCH
            path: /api/endpoint routes

        Raises:
            ValueError: If method is not a valid HTTP verb
        """
        if not isinstance(decorator, ast.Call):
            return None, None

        http_method = None
        http_path = None

        # Extract keyword arguments: method="POST", path="/api/process"
        for keyword in decorator.keywords:
            if keyword.arg == "method":
                if isinstance(keyword.value, ast.Constant):
                    http_method = keyword.value.value
            elif keyword.arg == "path":
                if isinstance(keyword.value, ast.Constant):
                    http_path = keyword.value.value

        # Validate HTTP method if provided
        valid_methods = {"GET", "POST", "PUT", "DELETE", "PATCH"}
        if http_method is not None and http_method.upper() not in valid_methods:
            raise ValueError(
                f"Invalid HTTP method '{http_method}'. Must be one of: {', '.join(valid_methods)}"
            )

        return http_method, http_path


def detect_main_app(
    project_root: Path, explicit_mothership_exists: bool = False
) -> Optional[dict]:
    """Detect main.py FastAPI app and return mothership config.

    Searches for main.py/app.py/server.py and parses AST to find FastAPI app.
    Only returns config if app has custom routes (not just @remote calls).

    Args:
        project_root: Root directory of Flash project
        explicit_mothership_exists: If True, skip auto-detection (explicit config takes precedence)

    Returns:
        Dict with app metadata: {
            'file_path': Path,
            'app_variable': str,
            'has_routes': bool,
        }
        Returns None if no FastAPI app found with custom routes or explicit_mothership_exists is True.
    """
    if explicit_mothership_exists:
        # Explicit mothership config exists, skip auto-detection
        return None
    for filename in ["main.py", "app.py", "server.py"]:
        main_path = project_root / filename
        if not main_path.exists():
            continue

        try:
            content = main_path.read_text(encoding="utf-8")
            tree = ast.parse(content)

            # Find FastAPI app instantiation
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    if isinstance(node.value, ast.Call):
                        call_type = None
                        if isinstance(node.value.func, ast.Name):
                            call_type = node.value.func.id
                        elif isinstance(node.value.func, ast.Attribute):
                            call_type = node.value.func.attr

                        if call_type == "FastAPI":
                            app_variable = None
                            for target in node.targets:
                                if isinstance(target, ast.Name):
                                    app_variable = target.id
                                    break

                            if app_variable:
                                # Check for custom routes (not just @remote)
                                has_routes = _has_custom_routes(tree, app_variable)

                                # 1. Extract direct app routes
                                module_path = filename.replace(".py", "")
                                app_routes = _extract_fastapi_routes(
                                    tree, app_variable, module_path
                                )

                                # 2. Find included routers
                                included_routers = _find_included_routers(
                                    tree, app_variable
                                )

                                # 3. Extract routes from each included router
                                router_routes = []
                                for router_var, prefix in included_routers:
                                    router_file = _resolve_router_import(
                                        router_var, tree, main_path, project_root
                                    )
                                    if router_file and router_file.exists():
                                        try:
                                            router_content = router_file.read_text(
                                                encoding="utf-8"
                                            )
                                            router_tree = ast.parse(router_content)
                                            router_module = router_file.stem

                                            routes = _extract_router_routes(
                                                router_tree,
                                                router_var,
                                                router_module,
                                                prefix,
                                                router_file,
                                            )
                                            router_routes.extend(routes)
                                        except (
                                            UnicodeDecodeError,
                                            SyntaxError,
                                            PermissionError,
                                            OSError,
                                        ) as e:
                                            logger.debug(
                                                f"Failed to parse router file {router_file}: {e}"
                                            )

                                # 4. Combine all routes
                                all_fastapi_routes = app_routes + router_routes

                                # 5. Update file_path for all routes
                                for route in all_fastapi_routes:
                                    if route.file_path == Path(module_path):
                                        route.file_path = main_path

                                return {
                                    "file_path": main_path,
                                    "app_variable": app_variable,
                                    "has_routes": has_routes
                                    or bool(all_fastapi_routes),
                                    "fastapi_routes": all_fastapi_routes,
                                }
        except UnicodeDecodeError:
            logger.debug(f"Skipping non-UTF-8 file: {main_path}")
        except SyntaxError as e:
            logger.debug(f"Syntax error in {main_path}: {e}")
        except Exception as e:
            logger.debug(f"Failed to parse {main_path}: {e}")

    return None


def _has_custom_routes(tree: ast.AST, app_variable: str) -> bool:
    """Check if FastAPI app has custom routes (beyond @remote).

    Args:
        tree: AST tree of the file
        app_variable: Name of the FastAPI app variable

    Returns:
        True if app has route decorators (app.get, app.post, etc.)
    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                # Look for app.get(), app.post(), app.put(), etc.
                if isinstance(decorator, ast.Call):
                    if isinstance(decorator.func, ast.Attribute):
                        if (
                            isinstance(decorator.func.value, ast.Name)
                            and decorator.func.value.id == app_variable
                            and decorator.func.attr
                            in ["get", "post", "put", "delete", "patch"]
                        ):
                            return True
                # Also check for @app.get without parentheses (decorator without Call)
                elif isinstance(decorator, ast.Attribute):
                    if (
                        isinstance(decorator.value, ast.Name)
                        and decorator.value.id == app_variable
                        and decorator.attr in ["get", "post", "put", "delete", "patch"]
                    ):
                        return True

    return False


def _find_included_routers(tree: ast.AST, app_variable: str) -> List[Tuple[str, str]]:
    """Find all routers included in FastAPI app via include_router().

    Args:
        tree: AST of the main file
        app_variable: FastAPI app variable name (e.g., 'app')

    Returns:
        List of (router_variable_name, prefix) tuples
        Example: [('user_router', '/users'), ('api_router', '/api')]
    """
    included_routers = []

    for node in ast.walk(tree):
        # Look for: app.include_router(router_var, prefix="/path", ...)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value

            # Check if it's app.include_router
            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "include_router"
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == app_variable
            ):
                # Extract router variable from first positional arg
                if call.args and isinstance(call.args[0], ast.Name):
                    router_var = call.args[0].id

                    # Extract prefix from keyword args
                    prefix = ""
                    for keyword in call.keywords:
                        if keyword.arg == "prefix" and isinstance(
                            keyword.value, ast.Constant
                        ):
                            prefix = keyword.value.value

                    included_routers.append((router_var, prefix))

    return included_routers


def _resolve_router_import(
    router_variable: str, tree: ast.AST, main_file_path: Path, project_root: Path
) -> Optional[Path]:
    """Resolve router variable to its source file via import statements.

    Args:
        router_variable: Name like 'user_router'
        tree: AST of main.py
        main_file_path: Path to main.py
        project_root: Project root directory

    Returns:
        Path to module defining the router, or None if not found
    """
    for node in ast.walk(tree):
        # Handle: from module import router_variable
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported_name = alias.asname if alias.asname else alias.name
                if imported_name == router_variable:
                    # Found the import!
                    module_path = node.module
                    if not module_path:
                        continue

                    # Handle relative imports
                    if node.level > 0:
                        # Relative import (e.g., from .routers import user_router)
                        parent_dir = main_file_path.parent
                        for _ in range(node.level - 1):
                            parent_dir = parent_dir.parent
                        module_parts = module_path.split(".") if module_path else []
                        target_path = parent_dir.joinpath(*module_parts)
                    else:
                        # Absolute import (e.g., from routers.users import user_router)
                        module_parts = module_path.split(".")
                        target_path = project_root.joinpath(*module_parts)

                    # Try both .py file and __init__.py in package
                    py_file = target_path.with_suffix(".py")
                    if py_file.exists():
                        return py_file

                    init_file = target_path / "__init__.py"
                    if init_file.exists():
                        return init_file

    return None


# Supported HTTP methods for route extraction
SUPPORTED_HTTP_METHODS = ["get", "post", "put", "delete", "patch", "options", "head"]


def _normalize_route_path(url_prefix: str, http_path: str) -> str:
    """Normalize URL path by combining prefix and path with proper slashes.

    Args:
        url_prefix: URL prefix (e.g., '/users' or '')
        http_path: HTTP path (e.g., '/' or '/list')

    Returns:
        Normalized path starting with '/' (e.g., '/users/list')
    """
    # Handle empty cases
    if not url_prefix and not http_path:
        return "/"
    if not url_prefix:
        return f"/{http_path.lstrip('/')}" if http_path else "/"
    if not http_path or http_path == "/":
        # When path is just "/", append it to prefix
        return f"/{url_prefix.strip('/')}/"

    # Combine prefix and path
    prefix_part = url_prefix.strip("/")
    path_part = http_path.lstrip("/")

    return f"/{prefix_part}/{path_part}"


def _extract_routes_from_decorator(
    tree: ast.AST,
    decorator_object: str,
    module_path: str,
    url_prefix: str,
    file_path: Path,
) -> List[RemoteFunctionMetadata]:
    """Extract routes from decorators (@app.get, @router.post, etc.).

    Unified implementation for both FastAPI app and APIRouter route extraction.

    Args:
        tree: AST of the file
        decorator_object: Variable name ('app', 'user_router', etc.)
        module_path: Module path for imports
        url_prefix: URL prefix to prepend (empty string for no prefix)
        file_path: Path to the source file

    Returns:
        List of RemoteFunctionMetadata for discovered routes
    """
    routes = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        for decorator in node.decorator_list:
            # Look for @decorator_object.METHOD(...) pattern
            if not isinstance(decorator, ast.Call):
                continue

            if not isinstance(decorator.func, ast.Attribute):
                continue

            # Check decorator object match
            if not (
                isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == decorator_object
            ):
                continue

            # Get HTTP method
            method = decorator.func.attr
            if method not in SUPPORTED_HTTP_METHODS:
                continue

            # Extract path from first positional argument
            http_path = None
            if decorator.args and isinstance(decorator.args[0], ast.Constant):
                http_path = decorator.args[0].value

            if not http_path:
                continue

            # Normalize path with prefix
            full_path = _normalize_route_path(url_prefix, http_path)

            routes.append(
                RemoteFunctionMetadata(
                    function_name=node.name,
                    module_path=module_path,
                    resource_config_name="mothership",
                    resource_type="CpuLiveLoadBalancer",
                    is_async=isinstance(node, ast.AsyncFunctionDef),
                    is_class=False,
                    file_path=file_path,
                    http_method=method.upper(),
                    http_path=full_path,
                    is_load_balanced=True,
                    is_live_resource=True,
                    config_variable=None,
                )
            )
            break  # Only process first matching decorator per function

    return routes


def _extract_router_routes(
    tree: ast.AST,
    router_variable: str,
    module_path: str,
    url_prefix: str,
    router_file: Path,
) -> List[RemoteFunctionMetadata]:
    """Extract routes from APIRouter decorators (@router.get, etc.).

    Args:
        tree: AST of module containing the router
        router_variable: Router variable name (e.g., 'user_router')
        module_path: Module path for imports
        url_prefix: URL prefix from include_router (e.g., '/users')
        router_file: Path to router file

    Returns:
        Routes with prefixed paths
    """
    return _extract_routes_from_decorator(
        tree, router_variable, module_path, url_prefix, router_file
    )


def _extract_fastapi_routes(
    tree: ast.AST, app_variable: str, module_path: str
) -> List[RemoteFunctionMetadata]:
    """Extract routes from FastAPI decorators (@app.get, @app.post, etc.).

    Args:
        tree: AST tree of the file
        app_variable: FastAPI app variable name (e.g., 'app', 'router')
        module_path: Module import path (e.g., 'main')

    Returns:
        List of RemoteFunctionMetadata for each FastAPI route found
    """
    # Use unified extraction with no prefix and placeholder path
    # The caller will update file_path with the actual path
    return _extract_routes_from_decorator(
        tree, app_variable, module_path, "", Path(module_path)
    )


def detect_explicit_mothership(project_root: Path) -> Optional[Dict]:
    """Detect explicitly configured mothership resource in mothership.py.

    Parses mothership.py to extract resource configuration.

    Args:
        project_root: Root directory of Flash project

    Returns:
        Dict with mothership config if found:
            {
                'resource_type': str (e.g., 'CpuLiveLoadBalancer'),
                'name': str,
                'workersMin': int,
                'workersMax': int,
                'is_explicit': bool,
            }
        Returns None if mothership.py doesn't exist or can't be parsed.
    """
    mothership_file = project_root / "mothership.py"

    if not mothership_file.exists():
        return None

    try:
        content = mothership_file.read_text(encoding="utf-8")
        tree = ast.parse(content)

        # Look for variable assignment: mothership = SomeResource(...)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "mothership":
                        # Found mothership variable assignment
                        if isinstance(node.value, ast.Call):
                            resource_type = _extract_resource_type(node.value)
                            kwargs = _extract_call_kwargs(node.value)

                            return {
                                "resource_type": resource_type,
                                "name": kwargs.get("name", "mothership"),
                                "workersMin": kwargs.get("workersMin", 1),
                                "workersMax": kwargs.get("workersMax", 1),
                                "is_explicit": True,
                            }

        return None

    except UnicodeDecodeError:
        logger.debug(f"Skipping non-UTF-8 file: {mothership_file}")
        return None
    except SyntaxError as e:
        logger.debug(f"Syntax error in mothership.py: {e}")
        return None
    except Exception as e:
        logger.debug(f"Failed to parse mothership.py: {e}")
        return None


def _extract_resource_type(call_node: ast.Call) -> str:
    """Extract resource type from Call node.

    Args:
        call_node: AST Call node representing resource instantiation

    Returns:
        Resource type name (e.g., 'CpuLiveLoadBalancer'), or default if not found
    """
    if isinstance(call_node.func, ast.Name):
        return call_node.func.id
    elif isinstance(call_node.func, ast.Attribute):
        return call_node.func.attr
    return "CpuLiveLoadBalancer"  # Default


def _extract_call_kwargs(call_node: ast.Call) -> Dict:
    """Extract keyword arguments from Call node.

    Args:
        call_node: AST Call node

    Returns:
        Dict of keyword arguments with evaluated values (numbers, strings)
    """
    kwargs = {}
    for keyword in call_node.keywords:
        if keyword.arg:
            try:
                # Try to evaluate simple literal values
                kwargs[keyword.arg] = ast.literal_eval(keyword.value)
            except (ValueError, SyntaxError, TypeError):
                # Skip non-literal arguments
                pass
    return kwargs
