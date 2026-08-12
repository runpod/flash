"""smoke: apps SDK and flash both import in this environment."""


def test_apps_public_symbols_import():
    from runpod.apps import Api, App, Queue, ResourceSpec  # noqa: F401


def test_apps_dispatch_primitives_import():
    from runpod.apps.targets import QueueClient, SentinelTarget  # noqa: F401


def test_flash_still_imports():
    import runpod_flash  # noqa: F401

    assert runpod_flash.__version__
