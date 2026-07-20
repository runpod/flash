from runpod_flash.core.exceptions import (
    LocalModulePayloadTooLargeError,
    LocalModuleResolutionError,
)


def test_local_module_resolution_error_carries_message():
    err = LocalModuleResolutionError("cannot resolve 'utils'")
    assert str(err) == "cannot resolve 'utils'"
    assert isinstance(err, Exception)


def test_payload_too_large_error_carries_message():
    err = LocalModulePayloadTooLargeError("9 MB exceeds 8 MB cap")
    assert str(err) == "9 MB exceeds 8 MB cap"
    assert isinstance(err, Exception)
