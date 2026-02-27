"""Integration tests for the deploy/undeploy lifecycle.

Exercises FlashApp and ResourceManager with mocked API calls,
letting real business logic (manifest, config drift, tracking) run.
"""

import asyncio
from unittest.mock import AsyncMock, patch


from runpod_flash.core.resources import LiveServerless
from runpod_flash.core.resources.resource_manager import ResourceManager


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestResourceManagerLifecycle:
    """ResourceManager tracks, deploys, and undeploys resources."""

    def test_register_and_list_resources(self):
        """Resources can be registered and listed."""
        manager = ResourceManager()
        resource = LiveServerless(
            name="lifecycle-gpu",
            gpu_count=1,
            gpu_ids="AMPERE_48",
            workersMin=0,
            workersMax=1,
        )

        uid = _run(manager.register_resource(resource))
        all_resources = manager.list_all_resources()
        assert uid in all_resources
        # LiveServerless appends -fb (flashboot) to the name
        assert "lifecycle-gpu" in all_resources[uid].name

    def test_undeploy_removes_resource(self):
        """Undeploy with force_remove=True removes from tracking."""
        manager = ResourceManager()
        resource = LiveServerless(
            name="to-remove",
            gpu_count=1,
            gpu_ids="AMPERE_48",
            workersMin=0,
            workersMax=1,
        )

        uid = _run(manager.register_resource(resource))
        assert uid in manager.list_all_resources()

        # Force-remove removes from tracking even without a real endpoint ID
        _run(manager.undeploy_resource(uid, force_remove=True))

        # Resource should be removed from tracking regardless of undeploy success
        assert uid not in manager.list_all_resources()

    def test_deploy_idempotent_no_drift(self):
        """Deploying the same config twice doesn't create duplicate resources."""
        manager = ResourceManager()

        config = LiveServerless(
            name="idempotent-gpu",
            gpu_count=1,
            gpu_ids="AMPERE_48",
            workersMin=0,
            workersMax=2,
        )

        # Mock _do_deploy to avoid real API calls — return a deployed-looking resource
        async def mock_do_deploy(self_resource):
            deployed = LiveServerless(
                name=self_resource.name,
                gpu_count=1,
                gpu_ids="AMPERE_48",
                workersMin=0,
                workersMax=2,
                id="ep-mock-123",
            )
            return deployed

        with patch.object(LiveServerless, "_do_deploy", mock_do_deploy):
            # First deploy
            _run(manager.get_or_deploy_resource(config))

            resource_key = config.get_resource_key()
            assert resource_key in manager.list_all_resources()

            # Second deploy with same config — should reuse
            config2 = LiveServerless(
                name="idempotent-gpu",
                gpu_count=1,
                gpu_ids="AMPERE_48",
                workersMin=0,
                workersMax=2,
            )
            _run(manager.get_or_deploy_resource(config2))

        # Should still be exactly one resource
        matching = [k for k in manager.list_all_resources() if "idempotent-gpu" in k]
        assert len(matching) == 1


class TestResourceManagerDriftDetection:
    """Config changes are detected and trigger updates."""

    def test_config_drift_triggers_update(self):
        """Changing config values triggers an update on the existing resource."""
        manager = ResourceManager()

        config_v1 = LiveServerless(
            name="drift-gpu",
            gpu_count=1,
            gpu_ids="AMPERE_48",
            workersMin=0,
            workersMax=1,
        )

        deploy_count = 0

        async def mock_do_deploy(self_resource):
            nonlocal deploy_count
            deploy_count += 1
            deployed = LiveServerless(
                name=self_resource.name,
                gpu_count=1,
                gpu_ids="AMPERE_48",
                workersMin=0,
                workersMax=self_resource.workersMax,
                id="ep-drift-123",
            )
            return deployed

        def mock_is_deployed(self_resource):
            return self_resource.id is not None

        with (
            patch.object(LiveServerless, "_do_deploy", mock_do_deploy),
            patch.object(LiveServerless, "is_deployed", mock_is_deployed),
        ):
            _run(manager.get_or_deploy_resource(config_v1))
            assert deploy_count == 1

            # Change workersMax (causes config drift)
            config_v2 = LiveServerless(
                name="drift-gpu",
                gpu_count=1,
                gpu_ids="AMPERE_48",
                workersMin=0,
                workersMax=5,
            )

            resource_key = config_v1.get_resource_key()
            existing = manager.list_all_resources()[resource_key]

            # Mock update on the existing resource
            with patch.object(
                type(existing), "update", new_callable=AsyncMock
            ) as mock_update:
                updated = LiveServerless(
                    name="drift-gpu",
                    gpu_count=1,
                    gpu_ids="AMPERE_48",
                    workersMin=0,
                    workersMax=5,
                    id="ep-drift-123",
                )
                mock_update.return_value = updated

                _run(manager.get_or_deploy_resource(config_v2))
                mock_update.assert_awaited_once()
