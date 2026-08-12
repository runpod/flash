"""resource-name normalization shared across the dispatch facade.

ported verbatim from runpod_flash/client.py:_normalize_resource_name so
sentinel routing keys match the deployed endpoint names exactly.
"""


def normalize_resource_name(name: str) -> str:
    """strip the live- provisioning prefix and -fb flashboot suffix."""
    result = name
    if result.startswith("live-"):
        result = result[len("live-") :]
    if result.endswith("-fb"):
        result = result[: -len("-fb")]
    return result
