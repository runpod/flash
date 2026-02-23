"""
Class execution module for remote class instantiation and method calls.

This module provides functionality to create and execute remote class instances,
with automatic caching of class serialization data to improve performance and
prevent memory leaks through LRU eviction.
"""

import hashlib
import inspect
import logging
import textwrap
import uuid
from typing import List, Optional, Type

import cloudpickle

from .core.resources import ResourceManager, ServerlessResource
from .core.utils.constants import HASH_TRUNCATE_LENGTH, UUID_FALLBACK_LENGTH
from .core.utils.lru_cache import LRUCache
from .protos.remote_execution import FunctionRequest
from .runtime.exceptions import SerializationError
from .runtime.serialization import serialize_args, serialize_kwargs
from .stubs import stub_resource

log = logging.getLogger(__name__)

# Global in-memory cache for serialized class data with LRU eviction
_SERIALIZED_CLASS_CACHE = LRUCache(max_size=1000)


def serialize_constructor_args(args, kwargs):
    """Serialize constructor arguments for caching."""
    return serialize_args(args), serialize_kwargs(kwargs)


def get_or_cache_class_data(
    cls: Type, args: tuple, kwargs: dict, cache_key: str
) -> str:
    """Get class code from cache or extract and cache it."""
    if cache_key not in _SERIALIZED_CLASS_CACHE:
        # Cache miss - extract and cache class code
        clean_class_code = extract_class_code_simple(cls)

        try:
            serialized_args, serialized_kwargs = serialize_constructor_args(
                args, kwargs
            )

            # Cache the serialized data
            _SERIALIZED_CLASS_CACHE.set(
                cache_key,
                {
                    "class_code": clean_class_code,
                    "constructor_args": serialized_args,
                    "constructor_kwargs": serialized_kwargs,
                },
            )

        except (TypeError, AttributeError, OSError, SerializationError) as e:
            log.warning(
                f"Could not serialize constructor arguments for {cls.__name__}: {e}"
            )
            log.warning(
                f"Skipping constructor argument caching for {cls.__name__} due to unserializable arguments"
            )

            # Store minimal cache entry to avoid repeated attempts
            _SERIALIZED_CLASS_CACHE.set(
                cache_key,
                {
                    "class_code": clean_class_code,
                    "constructor_args": None,  # Signal that args couldn't be cached
                    "constructor_kwargs": None,
                },
            )

        return clean_class_code
    else:
        # Cache hit - retrieve cached data
        cached_data = _SERIALIZED_CLASS_CACHE.get(cache_key)
        return cached_data["class_code"]


def extract_class_code_simple(cls: Type) -> str:
    """Extract clean class code without decorators and proper indentation"""
    try:
        # Get source code
        source = inspect.getsource(cls)

        # Split into lines
        lines = source.split("\n")

        # Find the class definition line (starts with 'class' and contains ':')
        class_start_idx = -1
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("class ") and ":" in stripped:
                class_start_idx = i
                break

        if class_start_idx == -1:
            raise ValueError("Could not find class definition")

        # Take lines from class definition onwards (ignore everything before)
        class_lines = lines[class_start_idx:]

        # Remove empty lines at the end
        while class_lines and not class_lines[-1].strip():
            class_lines.pop()

        # Join back and dedent to remove any leading indentation
        class_code = "\n".join(class_lines)
        class_code = textwrap.dedent(class_code)

        # Validate the code by trying to compile it
        compile(class_code, "<string>", "exec")

        return class_code

    except Exception as e:
        log.warning(f"Could not extract class code for {cls.__name__}: {e}")
        log.warning("Falling back to basic class structure")

        # Enhanced fallback: try to preserve method signatures
        fallback_methods = []
        for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
            try:
                sig = inspect.signature(method)
                fallback_methods.append(f"    def {name}{sig}:")
                fallback_methods.append("        pass")
                fallback_methods.append("")
            except (TypeError, ValueError, OSError) as e:
                log.warning(f"Could not extract method signature for {name}: {e}")
                fallback_methods.append(f"    def {name}(self, *args, **kwargs):")
                fallback_methods.append("        pass")
                fallback_methods.append("")

        fallback_code = f"""class {cls.__name__}:
    def __init__(self, *args, **kwargs):
        pass

{chr(10).join(fallback_methods)}"""

        return fallback_code


def get_class_cache_key(
    cls: Type, constructor_args: tuple, constructor_kwargs: dict
) -> str:
    """Generate a cache key for class serialization based on class source and constructor args.

    Args:
        cls: The class type to generate a key for
        constructor_args: Positional arguments passed to class constructor
        constructor_kwargs: Keyword arguments passed to class constructor

    Returns:
        A unique cache key string, or a UUID-based fallback if serialization fails

    Note:
        Falls back to UUID-based key if constructor arguments cannot be serialized,
        which disables caching benefits but maintains functionality.
    """
    try:
        # Get class source code for hashing
        class_source = extract_class_code_simple(cls)

        # Create hash of class source
        class_hash = hashlib.sha256(class_source.encode()).hexdigest()

        # Create hash of constructor arguments
        args_data = cloudpickle.dumps((constructor_args, constructor_kwargs))
        args_hash = hashlib.sha256(args_data).hexdigest()

        # Combine hashes for final cache key
        cache_key = f"{cls.__name__}_{class_hash[:HASH_TRUNCATE_LENGTH]}_{args_hash[:HASH_TRUNCATE_LENGTH]}"

        return cache_key

    except (TypeError, AttributeError, OSError) as e:
        log.warning(f"Could not generate cache key for {cls.__name__}: {e}")
        # Fallback to basic key without caching benefits
        return f"{cls.__name__}_{uuid.uuid4().hex[:UUID_FALLBACK_LENGTH]}"


def create_remote_class(
    cls: Type,
    resource_config: ServerlessResource,
    dependencies: Optional[List[str]],
    system_dependencies: Optional[List[str]],
    accelerate_downloads: bool,
    extra: dict,
):
    """
    Create a remote class wrapper.
    """
    # Validate inputs
    if not inspect.isclass(cls):
        raise TypeError(f"Expected a class, got {type(cls).__name__}")
    if not hasattr(cls, "__name__"):
        raise ValueError("Class must have a __name__ attribute")

    class RemoteClassWrapper:
        def __init__(self, *args, **kwargs):
            self._class_type = cls
            self._resource_config = resource_config
            self._dependencies = dependencies or []
            self._system_dependencies = system_dependencies or []
            self._accelerate_downloads = accelerate_downloads
            self._extra = extra
            self._constructor_args = args
            self._constructor_kwargs = kwargs
            self._instance_id = (
                f"{cls.__name__}_{uuid.uuid4().hex[:UUID_FALLBACK_LENGTH]}"
            )
            self._initialized = False

            # Generate cache key and get class code
            self._cache_key = get_class_cache_key(cls, args, kwargs)
            self._clean_class_code = get_or_cache_class_data(
                cls, args, kwargs, self._cache_key
            )

        async def _ensure_initialized(self):
            """Ensure the remote instance is created."""
            if self._initialized:
                return

            # Get remote resource
            resource_manager = ResourceManager()
            remote_resource = await resource_manager.get_or_deploy_resource(
                self._resource_config
            )
            self._stub = stub_resource(remote_resource, **self._extra)

            # Create the remote instance by calling a method (which will trigger instance creation)
            # We'll do this on first method call
            self._initialized = True

        def __getattr__(self, name):
            """Dynamically create method proxies for all class methods."""
            if name.startswith("_"):
                raise AttributeError(
                    f"'{self.__class__.__name__}' object has no attribute '{name}'"
                )

            async def method_proxy(*args, **kwargs):
                await self._ensure_initialized()

                # Get cached data
                cached_data = _SERIALIZED_CLASS_CACHE.get(self._cache_key)

                # Serialize method arguments (these change per call, so no caching)
                method_args = serialize_args(args)
                method_kwargs = serialize_kwargs(kwargs)

                # Handle constructor args - use cached if available, else serialize fresh
                if cached_data["constructor_args"] is not None:
                    # Use cached constructor args
                    constructor_args = cached_data["constructor_args"]
                    constructor_kwargs = cached_data["constructor_kwargs"]
                else:
                    # Constructor args couldn't be cached due to serialization issues
                    # Serialize them fresh for each method call (fallback behavior)
                    constructor_args = serialize_args(self._constructor_args)
                    constructor_kwargs = serialize_kwargs(self._constructor_kwargs)

                request = FunctionRequest(
                    execution_type="class",
                    class_name=self._class_type.__name__,
                    class_code=cached_data["class_code"],
                    method_name=name,
                    args=method_args,
                    kwargs=method_kwargs,
                    constructor_args=constructor_args,
                    constructor_kwargs=constructor_kwargs,
                    dependencies=self._dependencies,
                    system_dependencies=self._system_dependencies,
                    accelerate_downloads=self._accelerate_downloads,
                    instance_id=self._instance_id,
                    create_new_instance=not hasattr(
                        self, "_stub"
                    ),  # Create new only on first call
                )

                # Execute via stub
                return await self._stub.execute_class_method(request)  # type: ignore

            return method_proxy

    return RemoteClassWrapper
