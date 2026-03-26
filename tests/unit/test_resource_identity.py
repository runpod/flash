"""Unit tests for resource identity and resource_id stability."""

from runpod_flash.core.resources.live_serverless import LiveServerless
from runpod_flash.core.resources.gpu import GpuGroup


class TestResourceIdentity:
    """Test resource_id stability and identity management."""

    def test_resource_id_stable_across_multiple_calls(self):
        """Test that resource_id remains the same when called multiple times."""
        config = LiveServerless(
            name="test-endpoint",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=3,
            flashboot=True,
        )

        # Call resource_id multiple times
        id1 = config.resource_id
        id2 = config.resource_id
        id3 = config.resource_id

        # All should be identical
        assert id1 == id2
        assert id2 == id3

    def test_resource_id_stable_after_validator_mutations(self):
        """Test that resource_id is stable even after validators mutate the object."""
        config = LiveServerless(
            name="test-gpu",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=3,
            flashboot=True,
        )

        # Get resource_id (this triggers caching)
        first_id = config.resource_id

        # Verify validator mutated the name (should have "-fb" suffix)
        assert config.name.endswith("-fb")

        # Get resource_id again
        second_id = config.resource_id

        # Should still be the same
        assert first_id == second_id

    def test_resource_id_different_for_different_configs(self):
        """Test that different configurations produce different resource_ids."""
        config1 = LiveServerless(
            name="endpoint-1",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=3,
        )

        config2 = LiveServerless(
            name="endpoint-2",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=3,
        )

        # Different names should produce different IDs
        assert config1.resource_id != config2.resource_id

    def test_resource_id_same_for_identical_configs(self):
        """Test that identical configurations produce the same resource_id."""
        config1 = LiveServerless(
            name="test-endpoint",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=3,
            flashboot=True,
        )

        config2 = LiveServerless(
            name="test-endpoint",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=3,
            flashboot=True,
        )

        # Identical configs should produce identical IDs
        assert config1.resource_id == config2.resource_id

    def test_pickled_resource_preserves_id(self):
        """Test that serialization round-trip preserves resource_id.

        Uses Pydantic's model_validate(model_dump()) instead of cloudpickle
        because cloudpickle + Pydantic v2 produces corrupt schemas under
        parallel test execution (pytest-xdist).
        """
        config = LiveServerless(
            name="test-pickle",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=3,
            flashboot=True,
        )

        id_before = config.resource_id

        # Round-trip through Pydantic serialization
        restored = LiveServerless.model_validate(config.model_dump(by_alias=True))

        id_after = restored.resource_id

        assert id_before == id_after

    def test_validator_idempotency_name_suffix(self):
        """Test that validators don't add multiple suffixes."""
        config = LiveServerless(
            name="test",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=3,
            flashboot=True,
        )

        # First access triggers validators
        _ = config.resource_id

        # Name should have exactly one "-fb" suffix
        assert config.name == "test-fb"
        assert config.name.count("-fb") == 1

        # Manually trigger validator again (simulate multiple runs)
        config.sync_input_fields()

        # Should still have only one "-fb" suffix
        assert config.name == "test-fb"
        assert config.name.count("-fb") == 1

    def test_resource_id_excludes_none_values(self):
        """Test that None values are excluded from resource_id computation."""
        config1 = LiveServerless(
            name="test",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=3,
            flashboot=True,
        )

        config2 = LiveServerless(
            name="test",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=3,
            flashboot=True,
            networkVolume=None,  # Explicitly set to None
        )

        # Both should have the same resource_id (None values excluded)
        assert config1.resource_id == config2.resource_id

    def test_resource_id_stable_after_id_field_set(self):
        """Test that resource_id remains stable even after 'id' field is set.

        This simulates the real-world scenario where:
        1. Config created before deployment (no id)
        2. resource_id computed and cached
        3. Resource deployed, id field set to endpoint ID
        4. resource_id should remain unchanged
        """
        config = LiveServerless(
            name="test-deployment",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=3,
            flashboot=True,
        )

        # Get resource_id before deployment (no id field)
        id_before_deployment = config.resource_id

        # Simulate deployment - set the id field (like deploy() method does)
        config.id = "abc123endpoint"

        # Get resource_id after deployment
        id_after_deployment = config.resource_id

        # Should be identical - id field should not affect hash
        assert id_before_deployment == id_after_deployment

    def test_resource_id_excludes_id_field_from_hash(self):
        """Test that the 'id' field is excluded from resource_id computation.

        Two configs with identical parameters but different 'id' fields
        should produce the same resource_id.
        """
        config1 = LiveServerless(
            name="test-endpoint",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=3,
            flashboot=True,
        )
        config1.id = "endpoint-123"

        config2 = LiveServerless(
            name="test-endpoint",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=3,
            flashboot=True,
        )
        config2.id = "endpoint-456"  # Different endpoint ID

        # Should have the same resource_id despite different ids
        assert config1.resource_id == config2.resource_id

    def test_config_hash_excludes_server_assigned_fields(self):
        """Test that config_hash excludes server-assigned fields.

        Server-assigned fields like templateId, aiKey, userId should not affect
        config hash for drift detection.
        """
        # Create a fresh config
        fresh_config = LiveServerless(
            name="test-endpoint",
            gpus=[GpuGroup.ADA_24],
            workersMin=0,
            workersMax=3,
            flashboot=True,
        )

        # Get hash before "deployment"
        hash_before = fresh_config.config_hash

        # Simulate server response by setting server-assigned fields
        fresh_config.templateId = "ig8m26v4p8"
        fresh_config.aiKey = "some-ai-key"
        fresh_config.userId = "user_123"
        fresh_config.type = "QB"
        fresh_config.executionTimeoutMs = 0
        fresh_config.allowedCudaVersions = ""

        # Get hash after "deployment"
        hash_after = fresh_config.config_hash

        # Hashes should be identical - server fields shouldn't affect hash
        assert hash_before == hash_after
