import hashlib
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from pydantic import BaseModel, ConfigDict


def _restore_resource(cls, state):
    """Helper to restore a BaseResource from pickled state.

    This function is used by __reduce_ex__ to reconstruct resource objects
    in a way that avoids pickling module-level ContextVar objects.
    """
    # Create instance without calling __init__ to avoid validation
    instance = cls.__new__(cls)
    # Restore state directly
    instance.__setstate__(state)
    return instance


class BaseResource(BaseModel):
    """Base class for all resources."""

    model_config = ConfigDict(
        validate_by_name=True,
        validate_default=True,
        serialize_by_alias=True,
    )

    id: Optional[str] = None

    @property
    def resource_id(self) -> str:
        """Unique resource ID based on configuration.

        Computed once and cached to ensure stability across the object's lifetime.
        This prevents hash changes if validators mutate the object after first access.

        The hash excludes the 'id' field since it's assigned by the provider after
        deployment and should not affect resource identity.

        If the resource defines _hashed_fields as a class variable, only those fields
        are included in the hash.
        """
        # Use a private attribute in __dict__ for caching (handles pickle correctly)
        cache_key = "_cached_resource_id"
        if cache_key not in self.__dict__:
            resource_type = self.__class__.__name__
            # Check if resource defines _hashed_fields as a set/frozenset or ModelPrivateAttr
            hashed_fields_attr = getattr(self.__class__, "_hashed_fields", None)
            include_fields = None

            if isinstance(hashed_fields_attr, (set, frozenset)):
                # Direct set/frozenset
                include_fields = hashed_fields_attr - {"id"}
            elif hasattr(hashed_fields_attr, "default") and isinstance(
                hashed_fields_attr.default, (set, frozenset)
            ):
                # Pydantic ModelPrivateAttr with set/frozenset default
                include_fields = hashed_fields_attr.default - {"id"}

            if include_fields:
                config_str = self.model_dump_json(
                    exclude_none=True, include=include_fields
                )
            else:
                # Fallback: Exclude only id field
                config_str = self.model_dump_json(exclude_none=True, exclude={"id"})

            hash_obj = hashlib.md5(f"{resource_type}:{config_str}".encode())
            self.__dict__[cache_key] = f"{resource_type}_{hash_obj.hexdigest()}"
        return self.__dict__[cache_key]

    @property
    def config_hash(self) -> str:
        """Get hash of current configuration (excluding id and server-assigned fields).

        Unlike resource_id which is cached, this always computes fresh hash.
        Used for drift detection.

        For resources with _input_only set, only those fields are included in the hash
        to avoid drift from server-assigned fields.
        """
        import json
        import logging

        resource_type = self.__class__.__name__

        # If resource defines input_only fields, use only those for hash
        if hasattr(self, "_input_only"):
            # Include only user-provided input fields, not server-assigned ones
            include_fields = self._input_only - {"id"}  # Exclude id from input fields
            config_dict = self.model_dump(
                exclude_none=True, include=include_fields, mode="json"
            )
        else:
            # Fallback: exclude only id field
            config_dict = self.model_dump(
                exclude_none=True, exclude={"id"}, mode="json"
            )

        # Convert to JSON string for hashing
        config_str = json.dumps(config_dict, sort_keys=True)
        hash_obj = hashlib.md5(f"{resource_type}:{config_str}".encode())
        hash_value = hash_obj.hexdigest()

        # Debug logging to see what's being hashed
        log = logging.getLogger(__name__)
        if hasattr(self, "name"):
            log.debug(
                f"CONFIG HASH for {self.name} ({resource_type}):\n"
                f"  Fields included: {sorted(config_dict.keys())}\n"
                f"  Config dict: {config_str}\n"
                f"  Hash: {hash_value}"
            )

        return hash_value

    def get_resource_key(self) -> str:
        """Get stable resource key for tracking.

        Format: {ResourceType}:{name}
        This provides stable identity even when config changes.
        """
        resource_type = self.__class__.__name__
        name = getattr(self, "name", None)
        if name:
            return f"{resource_type}:{name}"
        # Fallback to resource_id for resources without names
        return self.resource_id

    def __reduce__(self):
        """Custom pickling to handle ContextVar issues with cloudpickle.

        When cloudpickle tries to serialize this object, it includes references
        to module-level state, including ContextVar objects that cannot be pickled.
        This method uses a helper function to restore from state without triggering
        module-level imports that include ContextVar.
        """
        # Use helper function to reconstruct from state
        # This avoids cloudpickle trying to serialize module-level ContextVar
        return (_restore_resource, (self.__class__, self.__getstate__()))

    def __getstate__(self) -> Dict[str, Any]:
        """Get state for pickling, excluding non-pickleable items."""
        import weakref as weakref_module

        state = self.__dict__.copy()

        # Remove cached attributes that will be recomputed
        state.pop("_cached_resource_id", None)

        # Remove any weakrefs from the state dict
        keys_to_remove = []
        for key, value in state.items():
            # Direct weakref
            if isinstance(value, weakref_module.ref):
                keys_to_remove.append(key)
                continue

            # Check if value holds weakrefs in its __dict__
            if hasattr(value, "__dict__"):
                try:
                    for sub_value in value.__dict__.values():
                        if isinstance(sub_value, weakref_module.ref):
                            keys_to_remove.append(key)
                            break
                except Exception:
                    pass

        for key in keys_to_remove:
            del state[key]

        return state

    def __setstate__(self, state: Dict[str, Any]) -> None:
        """Restore state from pickling.

        Pydantic models store field values in __dict__, so updating __dict__
        with the state dict (from model_dump) restores the model correctly.
        Cached attributes like _cached_resource_id will be recomputed on first access.
        """
        self.__dict__.update(state)


class DeployableResource(BaseResource, ABC):
    """Base class for deployable resources."""

    def __str__(self) -> str:
        return f"{self.__class__.__name__}"

    @property
    @abstractmethod
    def url(self) -> str:
        """Public URL of the resource."""
        raise NotImplementedError("Subclasses should implement this method.")

    @abstractmethod
    def is_deployed(self) -> bool:
        """Check the resource if it's still valid or available."""
        raise NotImplementedError("Subclasses should implement this method.")

    @abstractmethod
    async def deploy(self) -> "DeployableResource":
        """Deploy the resource."""
        raise NotImplementedError("Subclasses should implement this method.")

    @abstractmethod
    async def undeploy(self) -> bool:
        """Undeploy/delete the resource.

        Returns:
            True if successfully undeployed, False otherwise
        """
        raise NotImplementedError("Subclasses should implement this method.")
