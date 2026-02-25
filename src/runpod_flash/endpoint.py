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

    three usage modes:

    1. your code (decorator mode):

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

    2. external image (deploy a pre-built image, call it as an API client):

        vllm = Endpoint(name="vllm", image="vllm/vllm-openai:latest", gpu=GpuGroup.ADA_24)

        # LB-style calls
        result = await vllm.post("/v1/completions", {"prompt": "hello"})
        models = await vllm.get("/v1/models")

        # QB-style calls
        result = await vllm.run({"prompt": "hello"})
        result = await vllm.runsync({"prompt": "hello"})
        status = await vllm.status(job_id)

    3. existing endpoint (connect to an already-deployed endpoint by id):

        ep = Endpoint(id="abc123")

        # same client methods as image mode, no provisioning
        result = await ep.runsync({"prompt": "hello"})
        result = await ep.post("/v1/completions", {"prompt": "hello"})

    behavior is determined by context:
    - no image, no id: decorator mode (your code)
    - image= set: deploys the image, then client mode
    - id= set: pure client, no provisioning
    - .get()/.post() with data arg = HTTP client call
    - .get()/.post() with no data arg = route decorator
    - .run()/.runsync()/.status() = QB client calls

    gpu vs cpu is a parameter:
    - gpu=GpuGroup.ADA_24 for gpu endpoints (default: GpuGroup.ANY)
    - cpu=CpuInstanceType.CPU3G_2_8 for cpu endpoints
    - mutually exclusive

    live vs deploy is determined by the runtime (flash run vs flash deploy).
    """

    def __init__(
        self,
        name: Optional[str] = None,
        *,
        id: Optional[str] = None,
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
        if id is not None and image is not None:
            raise ValueError("id and image are mutually exclusive. id= connects to an "
                             "existing endpoint, image= deploys a new one.")
        if name is None and id is None:
            raise ValueError("name or id is required.")

        self.name = name
        self.id = id
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

        # if no gpu or cpu specified, default to gpu any (unless pure client mode)
        if not self._is_cpu and self._gpu is None and not self.is_client:
            self._gpu = [GpuGroup.ANY]

        # lb routes registered via .get()/.post()/etc (decorator mode only)
        self._routes: List[Dict[str, Any]] = []

        # tracks whether this endpoint was used as a direct decorator (qb mode)
        self._qb_target: Any = None

        # cached resource config built by _build_resource_config()
        self._cached_resource_config: Any = None

        # cached endpoint url resolved by _ensure_endpoint_ready()
        self._endpoint_url: Optional[str] = None

    @property
    def is_cpu(self) -> bool:
        return self._is_cpu

    @property
    def is_client(self) -> bool:
        """true when this endpoint is a client for an external/existing resource.

        client mode is active when image= or id= is provided. in client mode,
        .get()/.post()/etc make HTTP calls instead of returning decorators,
        and .run()/.runsync()/.status() submit/poll QB jobs.
        """
        return self.image is not None or self.id is not None

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

        returns a cached instance on repeated calls so that the resource
        manager sees the same object and avoids redundant provisioning.
        """
        if self._cached_resource_config is not None:
            return self._cached_resource_config

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
            config = CpuLiveLoadBalancer(**kwargs)
        elif is_lb and is_cpu and not live:
            from .core.resources.load_balancer_sls_resource import CpuLoadBalancerSlsResource
            config = CpuLoadBalancerSlsResource(**kwargs)
        elif is_lb and not is_cpu and live:
            from .core.resources.live_serverless import LiveLoadBalancer
            config = LiveLoadBalancer(**kwargs)
        elif is_lb and not is_cpu and not live:
            from .core.resources.load_balancer_sls_resource import LoadBalancerSlsResource
            config = LoadBalancerSlsResource(**kwargs)
        elif not is_lb and is_cpu and live:
            from .core.resources.live_serverless import CpuLiveServerless
            config = CpuLiveServerless(**kwargs)
        elif not is_lb and is_cpu and not live:
            from .core.resources.serverless_cpu import CpuServerlessEndpoint
            config = CpuServerlessEndpoint(**kwargs)
        elif not is_lb and not is_cpu and live:
            from .core.resources.live_serverless import LiveServerless
            config = LiveServerless(**kwargs)
        else:
            from .core.resources.serverless import ServerlessEndpoint
            config = ServerlessEndpoint(**kwargs)

        self._cached_resource_config = config
        return config

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

    def get(self, path: str, data: Any = None, **kwargs):
        """GET route decorator (decorator mode) or HTTP GET call (client mode)."""
        if self.is_client:
            return self._client_request("GET", path, data, **kwargs)
        return self._route("GET", path)

    def post(self, path: str, data: Any = None, **kwargs):
        """POST route decorator (decorator mode) or HTTP POST call (client mode)."""
        if self.is_client:
            return self._client_request("POST", path, data, **kwargs)
        return self._route("POST", path)

    def put(self, path: str, data: Any = None, **kwargs):
        """PUT route decorator (decorator mode) or HTTP PUT call (client mode)."""
        if self.is_client:
            return self._client_request("PUT", path, data, **kwargs)
        return self._route("PUT", path)

    def delete(self, path: str, data: Any = None, **kwargs):
        """DELETE route decorator (decorator mode) or HTTP DELETE call (client mode)."""
        if self.is_client:
            return self._client_request("DELETE", path, data, **kwargs)
        return self._route("DELETE", path)

    def patch(self, path: str, data: Any = None, **kwargs):
        """PATCH route decorator (decorator mode) or HTTP PATCH call (client mode)."""
        if self.is_client:
            return self._client_request("PATCH", path, data, **kwargs)
        return self._route("PATCH", path)

    # -- client methods (image= or id= mode) --

    async def _ensure_endpoint_ready(self) -> str:
        """ensure the endpoint is provisioned and return its base url.

        for id= mode: resolves the endpoint url from the id directly.
        for image= mode: provisions via ResourceManager, then returns url.

        caches the resolved url for subsequent calls.
        """
        if self._endpoint_url is not None:
            return self._endpoint_url

        if self.id is not None:
            # pure client mode: build url from endpoint id
            import runpod
            base = runpod.endpoint_url_base
            self._endpoint_url = f"{base}/{self.id}"
            return self._endpoint_url

        # image= mode: provision and deploy, then extract url
        resource_config = self._build_resource_config()
        from .core.resources import ResourceManager
        resource_manager = ResourceManager()
        deployed = await resource_manager.get_or_deploy_resource(resource_config)
        if hasattr(deployed, "endpoint_url") and deployed.endpoint_url:
            self._endpoint_url = deployed.endpoint_url
        elif hasattr(deployed, "id") and deployed.id:
            import runpod
            base = runpod.endpoint_url_base
            self._endpoint_url = f"{base}/{deployed.id}"
        else:
            raise RuntimeError(
                f"endpoint '{self.name}' was deployed but has no endpoint url or id"
            )
        return self._endpoint_url

    async def run(self, input_data: Any) -> dict:
        """submit a QB job asynchronously. returns job metadata including id.

        the returned dict contains at minimum {"id": "<job_id>", "status": "IN_QUEUE"}.
        use .status(job_id) to poll for completion.
        """
        url = await self._ensure_endpoint_ready()
        return await self._api_post(f"{url}/run", {"input": input_data})

    async def runsync(self, input_data: Any, timeout: float = 60.0) -> dict:
        """submit a QB job and wait for the result.

        returns the full job output dict including {"output": ..., "status": "COMPLETED"}.
        """
        url = await self._ensure_endpoint_ready()
        return await self._api_post(
            f"{url}/runsync", {"input": input_data}, timeout=timeout
        )

    async def status(self, job_id: str) -> dict:
        """check the status of a previously submitted QB job."""
        url = await self._ensure_endpoint_ready()
        return await self._api_get(f"{url}/status/{job_id}")

    async def _client_request(self, method: str, path: str, data: Any = None, **kwargs) -> Any:
        """make an HTTP request to a deployed LB endpoint.

        for LB endpoints this sends a request to the endpoint's base url + path.
        """
        url = await self._ensure_endpoint_ready()
        full_url = f"{url}{path}"
        timeout = kwargs.pop("timeout", 60.0)

        from .core.utils.http import get_authenticated_httpx_client
        async with get_authenticated_httpx_client(timeout=timeout) as client:
            response = await client.request(method, full_url, json=data)
            response.raise_for_status()
            return response.json()

    async def _api_post(self, url: str, payload: Any, timeout: float = 60.0) -> dict:
        """authenticated POST to the runpod api."""
        from .core.utils.http import get_authenticated_httpx_client
        async with get_authenticated_httpx_client(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()

    async def _api_get(self, url: str, timeout: float = 30.0) -> dict:
        """authenticated GET to the runpod api."""
        from .core.utils.http import get_authenticated_httpx_client
        async with get_authenticated_httpx_client(timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
