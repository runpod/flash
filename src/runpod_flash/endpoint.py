"""unified endpoint class for flash.

replaces the 8-class resource config hierarchy with a single class.
queue-based vs load-balanced is inferred from usage pattern.
gpu vs cpu is a parameter, not a class choice.
live vs deploy is determined by the runtime environment.
"""

import inspect
import logging
import os
from functools import wraps
from typing import Any, Dict, List, Optional, Tuple, Union

from .core.resources.cpu import CpuInstanceType
from .core.resources.gpu import GpuGroup, GpuType
from .core.resources.network_volume import DataCenter, NetworkVolume

log = logging.getLogger(__name__)

# valid http methods for load-balanced endpoints
_VALID_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "DELETE", "PATCH"})


def _normalize_workers(
    workers: Union[int, Tuple[int, int], None],
) -> Tuple[int, int]:
    """convert workers param to (min, max) tuple.

    accepts:
      - int: shorthand for (0, n)
      - (min, max): explicit tuple
      - None: defaults to (0, 1)
    """
    if workers is None:
        return (0, 1)
    if isinstance(workers, int):
        return (0, workers)
    if isinstance(workers, (tuple, list)) and len(workers) == 2:
        return (int(workers[0]), int(workers[1]))
    raise ValueError(
        f"workers must be an int or (min, max) tuple, got {type(workers).__name__}: {workers}"
    )


def _is_live_provisioning() -> bool:
    return os.getenv("FLASH_IS_LIVE_PROVISIONING", "").lower() == "true"


def _is_cpu_config(
    cpu: Optional[Union[str, CpuInstanceType, List[Union[str, CpuInstanceType]]]],
) -> bool:
    return cpu is not None


def _normalize_gpu(
    gpu: Optional[Union[GpuGroup, GpuType, List[Union[GpuGroup, GpuType]]]],
) -> Optional[List[Union[GpuGroup, GpuType]]]:
    if gpu is None:
        return None
    if isinstance(gpu, (GpuGroup, GpuType)):
        return [gpu]
    if isinstance(gpu, list):
        return gpu
    raise ValueError(f"gpu must be a GpuGroup, GpuType, or list, got {type(gpu).__name__}")


def _normalize_cpu(
    cpu: Optional[Union[str, CpuInstanceType, List[Union[str, CpuInstanceType]]]],
) -> Optional[List[CpuInstanceType]]:
    if cpu is None:
        return None
    if isinstance(cpu, CpuInstanceType):
        return [cpu]
    if isinstance(cpu, str):
        return [CpuInstanceType(cpu)]
    if isinstance(cpu, list):
        return [CpuInstanceType(c) if isinstance(c, str) else c for c in cpu]
    raise ValueError(f"cpu must be a CpuInstanceType, string, or list, got {type(cpu).__name__}")


class Endpoint:
    """unified configuration and decorator for flash endpoints.

    usage patterns:

    queue-based (one function = one endpoint = own workers):

        @Endpoint(name="my-worker", gpu=GpuGroup.ADA_24, workers=(0, 3))
        async def process(data: dict) -> dict:
            return {"result": data}

    load-balanced (multiple routes, shared workers):

        api = Endpoint(name="my-api", gpu=GpuGroup.ADA_24, workers=(1, 5))

        @api.get("/health")
        async def health():
            return {"status": "ok"}

        @api.post("/compute")
        async def compute(request: dict) -> dict:
            return {"result": request}

    the endpoint type (queue-based vs load-balanced) is inferred from usage:
    - decorating a function directly = queue-based
    - calling .get()/.post()/etc = load-balanced

    gpu vs cpu is a parameter:
    - gpu=GpuGroup.ADA_24 for gpu endpoints (default: GpuGroup.ANY)
    - cpu=CpuInstanceType.CPU3G_2_8 for cpu endpoints
    - mutually exclusive

    live vs deploy is determined by the runtime (flash run vs flash deploy).
    """

    def __init__(
        self,
        name: str,
        *,
        gpu: Optional[Union[GpuGroup, GpuType, List[Union[GpuGroup, GpuType]]]] = None,
        cpu: Optional[Union[str, CpuInstanceType, List[Union[str, CpuInstanceType]]]] = None,
        workers: Union[int, Tuple[int, int], None] = None,
        idle_timeout: int = 60,
        dependencies: Optional[List[str]] = None,
        system_dependencies: Optional[List[str]] = None,
        accelerate_downloads: bool = True,
        volume: Optional[NetworkVolume] = None,
        datacenter: DataCenter = DataCenter.EU_RO_1,
        env: Optional[Dict[str, str]] = None,
        gpu_count: int = 1,
        execution_timeout_ms: int = 0,
        flashboot: bool = True,
        image: Optional[str] = None,
    ):
        if gpu is not None and cpu is not None:
            raise ValueError("gpu and cpu are mutually exclusive. specify one or neither.")

        self.name = name
        self._gpu = _normalize_gpu(gpu)
        self._cpu = _normalize_cpu(cpu)
        self._is_cpu = _is_cpu_config(cpu)
        self._workers_min, self._workers_max = _normalize_workers(workers)
        self.idle_timeout = idle_timeout
        self.dependencies = dependencies
        self.system_dependencies = system_dependencies
        self.accelerate_downloads = accelerate_downloads
        self.volume = volume
        self.datacenter = datacenter
        self.env = env
        self.gpu_count = gpu_count
        self.execution_timeout_ms = execution_timeout_ms
        self.flashboot = flashboot
        self.image = image

        # if no gpu or cpu specified, default to gpu any
        if not self._is_cpu and self._gpu is None:
            self._gpu = [GpuGroup.ANY]

        # lb routes registered via .get()/.post()/etc
        self._routes: List[Dict[str, Any]] = []

        # tracks whether this endpoint was used as a direct decorator (qb mode)
        self._qb_target: Any = None

    @property
    def is_cpu(self) -> bool:
        return self._is_cpu

    @property
    def is_load_balanced(self) -> bool:
        return len(self._routes) > 0

    @property
    def workers_min(self) -> int:
        return self._workers_min

    @property
    def workers_max(self) -> int:
        return self._workers_max

    def _build_resource_config(self):
        """create the appropriate internal resource config object.

        selects the right class based on:
        - qb vs lb (inferred from usage)
        - gpu vs cpu (from params)
        - live vs deploy (from environment)
        """
        is_lb = self.is_load_balanced
        is_cpu = self._is_cpu
        live = _is_live_provisioning()

        # build common kwargs
        kwargs: Dict[str, Any] = {
            "name": self.name,
            "workersMin": self._workers_min,
            "workersMax": self._workers_max,
            "idleTimeout": self.idle_timeout,
            "executionTimeoutMs": self.execution_timeout_ms,
            "flashboot": self.flashboot,
            "datacenter": self.datacenter.value if hasattr(self.datacenter, "value") else self.datacenter,
        }

        if self.volume is not None:
            # serialize to dict to avoid pydantic model identity issues
            # when modules get re-imported across different test/import contexts
            kwargs["networkVolume"] = self.volume.model_dump(exclude_none=True)

        if self.env is not None:
            kwargs["env"] = self.env

        if is_cpu:
            # serialize cpu instance types to strings for pydantic compat
            kwargs["instanceIds"] = [
                c.value if hasattr(c, "value") else c for c in (self._cpu or [])
            ]
        else:
            # serialize gpu values to strings for pydantic compat
            kwargs["gpus"] = [
                g.value if hasattr(g, "value") else g for g in (self._gpu or [])
            ]
            kwargs["gpuCount"] = self.gpu_count

        if self.image is not None:
            kwargs["imageName"] = self.image

        # select the right class
        if is_lb and is_cpu and live:
            from .core.resources.live_serverless import CpuLiveLoadBalancer
            return CpuLiveLoadBalancer(**kwargs)
        elif is_lb and is_cpu and not live:
            from .core.resources.load_balancer_sls_resource import CpuLoadBalancerSlsResource
            return CpuLoadBalancerSlsResource(**kwargs)
        elif is_lb and not is_cpu and live:
            from .core.resources.live_serverless import LiveLoadBalancer
            return LiveLoadBalancer(**kwargs)
        elif is_lb and not is_cpu and not live:
            from .core.resources.load_balancer_sls_resource import LoadBalancerSlsResource
            return LoadBalancerSlsResource(**kwargs)
        elif not is_lb and is_cpu and live:
            from .core.resources.live_serverless import CpuLiveServerless
            return CpuLiveServerless(**kwargs)
        elif not is_lb and is_cpu and not live:
            from .core.resources.serverless_cpu import CpuServerlessEndpoint
            return CpuServerlessEndpoint(**kwargs)
        elif not is_lb and not is_cpu and live:
            from .core.resources.live_serverless import LiveServerless
            return LiveServerless(**kwargs)
        else:
            from .core.resources.serverless import ServerlessEndpoint
            return ServerlessEndpoint(**kwargs)

    # -- direct decorator (qb mode) --

    def __call__(self, func_or_class):
        """use Endpoint as a direct decorator for queue-based endpoints.

        @Endpoint(name="worker", gpu=GpuGroup.ADA_24)
        async def process(data: dict) -> dict: ...
        """
        if self._routes:
            raise ValueError(
                "cannot use Endpoint as a direct decorator after registering "
                "routes with .get()/.post()/etc. use one pattern or the other."
            )

        self._qb_target = func_or_class
        resource_config = self._build_resource_config()

        from .client import remote as remote_decorator

        return remote_decorator(
            resource_config=resource_config,
            dependencies=self.dependencies,
            system_dependencies=self.system_dependencies,
            accelerate_downloads=self.accelerate_downloads,
        )(func_or_class)

    # -- route decorators (lb mode) --

    def _route(self, method: str, path: str):
        """register an http route on this endpoint (lb mode)."""
        method = method.upper()
        if method not in _VALID_HTTP_METHODS:
            raise ValueError(f"method must be one of {_VALID_HTTP_METHODS}, got: {method}")
        if not path.startswith("/"):
            raise ValueError(f"path must start with '/', got: {path}")
        if self._qb_target is not None:
            raise ValueError(
                "cannot add routes after using Endpoint as a direct decorator. "
                "use one pattern or the other."
            )

        def decorator(func):
            self._routes.append({
                "method": method,
                "path": path,
                "function": func,
                "function_name": func.__name__,
            })

            resource_config = self._build_resource_config()

            from .client import remote as remote_decorator

            decorated = remote_decorator(
                resource_config=resource_config,
                dependencies=self.dependencies,
                system_dependencies=self.system_dependencies,
                accelerate_downloads=self.accelerate_downloads,
                method=method,
                path=path,
            )(func)

            return decorated

        return decorator

    def get(self, path: str):
        """register a GET route."""
        return self._route("GET", path)

    def post(self, path: str):
        """register a POST route."""
        return self._route("POST", path)

    def put(self, path: str):
        """register a PUT route."""
        return self._route("PUT", path)

    def delete(self, path: str):
        """register a DELETE route."""
        return self._route("DELETE", path)

    def patch(self, path: str):
        """register a PATCH route."""
        return self._route("PATCH", path)
