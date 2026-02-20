import logging
import os
from functools import singledispatch

from ..core.resources import (
    CpuLiveLoadBalancer,
    CpuLiveServerless,
    CpuServerlessEndpoint,
    LiveLoadBalancer,
    LiveServerless,
    LoadBalancerSlsResource,
    ServerlessEndpoint,
)
from .live_serverless import LiveServerlessStub
from .load_balancer_sls import LoadBalancerSlsStub
from .serverless import ServerlessEndpointStub

log = logging.getLogger(__name__)


@singledispatch
def stub_resource(resource, **extra):
    async def fallback(*args, **kwargs):
        return {"error": f"Cannot stub {resource.__class__.__name__}."}

    return fallback


def _create_live_serverless_stub(resource, **extra):
    """Create a live serverless stub for both LiveServerless and CpuLiveServerless."""
    stub = LiveServerlessStub(resource)

    # Function execution
    async def stubbed_resource(
        func,
        dependencies,
        system_dependencies,
        accelerate_downloads,
        *args,
        **kwargs,
    ) -> dict:
        if args == (None,):
            args = []

        request = await stub.prepare_request(
            func,
            dependencies,
            system_dependencies,
            accelerate_downloads,
            *args,
            **kwargs,
        )
        response = await stub.ExecuteFunction(request)
        return stub.handle_response(response)

    # Class method execution
    async def execute_class_method(request):
        response = await stub.ExecuteFunction(request)
        return stub.handle_response(response)

    # Inject ProductionWrapper if in production mode
    if os.getenv("RUNPOD_ENDPOINT_ID"):
        try:
            from ..runtime.production_wrapper import create_production_wrapper

            wrapper = create_production_wrapper()
            original_stubbed = stubbed_resource
            original_class_method = execute_class_method

            async def wrapped_stubbed(
                func,
                dependencies,
                system_dependencies,
                accelerate_downloads,
                *args,
                **kwargs,
            ):
                return await wrapper.wrap_function_execution(
                    original_stubbed,
                    func,
                    dependencies,
                    system_dependencies,
                    accelerate_downloads,
                    *args,
                    **kwargs,
                )

            async def wrapped_class_method(request):
                return await wrapper.wrap_class_method_execution(
                    original_class_method, request
                )

            stubbed_resource = wrapped_stubbed
            execute_class_method = wrapped_class_method

        except ImportError:
            log.warning(
                "ProductionWrapper not available, cross-endpoint routing disabled"
            )

    # Attach the method to the function
    stubbed_resource.execute_class_method = execute_class_method

    return stubbed_resource


@stub_resource.register(LiveServerless)
def _(resource, **extra):
    return _create_live_serverless_stub(resource, **extra)


@stub_resource.register(CpuLiveServerless)
def _(resource, **extra):
    return _create_live_serverless_stub(resource, **extra)


@stub_resource.register(ServerlessEndpoint)
def _(resource, **extra):
    async def stubbed_resource(
        func,
        dependencies,
        system_dependencies,
        accelerate_downloads,
        *args,
        **kwargs,
    ) -> dict:
        if dependencies or system_dependencies:
            log.warning(
                "Dependencies are not supported for ServerlessEndpoint. "
                "They will be ignored."
            )

        stub = ServerlessEndpointStub(resource)
        payload = stub.prepare_payload(func, *args, **kwargs)
        response = await stub.execute(payload, sync=extra.get("sync", False))
        return stub.handle_response(response)

    return stubbed_resource


@stub_resource.register(CpuServerlessEndpoint)
def _(resource, **extra):
    async def stubbed_resource(
        func,
        dependencies,
        system_dependencies,
        accelerate_downloads,
        *args,
        **kwargs,
    ) -> dict:
        if dependencies or system_dependencies:
            log.warning(
                "Dependencies are not supported for CpuServerlessEndpoint. "
                "They will be ignored."
            )

        stub = ServerlessEndpointStub(resource)
        payload = stub.prepare_payload(func, *args, **kwargs)
        response = await stub.execute(payload, sync=extra.get("sync", False))
        return stub.handle_response(response)

    return stubbed_resource


@stub_resource.register(LoadBalancerSlsResource)
def _(resource, **extra):
    """Create stub for LoadBalancerSlsResource (HTTP-based execution)."""
    stub = LoadBalancerSlsStub(resource)

    async def stubbed_resource(
        func,
        dependencies,
        system_dependencies,
        accelerate_downloads,
        *args,
        **kwargs,
    ) -> dict:
        return await stub(
            func,
            dependencies,
            system_dependencies,
            accelerate_downloads,
            *args,
            **kwargs,
        )

    return stubbed_resource


@stub_resource.register(LiveLoadBalancer)
def _(resource, **extra):
    """Create stub for LiveLoadBalancer (HTTP-based execution, local testing)."""
    stub = LoadBalancerSlsStub(resource)

    async def stubbed_resource(
        func,
        dependencies,
        system_dependencies,
        accelerate_downloads,
        *args,
        **kwargs,
    ) -> dict:
        return await stub(
            func,
            dependencies,
            system_dependencies,
            accelerate_downloads,
            *args,
            **kwargs,
        )

    return stubbed_resource


@stub_resource.register(CpuLiveLoadBalancer)
def _(resource, **extra):
    """Create stub for CpuLiveLoadBalancer (HTTP-based execution, local testing)."""
    stub = LoadBalancerSlsStub(resource)

    async def stubbed_resource(
        func,
        dependencies,
        system_dependencies,
        accelerate_downloads,
        *args,
        **kwargs,
    ) -> dict:
        return await stub(
            func,
            dependencies,
            system_dependencies,
            accelerate_downloads,
            *args,
            **kwargs,
        )

    return stubbed_resource
