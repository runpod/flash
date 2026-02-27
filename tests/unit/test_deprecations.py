"""tests for deprecation warnings on legacy classes and remote decorator."""

import importlib
import warnings

import pytest


_DEPRECATED_CLASSES = [
    "CpuLiveLoadBalancer",
    "CpuLiveServerless",
    "CpuLoadBalancerSlsResource",
    "CpuServerlessEndpoint",
    "LiveLoadBalancer",
    "LiveServerless",
    "LoadBalancerSlsResource",
    "ServerlessEndpoint",
]

_NON_DEPRECATED = [
    "Endpoint",
    "EndpointJob",
    "CpuInstanceType",
    "CudaVersion",
    "DataCenter",
    "GpuGroup",
    "GpuType",
    "NetworkVolume",
    "PodTemplate",
    "ResourceManager",
    "ServerlessScalerType",
    "ServerlessType",
    "FlashApp",
]


class TestDeprecatedResourceClasses:
    @pytest.mark.parametrize("name", _DEPRECATED_CLASSES)
    def test_import_emits_deprecation_warning(self, name):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import runpod_flash

            # force re-trigger via __getattr__
            importlib.reload(runpod_flash)
            _ = getattr(runpod_flash, name)

        deprecation_warnings = [
            x for x in w if issubclass(x.category, DeprecationWarning)
        ]
        msgs = [str(x.message) for x in deprecation_warnings]
        assert any(name in m and "Endpoint" in m for m in msgs), (
            f"expected DeprecationWarning mentioning {name!r}, got {msgs}"
        )

    @pytest.mark.parametrize("name", _DEPRECATED_CLASSES)
    def test_import_still_returns_class(self, name):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import runpod_flash

            cls = getattr(runpod_flash, name)
        assert cls is not None
        assert hasattr(cls, "__name__") or hasattr(cls, "__init__")


class TestNonDeprecatedNames:
    @pytest.mark.parametrize("name", _NON_DEPRECATED)
    def test_no_deprecation_warning(self, name):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import runpod_flash

            importlib.reload(runpod_flash)
            _ = getattr(runpod_flash, name)

        deprecation_warnings = [
            x
            for x in w
            if issubclass(x.category, DeprecationWarning) and name in str(x.message)
        ]
        assert len(deprecation_warnings) == 0, (
            f"unexpected DeprecationWarning for {name!r}"
        )


class TestRemoteDeprecation:
    def test_import_remote_emits_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import runpod_flash

            importlib.reload(runpod_flash)
            _ = runpod_flash.remote

        deprecation_warnings = [
            x for x in w if issubclass(x.category, DeprecationWarning)
        ]
        msgs = [str(x.message) for x in deprecation_warnings]
        assert any("remote" in m and "Endpoint" in m for m in msgs)

    def test_calling_remote_emits_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from runpod_flash.client import remote
            from runpod_flash.core.resources import LiveServerless

            cfg = LiveServerless(name="test")
            remote(resource_config=cfg)

        deprecation_warnings = [
            x for x in w if issubclass(x.category, DeprecationWarning)
        ]
        msgs = [str(x.message) for x in deprecation_warnings]
        assert any("remote" in m for m in msgs)
