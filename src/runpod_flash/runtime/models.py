"""Type-safe models for manifest handling."""

from dataclasses import asdict, dataclass, field
from dataclasses import fields as dataclass_fields
from typing import Any, Dict, List, Optional


@dataclass
class FunctionMetadata:
    """Function metadata in manifest."""

    name: str
    module: str
    is_async: bool
    is_class: bool = False
    http_method: Optional[str] = None
    http_path: Optional[str] = None


@dataclass
class ResourceConfig:
    """Resource configuration in manifest."""

    resource_type: str
    functions: List[FunctionMetadata] = field(default_factory=list)
    makes_remote_calls: bool = True  # Default true for safety
    is_load_balanced: bool = (
        False  # LB endpoint (LoadBalancerSlsResource or LiveLoadBalancer)
    )
    is_live_resource: bool = False  # LiveLoadBalancer/LiveServerless (local dev only)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResourceConfig":
        """Load ResourceConfig from dict."""
        fm_fields = {f.name for f in dataclass_fields(FunctionMetadata)}
        functions = [
            FunctionMetadata(**{k: v for k, v in fd.items() if k in fm_fields})
            for fd in data.get("functions", [])
        ]
        return cls(
            resource_type=data["resource_type"],
            functions=functions,
            makes_remote_calls=data.get("makes_remote_calls", True),
            is_load_balanced=data.get("is_load_balanced", False),
            is_live_resource=data.get("is_live_resource", False),
        )


@dataclass
class Manifest:
    """Type-safe manifest structure."""

    version: str
    generated_at: str
    project_name: str
    function_registry: Dict[str, str]
    resources: Dict[str, ResourceConfig]
    routes: Optional[Dict[str, Dict[str, str]]] = None
    resources_endpoints: Optional[Dict[str, str]] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Manifest":
        """Load Manifest from JSON dict."""
        resources = {}
        for resource_name, resource_data in data.get("resources", {}).items():
            resources[resource_name] = ResourceConfig.from_dict(resource_data)

        return cls(
            version=data.get("version", "1.0"),
            generated_at=data.get("generated_at", ""),
            project_name=data.get("project_name", ""),
            function_registry=data.get("function_registry", {}),
            resources=resources,
            routes=data.get("routes"),
            resources_endpoints=data.get("resources_endpoints"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result = asdict(self)
        # Remove None optional fields to keep JSON clean
        if result.get("routes") is None:
            result.pop("routes", None)
        if result.get("resources_endpoints") is None:
            result.pop("resources_endpoints", None)
        return result
