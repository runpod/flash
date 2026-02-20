import ast
import base64
import inspect
import textwrap
import hashlib
import traceback
import threading
import cloudpickle
import logging
from ..core.resources import LiveServerless
from ..protos.remote_execution import (
    FunctionRequest,
    FunctionResponse,
    RemoteExecutorStub,
)
from ..runtime.serialization import serialize_args, serialize_kwargs

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

        # Detect and resolve @remote dependencies for stacked execution
        from .dependency_resolver import (
            build_augmented_source,
            generate_stub_code,
            resolve_dependencies,
        )

        original_func = inspect.unwrap(func)
        remote_deps = await resolve_dependencies(source, original_func.__globals__)
        if remote_deps:
            stub_codes = [generate_stub_code(dep) for dep in remote_deps]
            source = build_augmented_source(source, stub_codes)
            # Recompute cache key to include dependency endpoints
            dep_key = "|".join(f"{d.name}:{d.endpoint_id}" for d in remote_deps)
            src_hash = hashlib.sha256((source + dep_key).encode("utf-8")).hexdigest()

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
            for line in response.stdout.splitlines():
                print(line)

        if response.success:
            if response.result is None:
                raise ValueError("Response result is None")
            return cloudpickle.loads(base64.b64decode(response.result))
        else:
            raise Exception(f"Remote execution failed: {response.error}")

    async def ExecuteFunction(
        self, request: FunctionRequest, sync: bool = False
    ) -> FunctionResponse:
        try:
            # Convert the gRPC request to Runpod format
            payload = request.model_dump(exclude_none=True)

            if sync:
                job = await self.server.run_sync(payload)
            else:
                job = await self.server.run(payload)

            if job.error:
                return FunctionResponse(
                    success=False,
                    error=job.error,
                    stdout=job.output.get("stdout", ""),
                )

            return FunctionResponse(**job.output)

        except Exception as e:
            error_traceback = traceback.format_exc()
            return FunctionResponse(
                success=False,
                error=f"{str(e)}\n{error_traceback}",
            )
