# Load .env vars from file before everything else
from dotenv import load_dotenv

load_dotenv()

from .logger import setup_logging  # noqa: E402

setup_logging()

# TYPE_CHECKING imports provide full IDE support (autocomplete, type hints)
# while __getattr__ enables lazy loading at runtime for fast CLI startup
from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:
    from .client import remote
    from .endpoint import Endpoint, EndpointJob
    from .core.resources import (
        CpuInstanceType,
        CpuLiveLoadBalancer,
        CpuLiveServerless,
        CpuLoadBalancerSlsResource,
        CpuServerlessEndpoint,
        CudaVersion,
        DataCenter,
        GpuGroup,
        GpuType,
        LiveLoadBalancer,
        LiveServerless,
        LoadBalancerSlsResource,
        NetworkVolume,
        PodTemplate,
        ResourceManager,
        ServerlessEndpoint,
        ServerlessScalerType,
        ServerlessType,
        FlashApp,
    )


def __getattr__(name):
    """Lazily import core modules only when accessed."""
    if name == "Endpoint":
        from .endpoint import Endpoint

        return Endpoint
    elif name == "EndpointJob":
        from .endpoint import EndpointJob

        return EndpointJob
    elif name == "remote":
        from .client import remote

        return remote
    elif name in (
        "CpuInstanceType",
        "CpuLiveLoadBalancer",
        "CpuLiveServerless",
        "CpuLoadBalancerSlsResource",
        "CpuServerlessEndpoint",
        "CudaVersion",
        "DataCenter",
        "GpuGroup",
        "GpuType",
        "LiveLoadBalancer",
        "LiveServerless",
        "LoadBalancerSlsResource",
        "NetworkVolume",
        "PodTemplate",
        "ResourceManager",
        "ServerlessEndpoint",
        "ServerlessScalerType",
        "ServerlessType",
        "FlashApp",
    ):
        from .core.resources import (
            CpuInstanceType,
            CpuLiveLoadBalancer,
            CpuLiveServerless,
            CpuLoadBalancerSlsResource,
            CpuServerlessEndpoint,
            CudaVersion,
            DataCenter,
            GpuGroup,
            GpuType,
            LiveLoadBalancer,
            LiveServerless,
            LoadBalancerSlsResource,
            NetworkVolume,
            PodTemplate,
            ResourceManager,
            ServerlessEndpoint,
            ServerlessScalerType,
            ServerlessType,
            FlashApp,
        )

        attrs = {
            "CpuInstanceType": CpuInstanceType,
            "CpuLiveLoadBalancer": CpuLiveLoadBalancer,
            "CpuLiveServerless": CpuLiveServerless,
            "CpuLoadBalancerSlsResource": CpuLoadBalancerSlsResource,
            "CpuServerlessEndpoint": CpuServerlessEndpoint,
            "CudaVersion": CudaVersion,
            "DataCenter": DataCenter,
            "GpuGroup": GpuGroup,
            "GpuType": GpuType,
            "LiveLoadBalancer": LiveLoadBalancer,
            "LiveServerless": LiveServerless,
            "LoadBalancerSlsResource": LoadBalancerSlsResource,
            "NetworkVolume": NetworkVolume,
            "PodTemplate": PodTemplate,
            "ResourceManager": ResourceManager,
            "ServerlessEndpoint": ServerlessEndpoint,
            "ServerlessScalerType": ServerlessScalerType,
            "ServerlessType": ServerlessType,
            "FlashApp": FlashApp,
        }
        return attrs[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Endpoint",
    "EndpointJob",
    "remote",
    "CpuInstanceType",
    "CpuLiveLoadBalancer",
    "CpuLiveServerless",
    "CpuLoadBalancerSlsResource",
    "CpuServerlessEndpoint",
    "CudaVersion",
    "DataCenter",
    "GpuGroup",
    "GpuType",
    "LiveLoadBalancer",
    "LiveServerless",
    "LoadBalancerSlsResource",
    "NetworkVolume",
    "PodTemplate",
    "ResourceManager",
    "ServerlessEndpoint",
    "ServerlessScalerType",
    "ServerlessType",
    "FlashApp",
]
