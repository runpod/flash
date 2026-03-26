"""Tests for @remote decorator rejecting unknown keyword arguments (AE-2313).

The **extra catch-all in remote() silently swallows typos like
depndencies=["torch"], causing missing dependencies at runtime with
opaque import errors. These tests verify that unknown kwargs raise
TypeError with helpful "did you mean?" suggestions.
"""

import warnings

import pytest

from runpod_flash.core.resources import ServerlessResource


@pytest.fixture
def resource():
    return ServerlessResource(name="test", gpu="A100", workers=1)


class TestRemoteRejectsUnknownKwargs:
    """remote() must raise TypeError on unknown keyword arguments."""

    def test_single_unknown_kwarg_raises_type_error(self, resource):
        from runpod_flash.client import remote

        with pytest.raises(TypeError, match="unknown keyword argument"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                remote(resource, bogus=True)

    def test_typo_of_dependencies_raises_with_suggestion(self, resource):
        from runpod_flash.client import remote

        with pytest.raises(TypeError, match="depndencies.*Did you mean.*dependencies"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                remote(resource, depndencies=["torch"])

    def test_typo_of_system_dependencies_raises_with_suggestion(self, resource):
        from runpod_flash.client import remote

        with pytest.raises(
            TypeError, match="system_depndencies.*Did you mean.*system_dependencies"
        ):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                remote(resource, system_depndencies=["git"])

    def test_typo_of_accelerate_downloads_raises_with_suggestion(self, resource):
        from runpod_flash.client import remote

        with pytest.raises(
            TypeError, match="accelerate_download.*Did you mean.*accelerate_downloads"
        ):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                remote(resource, accelerate_download=False)

    def test_multiple_unknown_kwargs_all_listed(self, resource):
        from runpod_flash.client import remote

        with pytest.raises(
            TypeError,
            match="unknown keyword arguments.*bar.*foo",
        ):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                remote(resource, foo=1, bar=2)

    def test_no_suggestion_for_completely_unrelated_kwarg(self, resource):
        """Unknown kwargs with no close match should not include 'Did you mean?'."""
        from runpod_flash.client import remote

        with pytest.raises(TypeError, match="unknown keyword argument.*zzzzz"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                remote(resource, zzzzz=True)

    def test_valid_kwargs_still_work(self, resource):
        """All known parameters must still be accepted without error."""
        from runpod_flash.client import remote

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            decorator = remote(
                resource,
                dependencies=["torch"],
                system_dependencies=["git"],
                accelerate_downloads=False,
                local=True,
                method=None,
                path=None,
            )
        # local=True returns the function unwrapped, decorator should be callable
        assert callable(decorator)
