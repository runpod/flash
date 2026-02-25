"""tests for the unified Endpoint class."""

import os
from unittest.mock import patch, MagicMock

import pytest

from runpod_flash.endpoint import Endpoint, _normalize_workers
from runpod_flash.core.resources.cpu import CpuInstanceType
from runpod_flash.core.resources.gpu import GpuGroup, GpuType
from runpod_flash.core.resources.network_volume import DataCenter, NetworkVolume


# -- _normalize_workers --


class TestNormalizeWorkers:
    def test_none_defaults(self):
        assert _normalize_workers(None) == (0, 1)

    def test_int_shorthand(self):
        assert _normalize_workers(3) == (0, 3)

    def test_tuple(self):
        assert _normalize_workers((1, 5)) == (1, 5)

    def test_list(self):
        assert _normalize_workers([2, 10]) == (2, 10)

    def test_invalid_type(self):
        with pytest.raises(ValueError, match="workers must be"):
            _normalize_workers("bad")

    def test_invalid_tuple_length(self):
        with pytest.raises(ValueError, match="workers must be"):
            _normalize_workers((1, 2, 3))


# -- Endpoint construction --


class TestEndpointInit:
    def test_defaults_to_gpu_any(self):
        ep = Endpoint(name="test")
        assert ep._gpu == [GpuGroup.ANY]
        assert ep._is_cpu is False

    def test_explicit_gpu(self):
        ep = Endpoint(name="test", gpu=GpuGroup.ADA_24)
        assert ep._gpu == [GpuGroup.ADA_24]
        assert ep._is_cpu is False

    def test_explicit_gpu_list(self):
        ep = Endpoint(name="test", gpu=[GpuGroup.ADA_24, GpuGroup.AMPERE_24])
        assert ep._gpu == [GpuGroup.ADA_24, GpuGroup.AMPERE_24]

    def test_gpu_type(self):
        ep = Endpoint(name="test", gpu=GpuType.NVIDIA_GEFORCE_RTX_4090)
        assert ep._gpu == [GpuType.NVIDIA_GEFORCE_RTX_4090]

    def test_explicit_cpu_enum(self):
        ep = Endpoint(name="test", cpu=CpuInstanceType.CPU3G_2_8)
        assert ep._cpu == [CpuInstanceType.CPU3G_2_8]
        assert ep._is_cpu is True
        assert ep._gpu is None

    def test_explicit_cpu_string(self):
        ep = Endpoint(name="test", cpu="cpu3g-2-8")
        assert ep._cpu == [CpuInstanceType.CPU3G_2_8]
        assert ep._is_cpu is True

    def test_explicit_cpu_list(self):
        ep = Endpoint(name="test", cpu=[CpuInstanceType.CPU3G_2_8, "cpu3c-1-2"])
        assert ep._cpu == [CpuInstanceType.CPU3G_2_8, CpuInstanceType.CPU3C_1_2]

    def test_gpu_cpu_mutually_exclusive(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            Endpoint(name="test", gpu=GpuGroup.ADA_24, cpu=CpuInstanceType.CPU3G_2_8)

    def test_workers_int(self):
        ep = Endpoint(name="test", workers=5)
        assert ep.workers_min == 0
        assert ep.workers_max == 5

    def test_workers_tuple(self):
        ep = Endpoint(name="test", workers=(2, 8))
        assert ep.workers_min == 2
        assert ep.workers_max == 8

    def test_workers_default(self):
        ep = Endpoint(name="test")
        assert ep.workers_min == 0
        assert ep.workers_max == 1

    def test_all_params(self):
        vol = NetworkVolume(name="test-vol", size=50)
        ep = Endpoint(
            name="test",
            gpu=GpuGroup.ADA_24,
            workers=(1, 3),
            idle_timeout=10,
            dependencies=["torch"],
            system_dependencies=["ffmpeg"],
            accelerate_downloads=False,
            volume=vol,
            datacenter=DataCenter.EU_RO_1,
            env={"MY_VAR": "value"},
            gpu_count=2,
            execution_timeout_ms=5000,
            flashboot=False,
        )
        assert ep.name == "test"
        assert ep._gpu == [GpuGroup.ADA_24]
        assert ep.workers_min == 1
        assert ep.workers_max == 3
        assert ep.idle_timeout == 10
        assert ep.dependencies == ["torch"]
        assert ep.system_dependencies == ["ffmpeg"]
        assert ep.accelerate_downloads is False
        assert ep.volume is vol
        assert ep.env == {"MY_VAR": "value"}
        assert ep.gpu_count == 2
        assert ep.execution_timeout_ms == 5000
        assert ep.flashboot is False


# -- is_load_balanced --


class TestIsLoadBalanced:
    def test_no_routes(self):
        ep = Endpoint(name="test")
        assert ep.is_load_balanced is False

    def test_with_routes(self):
        ep = Endpoint(name="test")
        # manually add a route to simulate .get()/.post() usage
        ep._routes.append({"method": "GET", "path": "/health", "function": lambda: None, "function_name": "health"})
        assert ep.is_load_balanced is True


# -- _build_resource_config --


class TestBuildResourceConfig:
    """test that the right internal resource config type is selected."""

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_qb_gpu_live(self):
        ep = Endpoint(name="test", gpu=GpuGroup.ADA_24, workers=(0, 3))
        config = ep._build_resource_config()
        from runpod_flash.core.resources.live_serverless import LiveServerless
        assert isinstance(config, LiveServerless)
        assert config.workersMin == 0
        assert config.workersMax == 3

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "false"})
    def test_qb_gpu_deploy(self):
        ep = Endpoint(name="test", gpu=GpuGroup.ADA_24, workers=3, image="my-image:latest")
        config = ep._build_resource_config()
        from runpod_flash.core.resources.serverless import ServerlessEndpoint
        assert isinstance(config, ServerlessEndpoint)

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_qb_cpu_live(self):
        ep = Endpoint(name="test", cpu=CpuInstanceType.CPU3G_2_8, workers=2)
        config = ep._build_resource_config()
        from runpod_flash.core.resources.live_serverless import CpuLiveServerless
        assert isinstance(config, CpuLiveServerless)

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "false"})
    def test_qb_cpu_deploy(self):
        ep = Endpoint(name="test", cpu=CpuInstanceType.CPU3G_2_8, workers=2, image="my-cpu-image:latest")
        config = ep._build_resource_config()
        from runpod_flash.core.resources.serverless_cpu import CpuServerlessEndpoint
        assert isinstance(config, CpuServerlessEndpoint)

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_lb_gpu_live(self):
        ep = Endpoint(name="test", gpu=GpuGroup.ADA_24)
        ep._routes.append({"method": "GET", "path": "/health", "function": lambda: None, "function_name": "health"})
        config = ep._build_resource_config()
        from runpod_flash.core.resources.live_serverless import LiveLoadBalancer
        assert isinstance(config, LiveLoadBalancer)

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "false"})
    def test_lb_gpu_deploy(self):
        ep = Endpoint(name="test", gpu=GpuGroup.ADA_24, image="my-lb:latest")
        ep._routes.append({"method": "GET", "path": "/health", "function": lambda: None, "function_name": "health"})
        config = ep._build_resource_config()
        from runpod_flash.core.resources.load_balancer_sls_resource import LoadBalancerSlsResource
        assert isinstance(config, LoadBalancerSlsResource)

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_lb_cpu_live(self):
        ep = Endpoint(name="test", cpu="cpu3g-2-8")
        ep._routes.append({"method": "POST", "path": "/run", "function": lambda: None, "function_name": "run"})
        config = ep._build_resource_config()
        from runpod_flash.core.resources.live_serverless import CpuLiveLoadBalancer
        assert isinstance(config, CpuLiveLoadBalancer)

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "false"})
    def test_lb_cpu_deploy(self):
        ep = Endpoint(name="test", cpu="cpu3g-2-8", image="my-cpu-lb:latest")
        ep._routes.append({"method": "POST", "path": "/run", "function": lambda: None, "function_name": "run"})
        config = ep._build_resource_config()
        from runpod_flash.core.resources.load_balancer_sls_resource import CpuLoadBalancerSlsResource
        assert isinstance(config, CpuLoadBalancerSlsResource)

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_default_gpu_any_live(self):
        ep = Endpoint(name="test")
        config = ep._build_resource_config()
        from runpod_flash.core.resources.live_serverless import LiveServerless
        assert isinstance(config, LiveServerless)

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_config_passes_idle_timeout(self):
        ep = Endpoint(name="test", idle_timeout=10, workers=(1, 5))
        config = ep._build_resource_config()
        assert config.idleTimeout == 10
        assert config.workersMin == 1
        assert config.workersMax == 5

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_config_passes_volume(self):
        vol = NetworkVolume(name="test-vol", size=50)
        ep = Endpoint(name="test", volume=vol)
        config = ep._build_resource_config()
        assert config.networkVolume is not None
        assert config.networkVolume.name == "test-vol"
        assert config.networkVolume.size == 50

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_config_passes_env(self):
        ep = Endpoint(name="test", env={"KEY": "VALUE"})
        config = ep._build_resource_config()
        assert config.env["KEY"] == "VALUE"

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_config_passes_gpu_count(self):
        ep = Endpoint(name="test", gpu=GpuGroup.ADA_80_PRO, gpu_count=4)
        config = ep._build_resource_config()
        assert config.gpuCount == 4


# -- decorator behavior (qb mode) --


class TestQBDecorator:
    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_decorates_async_function(self):
        ep = Endpoint(name="test-qb")

        @ep
        async def my_func(data: dict) -> dict:
            return data

        # the decorated function should have __remote_config__ attached
        assert hasattr(my_func, "__remote_config__")
        config = my_func.__remote_config__
        assert config["resource_config"] is not None

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_decorates_sync_function(self):
        ep = Endpoint(name="test-qb-sync")

        @ep
        def my_func(data: dict) -> dict:
            return data

        assert hasattr(my_func, "__remote_config__")

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_decorates_class(self):
        ep = Endpoint(name="test-qb-class")

        @ep
        class MyWorker:
            def __init__(self):
                pass

            async def run(self, data: dict) -> dict:
                return data

        assert hasattr(MyWorker, "__remote_config__")

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_passes_dependencies(self):
        ep = Endpoint(name="test-deps", dependencies=["torch", "numpy"])

        @ep
        async def my_func(data: dict) -> dict:
            return data

        config = my_func.__remote_config__
        assert config["dependencies"] == ["torch", "numpy"]

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_cannot_add_routes_after_qb_decorator(self):
        ep = Endpoint(name="test-conflict")

        @ep
        async def my_func(data: dict) -> dict:
            return data

        with pytest.raises(ValueError, match="cannot add routes"):
            @ep.get("/health")
            async def health():
                return {"status": "ok"}


# -- route decorators (lb mode) --


class TestLBDecorator:
    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_get_route(self):
        ep = Endpoint(name="test-lb")

        @ep.get("/health")
        async def health():
            return {"status": "ok"}

        assert len(ep._routes) == 1
        assert ep._routes[0]["method"] == "GET"
        assert ep._routes[0]["path"] == "/health"
        assert ep._routes[0]["function_name"] == "health"
        assert ep.is_load_balanced is True

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_post_route(self):
        ep = Endpoint(name="test-lb")

        @ep.post("/compute")
        async def compute(data: dict) -> dict:
            return data

        assert len(ep._routes) == 1
        assert ep._routes[0]["method"] == "POST"
        assert ep._routes[0]["path"] == "/compute"

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_multiple_routes(self):
        ep = Endpoint(name="test-lb-multi")

        @ep.get("/health")
        async def health():
            return {"status": "ok"}

        @ep.post("/compute")
        async def compute(data: dict) -> dict:
            return data

        @ep.put("/update")
        async def update(data: dict) -> dict:
            return data

        @ep.delete("/remove")
        async def remove():
            return {"deleted": True}

        @ep.patch("/modify")
        async def modify(data: dict) -> dict:
            return data

        assert len(ep._routes) == 5
        methods = [r["method"] for r in ep._routes]
        assert methods == ["GET", "POST", "PUT", "DELETE", "PATCH"]

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_route_has_remote_config(self):
        ep = Endpoint(name="test-lb")

        @ep.post("/process")
        async def process(data: dict) -> dict:
            return data

        assert hasattr(process, "__remote_config__")
        config = process.__remote_config__
        assert config["method"] == "POST"
        assert config["path"] == "/process"

    def test_route_invalid_method(self):
        ep = Endpoint(name="test-lb")
        with pytest.raises(ValueError, match="method must be"):
            ep._route("INVALID", "/path")

    def test_route_path_must_start_with_slash(self):
        ep = Endpoint(name="test-lb")
        with pytest.raises(ValueError, match="path must start with"):
            ep._route("GET", "no-slash")

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_cannot_use_as_direct_decorator_after_routes(self):
        ep = Endpoint(name="test-conflict")

        @ep.get("/health")
        async def health():
            return {"status": "ok"}

        with pytest.raises(ValueError, match="cannot use Endpoint as a direct decorator"):

            @ep
            async def my_func(data: dict) -> dict:
                return data


# -- resource config type selection matrix --


class TestResourceConfigTypeMatrix:
    """verify the full 2x2x2 matrix: (qb/lb) x (gpu/cpu) x (live/deploy)."""

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_qb_gpu_live_is_live_serverless(self):
        ep = Endpoint(name="t", gpu=GpuGroup.ADA_24)
        config = ep._build_resource_config()
        assert type(config).__name__ == "LiveServerless"

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "false"})
    def test_qb_gpu_deploy_is_serverless_endpoint(self):
        ep = Endpoint(name="t", gpu=GpuGroup.ADA_24, image="img:latest")
        config = ep._build_resource_config()
        assert type(config).__name__ == "ServerlessEndpoint"

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_qb_cpu_live_is_cpu_live_serverless(self):
        ep = Endpoint(name="t", cpu=CpuInstanceType.CPU3G_2_8)
        config = ep._build_resource_config()
        assert type(config).__name__ == "CpuLiveServerless"

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "false"})
    def test_qb_cpu_deploy_is_cpu_serverless_endpoint(self):
        ep = Endpoint(name="t", cpu=CpuInstanceType.CPU3G_2_8, image="img:latest")
        config = ep._build_resource_config()
        assert type(config).__name__ == "CpuServerlessEndpoint"

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_lb_gpu_live_is_live_load_balancer(self):
        ep = Endpoint(name="t", gpu=GpuGroup.ADA_24)
        ep._routes.append({"method": "GET", "path": "/h", "function": lambda: None, "function_name": "h"})
        config = ep._build_resource_config()
        assert type(config).__name__ == "LiveLoadBalancer"

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "false"})
    def test_lb_gpu_deploy_is_load_balancer_sls_resource(self):
        ep = Endpoint(name="t", gpu=GpuGroup.ADA_24, image="img:latest")
        ep._routes.append({"method": "GET", "path": "/h", "function": lambda: None, "function_name": "h"})
        config = ep._build_resource_config()
        assert type(config).__name__ == "LoadBalancerSlsResource"

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_lb_cpu_live_is_cpu_live_load_balancer(self):
        ep = Endpoint(name="t", cpu=CpuInstanceType.CPU3G_2_8)
        ep._routes.append({"method": "GET", "path": "/h", "function": lambda: None, "function_name": "h"})
        config = ep._build_resource_config()
        assert type(config).__name__ == "CpuLiveLoadBalancer"

    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "false"})
    def test_lb_cpu_deploy_is_cpu_load_balancer_sls_resource(self):
        ep = Endpoint(name="t", cpu=CpuInstanceType.CPU3G_2_8, image="img:latest")
        ep._routes.append({"method": "GET", "path": "/h", "function": lambda: None, "function_name": "h"})
        config = ep._build_resource_config()
        assert type(config).__name__ == "CpuLoadBalancerSlsResource"


# -- id= and client mode --


class TestEndpointId:
    def test_id_only(self):
        ep = Endpoint(id="abc123")
        assert ep.id == "abc123"
        assert ep.name is None
        assert ep.is_client is True

    def test_id_with_name(self):
        ep = Endpoint(name="my-ep", id="abc123")
        assert ep.id == "abc123"
        assert ep.name == "my-ep"
        assert ep.is_client is True

    def test_id_and_image_mutually_exclusive(self):
        with pytest.raises(ValueError, match="id and image are mutually exclusive"):
            Endpoint(name="test", id="abc123", image="img:latest")

    def test_name_or_id_required(self):
        with pytest.raises(ValueError, match="name or id is required"):
            Endpoint()

    def test_id_no_default_gpu(self):
        """client-only endpoints dont default to GPU ANY."""
        ep = Endpoint(id="abc123")
        assert ep._gpu is None
        assert ep._is_cpu is False


class TestClientMode:
    def test_image_is_client(self):
        ep = Endpoint(name="test", image="vllm:latest")
        assert ep.is_client is True

    def test_id_is_client(self):
        ep = Endpoint(id="abc123")
        assert ep.is_client is True

    def test_no_image_no_id_is_not_client(self):
        ep = Endpoint(name="test")
        assert ep.is_client is False

    def test_image_post_returns_coroutine(self):
        ep = Endpoint(name="test", image="vllm:latest")
        result = ep.post("/v1/completions", {"prompt": "hello"})
        # should be a coroutine (awaitable), not a decorator
        import asyncio
        assert asyncio.iscoroutine(result)
        result.close()

    def test_image_get_returns_coroutine(self):
        ep = Endpoint(name="test", image="vllm:latest")
        result = ep.get("/v1/models")
        import asyncio
        assert asyncio.iscoroutine(result)
        result.close()

    def test_decorator_mode_post_returns_callable(self):
        ep = Endpoint(name="test")
        result = ep.post("/compute")
        # should be a decorator (callable), not a coroutine
        assert callable(result)

    @pytest.mark.asyncio
    async def test_client_methods_raise_not_implemented(self):
        ep = Endpoint(id="abc123")
        with pytest.raises(NotImplementedError, match="client mode"):
            await ep.run({"prompt": "hello"})
        with pytest.raises(NotImplementedError, match="client mode"):
            await ep.runsync({"prompt": "hello"})
        with pytest.raises(NotImplementedError, match="client mode"):
            await ep.status("job-123")

    @pytest.mark.asyncio
    async def test_client_request_raises_not_implemented(self):
        ep = Endpoint(name="test", image="vllm:latest")
        with pytest.raises(NotImplementedError, match="client mode"):
            await ep.post("/v1/completions", {"prompt": "hello"})


# -- resource config caching --


class TestResourceConfigCaching:
    @patch.dict(os.environ, {"FLASH_IS_LIVE_PROVISIONING": "true"})
    def test_build_resource_config_is_cached(self):
        ep = Endpoint(name="test", gpu=GpuGroup.ADA_24)
        config1 = ep._build_resource_config()
        config2 = ep._build_resource_config()
        assert config1 is config2


# -- public import --


class TestPublicImport:
    def test_import_from_package(self):
        from runpod_flash import Endpoint as E
        assert E.__name__ == "Endpoint"
        assert E.__module__ == "runpod_flash.endpoint"

    def test_in_all(self):
        import runpod_flash
        assert "Endpoint" in runpod_flash.__all__
