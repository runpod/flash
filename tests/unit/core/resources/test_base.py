"""Tests for base resource classes."""

import json
import pickle
from typing import Optional

import pytest

from runpod_flash.core.resources.base import BaseResource, DeployableResource


class SampleResource(BaseResource):
    """Sample resource for testing BaseResource."""

    name: str
    value: int
    optional_field: Optional[str] = None


class HashedFieldsResource(BaseResource):
    """Resource with custom _hashed_fields."""

    _hashed_fields = frozenset({"name", "important_field"})

    name: str
    important_field: str
    ignored_field: str = "ignored"


class SampleDeployableResource(DeployableResource):
    """Sample deployable resource for testing."""

    name: str
    endpoint_url: Optional[str] = None
    deployed: bool = False

    @property
    def url(self) -> str:
        """Return endpoint URL."""
        return self.endpoint_url or f"https://example.com/{self.name}"

    def is_deployed(self) -> bool:
        """Check if deployed."""
        return self.deployed

    async def deploy(self) -> "SampleDeployableResource":
        """Deploy the resource."""
        self.deployed = True
        self.id = "deployed-123"
        return self

    async def undeploy(self) -> bool:
        """Undeploy the resource."""
        self.deployed = False
        self.id = None
        return True


class TestBaseResource:
    """Test BaseResource functionality."""

    def test_resource_id_generation(self):
        """Test that resource_id is generated correctly."""
        resource = SampleResource(name="test", value=42)

        resource_id = resource.resource_id

        assert resource_id.startswith("SampleResource_")
        assert len(resource_id) == len("SampleResource_") + 32  # MD5 hash length

    def test_resource_id_stability(self):
        """Test that resource_id is stable for same configuration."""
        resource1 = SampleResource(name="test", value=42)
        resource2 = SampleResource(name="test", value=42)

        assert resource1.resource_id == resource2.resource_id

    def test_resource_id_caching(self):
        """Test that resource_id is cached."""
        resource = SampleResource(name="test", value=42)

        # First access
        id1 = resource.resource_id

        # Second access should return cached value
        id2 = resource.resource_id

        assert id1 is id2
        assert "_cached_resource_id" in resource.__dict__

    def test_resource_id_excludes_id_field(self):
        """Test that id field is excluded from resource_id hash."""
        resource1 = SampleResource(name="test", value=42)
        resource1.id = "assigned-id-1"

        resource2 = SampleResource(name="test", value=42)
        resource2.id = "assigned-id-2"

        # Should have same resource_id despite different ids
        assert resource1.resource_id == resource2.resource_id

    def test_resource_id_different_for_different_config(self):
        """Test that different configurations produce different resource_ids."""
        resource1 = SampleResource(name="test", value=42)
        resource2 = SampleResource(name="test", value=43)

        assert resource1.resource_id != resource2.resource_id

    def test_resource_id_with_optional_fields(self):
        """Test resource_id handles optional fields correctly."""
        resource1 = SampleResource(name="test", value=42)
        resource2 = SampleResource(name="test", value=42, optional_field="extra")

        # Optional field should affect hash
        assert resource1.resource_id != resource2.resource_id

    def test_resource_id_with_hashed_fields(self):
        """Test resource_id respects _hashed_fields."""
        resource1 = HashedFieldsResource(
            name="test",
            important_field="important",
            ignored_field="value1",
        )
        resource2 = HashedFieldsResource(
            name="test",
            important_field="important",
            ignored_field="value2",  # Different but ignored
        )

        # Should have same hash because ignored_field is not in _hashed_fields
        assert resource1.resource_id == resource2.resource_id

    def test_resource_id_with_hashed_fields_important_change(self):
        """Test that changes to hashed fields affect resource_id."""
        resource1 = HashedFieldsResource(
            name="test",
            important_field="important1",
            ignored_field="ignored",
        )
        resource2 = HashedFieldsResource(
            name="test",
            important_field="important2",
            ignored_field="ignored",
        )

        # Should have different hash because important_field changed
        assert resource1.resource_id != resource2.resource_id

    def test_config_hash_generation(self):
        """Test that config_hash is generated correctly."""
        resource = SampleResource(name="test", value=42)

        config_hash = resource.config_hash

        assert len(config_hash) == 32  # MD5 hash length

    def test_config_hash_not_cached(self):
        """Test that config_hash is computed fresh each time."""
        resource = SampleResource(name="test", value=42)

        hash1 = resource.config_hash

        # Modify the resource
        resource.value = 43

        hash2 = resource.config_hash

        # Should be different because config changed
        assert hash1 != hash2

    def test_config_hash_excludes_id(self):
        """Test that config_hash excludes id field."""
        resource1 = SampleResource(name="test", value=42)
        resource1.id = "id-1"

        resource2 = SampleResource(name="test", value=42)
        resource2.id = "id-2"

        # Should have same config hash
        assert resource1.config_hash == resource2.config_hash

    def test_get_resource_key_with_name(self):
        """Test get_resource_key with named resource."""
        resource = SampleResource(name="my-resource", value=42)

        key = resource.get_resource_key()

        assert key == "SampleResource:my-resource"

    def test_get_resource_key_without_name(self):
        """Test get_resource_key falls back to resource_id."""

        class UnnamedResource(BaseResource):
            value: int

        resource = UnnamedResource(value=42)

        key = resource.get_resource_key()

        # Should fall back to resource_id
        assert key == resource.resource_id

    def test_pickle_support(self):
        """Test that BaseResource can be pickled and unpickled."""
        resource = SampleResource(name="test", value=42, optional_field="extra")
        resource.id = "test-id"

        # Pickle
        pickled = pickle.dumps(resource)

        # Unpickle
        restored = pickle.loads(pickled)

        assert restored.name == "test"
        assert restored.value == 42
        assert restored.optional_field == "extra"
        assert restored.id == "test-id"

    def test_pickle_preserves_cached_resource_id(self):
        """Test that cached resource_id survives pickling."""
        resource = SampleResource(name="test", value=42)

        # Access resource_id to cache it
        original_id = resource.resource_id

        # Pickle and unpickle
        pickled = pickle.dumps(resource)
        restored = pickle.loads(pickled)

        # Should have same resource_id
        assert restored.resource_id == original_id

    def test_getstate_removes_weakrefs(self):
        """Test that __getstate__ removes weakrefs."""
        resource = SampleResource(name="test", value=42)

        # Add a weakref to the object (simulating internal state)
        import weakref

        # Create an object that can be weakly referenced
        class DummyClass:
            pass

        dummy_obj = DummyClass()
        weak_ref = weakref.ref(dummy_obj)
        resource.__dict__["_weak_ref"] = weak_ref

        # Get state for pickling
        state = resource.__getstate__()

        # Weakref should be removed
        assert "_weak_ref" not in state

    def test_setstate_restores_dict(self):
        """Test that __setstate__ restores object dict."""
        resource = SampleResource(name="test", value=42)

        state = {
            "name": "restored",
            "value": 100,
            "optional_field": "restored_optional",
        }

        resource.__setstate__(state)

        assert resource.name == "restored"
        assert resource.value == 100
        assert resource.optional_field == "restored_optional"

    def test_pydantic_validation(self):
        """Test that Pydantic validation works."""
        # Valid resource
        resource = SampleResource(name="test", value=42)
        assert resource.name == "test"

        # Invalid type should raise validation error
        with pytest.raises(Exception):  # Pydantic validation error
            SampleResource(name="test", value="not_an_int")

    def test_model_dump(self):
        """Test model_dump functionality."""
        resource = SampleResource(name="test", value=42, optional_field="extra")
        resource.id = "test-id"

        dumped = resource.model_dump()

        assert dumped["name"] == "test"
        assert dumped["value"] == 42
        assert dumped["optional_field"] == "extra"
        assert dumped["id"] == "test-id"

    def test_model_dump_json(self):
        """Test model_dump_json functionality."""
        resource = SampleResource(name="test", value=42)

        json_str = resource.model_dump_json()

        # Should be valid JSON
        parsed = json.loads(json_str)
        assert parsed["name"] == "test"
        assert parsed["value"] == 42


class TestDeployableResource:
    """Test DeployableResource functionality."""

    @pytest.mark.asyncio
    async def test_deploy(self):
        """Test deploy method."""
        resource = SampleDeployableResource(name="test-resource")

        assert not resource.is_deployed()

        deployed = await resource.deploy()

        assert deployed.is_deployed()
        assert deployed.id == "deployed-123"

    @pytest.mark.asyncio
    async def test_undeploy(self):
        """Test undeploy method."""
        resource = SampleDeployableResource(name="test-resource")
        await resource.deploy()

        assert resource.is_deployed()

        result = await resource.undeploy()

        assert result is True
        assert not resource.is_deployed()
        assert resource.id is None

    def test_url_property(self):
        """Test url property."""
        resource = SampleDeployableResource(name="test-resource")

        url = resource.url

        assert url == "https://example.com/test-resource"

    def test_url_with_custom_endpoint(self):
        """Test url with custom endpoint_url."""
        resource = SampleDeployableResource(
            name="test-resource", endpoint_url="https://custom.com/endpoint"
        )

        url = resource.url

        assert url == "https://custom.com/endpoint"

    def test_is_deployed(self):
        """Test is_deployed method."""
        resource = SampleDeployableResource(name="test-resource")

        assert not resource.is_deployed()

        resource.deployed = True

        assert resource.is_deployed()

    def test_str_representation(self):
        """Test string representation."""
        resource = SampleDeployableResource(name="test-resource")

        str_repr = str(resource)

        assert str_repr == "SampleDeployableResource"

    def test_inherits_base_resource_properties(self):
        """Test that DeployableResource inherits BaseResource properties."""
        resource = SampleDeployableResource(name="test-resource")

        # Should have resource_id from BaseResource
        assert resource.resource_id.startswith("SampleDeployableResource_")

        # Should have get_resource_key from BaseResource
        key = resource.get_resource_key()
        assert key == "SampleDeployableResource:test-resource"

    def test_abstract_methods_required(self):
        """Test that abstract methods must be implemented."""

        # This should fail because abstract methods are not implemented
        with pytest.raises(TypeError):

            class IncompleteResource(DeployableResource):
                name: str

            # Cannot instantiate without implementing abstract methods
            IncompleteResource(name="test")

    @pytest.mark.asyncio
    async def test_deploy_returns_self(self):
        """Test that deploy returns the resource instance."""
        resource = SampleDeployableResource(name="test-resource")

        deployed = await resource.deploy()

        assert deployed is resource

    def test_resource_id_stable_across_deployment(self):
        """Test that resource_id remains stable before and after deployment."""
        resource = SampleDeployableResource(name="test-resource")

        id_before = resource.resource_id

        # Deploy changes the 'id' field, but not resource_id
        resource.deployed = True
        resource.id = "deployed-id"

        id_after = resource.resource_id

        # resource_id should remain stable
        assert id_before == id_after
