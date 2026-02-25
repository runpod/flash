"""Resource discovery for auto-provisioning during flash run startup."""

import ast
import importlib.util
import logging
import sys
from pathlib import Path
from typing import Dict, List, Set

from .resources.base import DeployableResource

log = logging.getLogger(__name__)


class ResourceDiscovery:
    """Discovers DeployableResource instances by parsing @remote decorators."""

    def __init__(self, entry_point: str, max_depth: int = 2):
        """Initialize resource discovery.

        Args:
            entry_point: Path to entry point file (e.g., "main.py")
            max_depth: Maximum depth for recursive module scanning
        """
        self.entry_point = Path(entry_point)
        self.max_depth = max_depth
        self._cache: Dict[str, List[DeployableResource]] = {}
        self._scanned_modules: Set[str] = set()

    def discover(self) -> List[DeployableResource]:
        """Discover all DeployableResource instances in entry point and imports.

        Returns:
            List of discovered deployable resources
        """
        if str(self.entry_point) in self._cache:
            return self._cache[str(self.entry_point)]

        resources = []

        try:
            # Parse entry point to find @remote decorators
            resource_var_names = self._find_resource_config_vars(self.entry_point)

            # Import entry point module to resolve variables (if any found)
            if resource_var_names:
                module = self._import_module(self.entry_point)

                if module:
                    # Resolve variable names to actual DeployableResource objects
                    for var_name in resource_var_names:
                        resource = self._resolve_resource_variable(module, var_name)
                        if resource:
                            resources.append(resource)
                else:
                    log.warning(f"Failed to import {self.entry_point}")

            log.info(f"[Discovery] After entry point: {len(resources)} resource(s)")

            # Recursively scan imported modules (static imports)
            imported_resources = self._scan_imports(self.entry_point, depth=1)
            resources.extend(imported_resources)

            log.info(f"[Discovery] After static imports: {len(resources)} resource(s)")

            # Fallback: Scan project directory for Python files with @remote decorators
            # This handles dynamic imports (importlib.util) that AST parsing misses
            if not resources:
                log.debug(
                    "No resources found via static imports, scanning project directory"
                )
                directory_resources = self._scan_project_directory()
                resources.extend(directory_resources)
                log.info(
                    f"[Discovery] After directory scan: {len(resources)} resource(s)"
                )

            log.info(f"[Discovery] Total: {len(resources)} resource(s) discovered")
            for res in resources:
                res_name = getattr(res, "name", "Unknown")
                res_type = res.__class__.__name__
                log.info(f"[Discovery]   • {res_name} ({res_type})")

            # Cache results
            self._cache[str(self.entry_point)] = resources

        except Exception as e:
            log.error(f"Error discovering resources in {self.entry_point}: {e}")

        return resources

    def _find_resource_config_vars(self, file_path: Path) -> Set[str]:
        """Find variable names used in @remote or @Endpoint decorators via AST parsing.

        Detects:
        - @remote(resource_config=var) / @remote(var) patterns
        - ep = Endpoint(...) variables used as LB route decorators (@ep.get, @ep.post, etc)

        Args:
            file_path: Path to Python file to parse

        Returns:
            Set of variable names referenced in decorators
        """
        var_names = set()

        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"))

            # pass 1: find Endpoint variable assignments (ep = Endpoint(...))
            endpoint_vars = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and len(node.targets) == 1:
                    target = node.targets[0]
                    if isinstance(target, ast.Name) and isinstance(node.value, ast.Call):
                        func = node.value.func
                        call_name = None
                        if isinstance(func, ast.Name):
                            call_name = func.id
                        elif isinstance(func, ast.Attribute):
                            call_name = func.attr
                        if call_name == "Endpoint":
                            endpoint_vars.add(target.id)

            # pass 2: find decorator references
            for node in ast.walk(tree):
                if isinstance(
                    node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    for decorator in node.decorator_list:
                        if self._is_remote_decorator(decorator):
                            var_name = self._extract_resource_config_var(decorator)
                            if var_name:
                                var_names.add(var_name)

                        # @ep.get("/path"), @ep.post("/path"), etc
                        elif self._is_endpoint_route_decorator(decorator, endpoint_vars):
                            var_name = self._extract_endpoint_var_from_route(decorator)
                            if var_name:
                                var_names.add(var_name)

        except Exception as e:
            log.warning(f"Failed to parse {file_path}: {e}")

        return var_names

    def _is_endpoint_route_decorator(
        self, decorator: ast.expr, endpoint_vars: Set[str]
    ) -> bool:
        """Check if decorator is @ep.get/post/put/delete/patch for a known Endpoint variable."""
        if not isinstance(decorator, ast.Call):
            return False
        func = decorator.func
        if not isinstance(func, ast.Attribute):
            return False
        if func.attr not in ("get", "post", "put", "delete", "patch"):
            return False
        if isinstance(func.value, ast.Name) and func.value.id in endpoint_vars:
            return True
        return False

    def _extract_endpoint_var_from_route(self, decorator: ast.Call) -> str:
        """Extract the Endpoint variable name from @ep.get("/path") decorator."""
        func = decorator.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            return func.value.id
        return ""

    def _is_remote_decorator(self, decorator: ast.expr) -> bool:
        """Check if decorator is @remote.

        Args:
            decorator: AST decorator node

        Returns:
            True if decorator is @remote
        """
        if isinstance(decorator, ast.Call):
            func_name = None
            if isinstance(decorator.func, ast.Name):
                func_name = decorator.func.id
            elif isinstance(decorator.func, ast.Attribute):
                func_name = decorator.func.attr

            return func_name == "remote"

        return False

    def _extract_resource_config_var(self, decorator: ast.Call) -> str:
        """Extract resource_config variable name from @remote decorator.

        Handles both:
        - @remote(resource_config=my_config)
        - @remote(my_config) (positional argument)

        Args:
            decorator: AST Call node for @remote decorator

        Returns:
            Variable name or empty string
        """
        # Check keyword argument: resource_config=var_name
        for keyword in decorator.keywords:
            if keyword.arg == "resource_config":
                if isinstance(keyword.value, ast.Name):
                    return keyword.value.id

        # Check positional argument: @remote(var_name)
        if decorator.args and isinstance(decorator.args[0], ast.Name):
            return decorator.args[0].id

        return ""

    def _import_module(self, file_path: Path):
        """Import a Python module from file path.

        Args:
            file_path: Path to Python file

        Returns:
            Imported module or None if import fails
        """
        try:
            # Create module spec
            module_name = file_path.stem
            spec = importlib.util.spec_from_file_location(module_name, file_path)

            if not spec or not spec.loader:
                return None

            # Load module
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            self._scanned_modules.add(module_name)

            return module

        except Exception as e:
            log.warning(f"Failed to import {file_path}: {e}")
            return None

    def _resolve_resource_variable(self, module, var_name: str) -> DeployableResource:
        """Resolve variable name to DeployableResource instance.

        Handles both legacy resource config objects (LiveServerless, etc) and
        Endpoint facade objects (unwraps via _build_resource_config()).

        Args:
            module: Imported module
            var_name: Variable name to resolve

        Returns:
            DeployableResource instance or None
        """
        try:
            obj = getattr(module, var_name, None)

            if obj and isinstance(obj, DeployableResource):
                return obj

            # unwrap Endpoint facade to its internal resource config
            if obj and hasattr(obj, "_build_resource_config"):
                resource = obj._build_resource_config()
                if isinstance(resource, DeployableResource):
                    return resource

            if obj is not None:
                log.warning(
                    f"Resource '{var_name}' failed to resolve to DeployableResource "
                    f"(found type: {type(obj).__name__}). "
                    f"Check that '{var_name}' is defined as a ServerlessResource, "
                    f"Endpoint, or other DeployableResource type."
                )

        except Exception as e:
            log.warning(f"Failed to resolve variable '{var_name}': {e}")

        return None

    def _scan_imports(self, file_path: Path, depth: int) -> List[DeployableResource]:
        """Recursively scan imported modules for resources.

        Args:
            file_path: Path to Python file
            depth: Current recursion depth

        Returns:
            List of discovered resources from imports
        """
        if depth > self.max_depth:
            return []

        resources = []

        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"))

            # Find import statements
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name
                        if module_name not in self._scanned_modules:
                            imported_resources = self._scan_imported_module(
                                module_name, depth
                            )
                            resources.extend(imported_resources)

                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module not in self._scanned_modules:
                        imported_resources = self._scan_imported_module(
                            node.module, depth
                        )
                        resources.extend(imported_resources)

        except Exception as e:
            log.debug(f"Failed to scan imports in {file_path}: {e}")

        return resources

    def _scan_imported_module(
        self, module_name: str, depth: int
    ) -> List[DeployableResource]:
        """Scan an imported module for resources.

        Args:
            module_name: Name of module to scan
            depth: Current recursion depth

        Returns:
            List of discovered resources
        """
        resources = []

        try:
            # Try to find module file
            module_path = self._resolve_module_path(module_name)

            if not module_path or not module_path.exists():
                return []

            # Mark as scanned to avoid cycles
            self._scanned_modules.add(module_name)

            # Find resources in this module
            resource_vars = self._find_resource_config_vars(module_path)

            if resource_vars:
                # Import module and resolve variables
                module = self._import_module(module_path)
                if module:
                    for var_name in resource_vars:
                        resource = self._resolve_resource_variable(module, var_name)
                        if resource:
                            resources.append(resource)

            # Recursively scan imports
            imported_resources = self._scan_imports(module_path, depth + 1)
            resources.extend(imported_resources)

        except Exception as e:
            log.debug(f"Failed to scan imported module '{module_name}': {e}")

        return resources

    def _resolve_module_path(self, module_name: str) -> Path:
        """Resolve module name to file path.

        Args:
            module_name: Name of module (e.g., "workers.gpu")

        Returns:
            Path to module file or None
        """
        try:
            # Handle relative imports from entry point directory
            parts = module_name.split(".")
            current_dir = self.entry_point.parent

            # Try as relative path first
            module_path = current_dir.joinpath(*parts)

            # Check for .py file
            if module_path.with_suffix(".py").exists():
                return module_path.with_suffix(".py")

            # Check for package (__init__.py)
            if (module_path / "__init__.py").exists():
                return module_path / "__init__.py"

        except Exception as e:
            log.debug(f"Failed to resolve module path for '{module_name}': {e}")

        return None

    def _scan_project_directory(self) -> List[DeployableResource]:
        """Scan project directory for Python files with @remote decorators.

        This is a fallback for projects that use dynamic imports (importlib.util)
        which cannot be detected via static AST import scanning.

        Returns:
            List of discovered resources
        """
        resources = []
        project_root = self.entry_point.parent

        try:
            # Find all Python files in project (excluding common ignore patterns)
            python_files = []
            for pattern in ["**/*.py"]:
                for file_path in project_root.glob(pattern):
                    # Skip entry point (already processed)
                    if file_path == self.entry_point:
                        continue

                    # Skip common directories
                    rel_path = str(file_path.relative_to(project_root))
                    if any(
                        skip in rel_path
                        for skip in [
                            ".venv/",
                            "venv/",
                            "__pycache__/",
                            ".git/",
                            "site-packages/",
                            ".pytest_cache/",
                            "build/",
                            "dist/",
                            ".tox/",
                            "node_modules/",
                            ".flash/",
                        ]
                    ):
                        continue

                    python_files.append(file_path)

            log.debug(f"Scanning {len(python_files)} Python files in {project_root}")

            # Check each file for @remote or Endpoint decorators
            for file_path in python_files:
                try:
                    # quick check: does file contain relevant patterns?
                    content = file_path.read_text(encoding="utf-8")
                    if "@remote" not in content and "Endpoint" not in content:
                        continue

                    # Find resource config variables via AST
                    resource_vars = self._find_resource_config_vars(file_path)
                    if not resource_vars:
                        continue

                    # Import module and resolve variables
                    module = self._import_module(file_path)
                    if module:
                        for var_name in resource_vars:
                            resource = self._resolve_resource_variable(module, var_name)
                            if resource:
                                resources.append(resource)

                except Exception as e:
                    log.debug(f"Failed to scan {file_path}: {e}")
                    continue

        except Exception as e:
            log.warning(f"Failed to scan project directory: {e}")

        return resources

    def clear_cache(self):
        """Clear discovery cache (for reload mode)."""
        self._cache.clear()
        self._scanned_modules.clear()
