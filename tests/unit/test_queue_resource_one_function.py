"""Tests that queue-based resources reject multiple @remote functions."""

import os
from unittest.mock import patch

import pytest

from runpod_flash.client import remote
from runpod_flash.core.resources.serverless import ServerlessEndpoint
from runpod_flash.core.resources.gpu import GpuGroup


@patch.dict(os.environ, {}, clear=True)
class TestQueueResourceOneFunction:
    def test_second_remote_on_same_config_raises(self):
        config = ServerlessEndpoint(
            name="worker",
            imageName="img:latest",
            gpus=[GpuGroup.ANY],
        )

        @remote(resource_config=config)
        async def first_fn():
            pass

        with pytest.raises(ValueError, match="already used by.*'first_fn'"):

            @remote(resource_config=config)
            async def second_fn():
                pass

    def test_separate_configs_are_independent(self):
        config_a = ServerlessEndpoint(
            name="worker-a",
            imageName="img:latest",
            gpus=[GpuGroup.ANY],
        )
        config_b = ServerlessEndpoint(
            name="worker-b",
            imageName="img:latest",
            gpus=[GpuGroup.ANY],
        )

        @remote(resource_config=config_a)
        async def fn_a():
            pass

        @remote(resource_config=config_b)
        async def fn_b():
            pass

        # no error raised

    def test_lb_resource_allows_multiple_functions(self):
        from runpod_flash.core.resources.load_balancer_sls_resource import (
            LoadBalancerSlsResource,
        )

        lb = LoadBalancerSlsResource(name="lb", imageName="img:latest")

        @remote(resource_config=lb, method="POST", path="/a")
        async def route_a():
            pass

        @remote(resource_config=lb, method="POST", path="/b")
        async def route_b():
            pass

        # no error raised

    def test_error_message_includes_both_function_names(self):
        config = ServerlessEndpoint(
            name="my-worker",
            imageName="img:latest",
            gpus=[GpuGroup.ANY],
        )

        @remote(resource_config=config)
        async def greet():
            pass

        with pytest.raises(ValueError, match="'greet'.*'add'"):

            @remote(resource_config=config)
            async def add():
                pass
