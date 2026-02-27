from __future__ import annotations

from typing import Optional, List
from pydantic import BaseModel
from enum import Enum


class GpuLowestPrice(BaseModel):
    minimumBidPrice: Optional[float] = None
    uninterruptablePrice: Optional[float] = None


class GpuTypeModel(BaseModel):
    id: str
    displayName: str
    memoryInGb: int


class GpuTypeDetail(GpuTypeModel):
    communityCloud: Optional[bool] = None
    communityPrice: Optional[float] = None
    communitySpotPrice: Optional[float] = None
    cudaCores: Optional[int] = None
    lowestPrice: Optional[GpuLowestPrice] = None
    manufacturer: Optional[str] = None
    maxGpuCount: Optional[int] = None
    oneMonthPrice: Optional[float] = None
    oneWeekPrice: Optional[float] = None
    secureCloud: Optional[bool] = None
    securePrice: Optional[float] = None
    secureSpotPrice: Optional[float] = None
    threeMonthPrice: Optional[float] = None


# TODO: this should be fetched from an API
class GpuGroup(Enum):
    ANY = "any"
    """Any GPU"""

    ADA_24 = "ADA_24"
    """NVIDIA GeForce RTX 4090"""

    ADA_32_PRO = "ADA_32_PRO"
    """NVIDIA GeForce RTX 5090"""

    ADA_48_PRO = "ADA_48_PRO"
    """NVIDIA RTX 6000 Ada Generation, NVIDIA L40, NVIDIA L40S"""

    ADA_80_PRO = "ADA_80_PRO"
    """NVIDIA H100 PCIe, NVIDIA H100 80GB HBM3, NVIDIA H100 NVL"""

    AMPERE_16 = "AMPERE_16"
    """NVIDIA RTX A4000, NVIDIA RTX A4500, NVIDIA RTX 4000 Ada Generation, NVIDIA RTX 2000 Ada Generation"""

    AMPERE_24 = "AMPERE_24"
    """NVIDIA RTX A5000, NVIDIA L4, NVIDIA GeForce RTX 3090"""

    AMPERE_48 = "AMPERE_48"
    """NVIDIA A40, NVIDIA RTX A6000"""

    AMPERE_80 = "AMPERE_80"
    """NVIDIA A100 80GB PCIe, NVIDIA A100-SXM4-80GB"""

    HOPPER_141 = "HOPPER_141"
    """NVIDIA H200"""

    BLACKWELL_180 = "BLACKWELL_180"
    """NVIDIA B200"""

    @classmethod
    def all(cls) -> List["GpuGroup"]:
        """Returns all GPU groups."""
        return [cls.AMPERE_48] + [g for g in cls if g != cls.ANY]

    @classmethod
    def to_gpu_ids_str(cls, gpu_types: List[GpuType | GpuGroup]) -> str:
        """
        The API expects a comma-separated list of pool IDs, with GPU ID negations (-4090, -3090, etc.). So to convert a list of GPU types to a string of pool IDs, we need to:
        1. Convert the GPU types to pool IDs
        2. Add a negation for each GPU type that is not in the list
        3. Join the pool IDs with a comma
        """
        pool_ids = set()
        pool_ids_from_groups = set()
        explicit_gpu_types = set()

        for gpu_type in gpu_types:
            if isinstance(gpu_type, GpuGroup):
                pool_id = gpu_type
                pool_ids_from_groups.add(pool_id)
            else:
                pool_id = _pool_from_gpu_type(gpu_type)
                explicit_gpu_types.add(gpu_type)

            if pool_id:
                pool_ids.add(pool_id)

        # only add negations for pools selected via explicit gpu types
        if explicit_gpu_types:
            # iterate over a snapshot because we add negations into the same set
            for pool_id in list(pool_ids):
                if pool_id in pool_ids_from_groups:
                    continue
                for gpu_type in POOLS_TO_TYPES.get(pool_id, []):
                    if gpu_type not in explicit_gpu_types:
                        pool_ids.add(f"-{gpu_type.value}")

        # normalize to strings for the api
        out = []
        for pool_id in pool_ids:
            if isinstance(pool_id, GpuGroup):
                out.append(pool_id.value)
            else:
                out.append(str(pool_id))
        return ",".join(out)

    @classmethod
    def from_gpu_ids_str(cls, gpu_ids_str: str) -> List[GpuGroup | GpuType]:
        """
        Convert a comma-separated list of pool IDs to a list of GPU types.
        """
        ids = gpu_ids_str.split(",")
        pool_ids = []
        gpu_types = []
        negated_gpu_types = []
        for id in ids:
            if id.startswith("-") and GpuType.is_gpu_type(id[1:]):
                negated_gpu_types.append(GpuType(id[1:]))
            elif GpuType.is_gpu_type(id):
                gpu_types.append(GpuType(id))
            else:
                pool_ids.append(id)

        ids = []

        for pool_id in pool_ids:
            try:
                pool = GpuGroup(pool_id)
            except ValueError:
                # ignore unknown pool ids from backend
                continue

            pool_gpus = POOLS_TO_TYPES.get(pool, [])
            # check if there are any negated gpu types in the pool
            if any(gpu_type in negated_gpu_types for gpu_type in pool_gpus):
                # add the gpu types that are not in the negated gpu types
                ids.extend(
                    [
                        gpu_type
                        for gpu_type in pool_gpus
                        if gpu_type not in negated_gpu_types
                    ]
                )
            else:
                ids.append(pool)

        ids.extend(gpu_types)
        return ids


# TODO: fetch from central registry at some point
class GpuType(Enum):
    ANY = "any"
    """Any GPU"""

    GEFORCE_RTX_4090 = "NVIDIA GeForce RTX 4090"
    GEFORCE_RTX_5090 = "NVIDIA GeForce RTX 5090"
    RTX_6000_ADA_GENERATION = "NVIDIA RTX 6000 Ada Generation"
    RTX_PRO_6000_BLACKWELL_SERVER_EDITION = (
        "NVIDIA RTX PRO 6000 Blackwell Server Edition"
    )
    RTX_PRO_6000_BLACKWELL_WORKSTATION_EDITION = (
        "NVIDIA RTX PRO 6000 Blackwell Workstation Edition"
    )
    H100_80GB_HBM3 = "NVIDIA H100 80GB HBM3"
    RTX_A4000 = "NVIDIA RTX A4000"
    RTX_A4500 = "NVIDIA RTX A4500"
    RTX_4000_ADA_GENERATION = "NVIDIA RTX 4000 Ada Generation"
    RTX_2000_ADA_GENERATION = "NVIDIA RTX 2000 Ada Generation"
    RTX_A5000 = "NVIDIA RTX A5000"
    L4 = "NVIDIA L4"
    GEFORCE_RTX_3090 = "NVIDIA GeForce RTX 3090"
    A40 = "NVIDIA A40"
    RTX_A6000 = "NVIDIA RTX A6000"
    A100_80GB_PCIe = "NVIDIA A100 80GB PCIe"
    A100_SXM4_80GB = "NVIDIA A100-SXM4-80GB"
    H200 = "NVIDIA H200"
    B200 = "NVIDIA B200"

    @classmethod
    def all(cls) -> List["GpuType"]:
        """Returns all GPU types."""
        return [g for g in cls if g != cls.ANY]

    @classmethod
    def is_gpu_type(cls, gpu_type: str) -> bool:
        """
        Check if a string is a valid GPU type.
        """
        return gpu_type in {m.value for m in cls}


POOLS_TO_TYPES = {
    GpuGroup.ADA_24: [GpuType.GEFORCE_RTX_4090],
    GpuGroup.ADA_32_PRO: [GpuType.GEFORCE_RTX_5090],
    GpuGroup.ADA_48_PRO: [GpuType.RTX_6000_ADA_GENERATION],
    GpuGroup.ADA_80_PRO: [GpuType.H100_80GB_HBM3],
    GpuGroup.AMPERE_16: [
        GpuType.RTX_A4000,
        GpuType.RTX_A4500,
        GpuType.RTX_4000_ADA_GENERATION,
        GpuType.RTX_2000_ADA_GENERATION,
    ],
    GpuGroup.AMPERE_24: [
        GpuType.RTX_A5000,
        GpuType.L4,
        GpuType.GEFORCE_RTX_3090,
    ],
    GpuGroup.AMPERE_48: [GpuType.A40, GpuType.RTX_A6000],
    GpuGroup.AMPERE_80: [GpuType.A100_80GB_PCIe, GpuType.A100_SXM4_80GB],
    GpuGroup.HOPPER_141: [GpuType.H200],
    GpuGroup.BLACKWELL_180: [GpuType.B200],
}


def _pool_from_gpu_type(gpu_type: GpuType) -> str:
    for group, types in POOLS_TO_TYPES.items():
        if gpu_type in types:
            return group
    return None
