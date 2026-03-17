"""Tests for max_concurrency in manifest models and builder."""

from dataclasses import asdict

from runpod_flash.runtime.models import ResourceConfig


class TestResourceConfigMaxConcurrency:
    def test_default_is_one(self):
        rc = ResourceConfig(resource_type="LiveServerless")
        assert rc.max_concurrency == 1

    def test_explicit_value(self):
        rc = ResourceConfig(resource_type="LiveServerless", max_concurrency=5)
        assert rc.max_concurrency == 5

    def test_from_dict_with_max_concurrency(self):
        data = {
            "resource_type": "LiveServerless",
            "max_concurrency": 10,
            "functions": [],
        }
        rc = ResourceConfig.from_dict(data)
        assert rc.max_concurrency == 10

    def test_from_dict_missing_field_defaults_to_one(self):
        data = {
            "resource_type": "LiveServerless",
            "functions": [],
        }
        rc = ResourceConfig.from_dict(data)
        assert rc.max_concurrency == 1

    def test_round_trip_through_dict(self):
        rc = ResourceConfig(resource_type="LiveServerless", max_concurrency=7)
        d = asdict(rc)
        assert d["max_concurrency"] == 7
        rc2 = ResourceConfig.from_dict(d)
        assert rc2.max_concurrency == 7
