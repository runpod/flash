import ast
import base64
import inspect
import textwrap
import hashlib
import traceback
import threading
import cloudpickle
import logging
from pathlib import Path

from ..core.exceptions import LocalModulePayloadTooLargeError
from ..core.resources import LiveServerless
from ..protos.remote_execution import (
    FunctionRequest,
    FunctionResponse,
    RemoteExecutorStub,
)
from ..runtime.serialization import serialize_args, serialize_kwargs
from .local_modules import MAX_INLINE_MODULE_BYTES, resolve_local_modules

log = logging.getLogger(__name__)


# Global in-memory cache with thread safety
_SERIALIZED_FUNCTION_CACHE = {}
_function_cache_lock = threading.RLock()


def get_function_source(func):
    """Extract the function source code without the decorator."""
    # Unwrap any decorators to get the original function
    func = inspect.unwrap(func)

    # Get the source code of the decorated function
    source = inspect.getsource(func)

    # Dedent the source to handle functions defined in classes or indented contexts
    source = textwrap.dedent(source)

    # Parse the source code
    module = ast.parse(source)

    # Find the function definition node (both sync and async)
    function_def = None
    for node in ast.walk(module):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == func.__name__
        ):
            function_def = node
            break

    if not function_def:
        raise ValueError(f"Could not find function definition for {func.__name__}")

    # Get the line and column offsets
    lineno = function_def.lineno - 1  # Line numbers are 1-based

    # Split into lines and extract just the function part
    lines = source.split("\n")
    function_lines = lines[lineno:]

    # Dedent to remove any extra indentation
    function_source = textwrap.dedent("\n".join(function_lines))

    # Return the function hash for cache key
    source_hash = hashlib.sha256(function_source.encode("utf-8")).hexdigest()

    return function_source, source_hash


def build_modules_map(func_source: str, source_file: str | None) -> dict[str, str]:
    """Collect the endpoint's local-module source for inline shipping.

    Resolves the transitive local-import closure of *func_source* against the
    source file's directory and returns {relative_path: source_text}. Enforces the
    inline size cap.

    Args:
        func_source: Extracted function source (from ``get_function_source``).
        source_file: Absolute path of the file the function was defined in, or
            ``None`` (e.g. functions with no ``__file__``), in which case nothing
            is bundled.

    Raises:
        LocalModulePayloadTooLargeError: total inline source exceeds the cap.
    """
    if not source_file:
        return {}

    project_root = Path(source_file).resolve().parent
    resolved = resolve_local_modules(func_source, source_file, project_root)
    for warning in resolved.warnings:
        log.warning(warning)

    modules: dict[str, str] = {}
    total = len(func_source.encode("utf-8"))
    for rel_path, abs_path in resolved.files.items():
        source = Path(abs_path).read_text(encoding="utf-8")
        total += len(source.encode("utf-8"))
        modules[rel_path] = source

    if total > MAX_INLINE_MODULE_BYTES:
        raise LocalModulePayloadTooLargeError(
            f"Inline module payload is {total} bytes, over the "
            f"{MAX_INLINE_MODULE_BYTES}-byte live-serverless cap. "
            f"Use `flash deploy` for endpoints with large local dependencies."
        )
    return modules


class LiveServerlessStub(RemoteExecutorStub):
    """Adapter class to make Runpod endpoints look like gRPC stubs."""

    def __init__(self, server: LiveServerless):
        self.server = server

    async def prepare_request(
        self,
        func,
        dependencies,
        system_dependencies,
        accelerate_downloads,
        *args,
        **kwargs,
    ):
        source, src_hash = get_function_source(func)

        # Extract module-level context (imports, constants, helpers)
        from .module_context import extract_module_context

        original_func = inspect.unwrap(func)
        module_context = extract_module_context(original_func, source)

        # Detect and resolve @remote dependencies for stacked execution
        from .dependency_resolver import (
            build_augmented_source,
            generate_stub_code,
            resolve_dependencies,
            resolve_in_function_imports,
            strip_remote_imports,
        )

        augmented_globals = resolve_in_function_imports(
            source, original_func.__globals__
        )
        remote_deps = await resolve_dependencies(source, augmented_globals)

        # Build augmented source with module context and stubs
        all_prepended = []
        if module_context:
            all_prepended.append(module_context)
        if remote_deps:
            remote_names = {dep.name for dep in remote_deps}
            source = strip_remote_imports(source, remote_names)
            all_prepended.extend(generate_stub_code(dep) for dep in remote_deps)
        if all_prepended:
            source = build_augmented_source(source, all_prepended)
            # Recompute cache key to include context and dependency endpoints
            extra_key = hashlib.sha256(source.encode("utf-8")).hexdigest()
            if remote_deps:
                dep_key = "|".join(f"{d.name}:{d.endpoint_id}" for d in remote_deps)
                extra_key = hashlib.sha256(
                    (source + dep_key).encode("utf-8")
                ).hexdigest()
            src_hash = extra_key

        request = {
            "function_name": func.__name__,
            "dependencies": dependencies,
            "system_dependencies": system_dependencies,
            "accelerate_downloads": accelerate_downloads,
        }

        # Thread-safe cache access
        with _function_cache_lock:
            # check if the function is already cached
            if src_hash not in _SERIALIZED_FUNCTION_CACHE:
                # Cache the serialized function
                _SERIALIZED_FUNCTION_CACHE[src_hash] = source

            request["function_code"] = _SERIALIZED_FUNCTION_CACHE[src_hash]

        source_file = original_func.__globals__.get("__file__")
        request["modules"] = build_modules_map(source, source_file)

        # Serialize arguments using cloudpickle
        if args:
            request["args"] = serialize_args(args)
        if kwargs:
            request["kwargs"] = serialize_kwargs(kwargs)

        return FunctionRequest(**request)

    def handle_response(self, response: FunctionResponse):
        if not (response.success or response.error):
            raise ValueError("Invalid response from server")

        if response.stdout:
            from runpod_flash.dev_console import print_worker_log

            name = getattr(self.server, "name", "worker")
            for line in response.stdout.splitlines():
                print_worker_log(name, line)

        if response.success:
            if response.result is not None:
                return cloudpickle.loads(base64.b64decode(response.result))
            if response.json_result is not None:
                return response.json_result
            return None
        else:
            raise Exception(f"Remote execution failed: {response.error}")

    async def ExecuteFunction(
        self, request: FunctionRequest, sync: bool = False
    ) -> FunctionResponse:
        try:
            # Convert the gRPC request to Runpod format
            payload = request.model_dump(exclude_none=True)

            if sync:
                job = await self.server.runsync(payload)
            else:
                job = await self.server.run(payload)

            if job.error:
                return FunctionResponse(
                    success=False,
                    error=job.error,
                    stdout=job.output.get("stdout", "") if job.output else None,
                )

            return FunctionResponse(**job.output)

        except Exception as e:
            error_traceback = traceback.format_exc()
            return FunctionResponse(
                success=False,
                error=f"{str(e)}\n{error_traceback}",
            )
