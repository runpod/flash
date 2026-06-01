from enum import Enum


class DataCenter(str, Enum):
    """Enum representing available RunPod data centers.

    NOTE: these are only datacenters with storage support, and S3 API support.
    """

    # north america
    US_CA_2 = "US-CA-2"
    US_IL_1 = "US-IL-1"
    US_KS_2 = "US-KS-2"
    US_MO_1 = "US-MO-1"
    US_MO_2 = "US-MO-2"
    US_NC_2 = "US-NC-2"
    US_NE_1 = "US-NE-1"
    US_WA_1 = "US-WA-1"

    # europe
    EU_CZ_1 = "EU-CZ-1"
    EU_RO_1 = "EU-RO-1"
    EUR_NO_1 = "EUR-NO-1"

    @classmethod
    def from_string(cls, value: str) -> "DataCenter":
        """Parse a datacenter ID string into a DataCenter enum.

        Accepts the canonical form (e.g. "EU-RO-1") as well as common
        variations like lowercase or underscore-separated.
        """
        normalized = value.strip().upper().replace("_", "-")
        try:
            return cls(normalized)
        except ValueError:
            valid = ", ".join(dc.value for dc in cls)
            raise ValueError(
                f"Unknown datacenter '{value}'. Valid datacenters: {valid}"
            )

    @classmethod
    def all(cls) -> list["DataCenter"]:
        """Return all datacenters."""
        return list(cls)


# data centers that support CPU serverless endpoints
CPU_DATACENTERS: frozenset[DataCenter] = frozenset(
    {
        DataCenter.EU_RO_1,
    }
)
