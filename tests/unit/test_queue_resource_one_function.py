"""Tests that queue-based resources reject multiple @remote functions."""

import os
from unittest.mock import patch

import pytest

from runpod_flash import LiveServerless
from runpod_flash.client import remote
from runpod_flash.core.resources.gpu import GpuGroup


@patch.dict(os.environ, {}, clear=True)
class TestQueueResourceOneFunction:
    def test_second_remote_on_same_config_raises(self):
        config = LiveServerless(
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
        config_a = LiveServerless(
            name="worker-a",
            imageName="img:latest",
            gpus=[GpuGroup.ANY],
        )
        config_b = LiveServerless(
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

    def test_error_message_includes_both_function_names(self):
        config = LiveServerless(
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

    def test_local_mode_allows_reuse_of_same_config(self):
        config = LiveServerless(
            name="worker",
            imageName="img:latest",
            gpus=[GpuGroup.ANY],
        )

        @remote(resource_config=config, local=True)
        async def fn_a():
            pass

        @remote(resource_config=config, local=True)
        async def fn_b():
            pass

    def test_class_remote_on_queue_resource_rejects_duplicate(self):
        config = LiveServerless(
            name="worker",
            imageName="img:latest",
            gpus=[GpuGroup.ANY],
        )

        @remote(resource_config=config)
        class MyModel:
            def predict(self, x):
                return x

        with pytest.raises(ValueError, match="already used by.*'MyModel'"):

            @remote(resource_config=config)
            class AnotherModel:
                def predict(self, x):
                    return x
