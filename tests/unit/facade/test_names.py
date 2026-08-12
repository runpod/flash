import pytest

from runpod_flash.facade.names import normalize_resource_name


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("my-worker", "my-worker"),
        ("live-my-worker", "my-worker"),
        ("my-worker-fb", "my-worker"),
        ("live-my-worker-fb", "my-worker"),
        ("live-", ""),
    ],
)
def test_normalize_strips_live_prefix_and_fb_suffix(raw, expected):
    assert normalize_resource_name(raw) == expected
