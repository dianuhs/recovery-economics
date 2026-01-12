from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pricing:
    # Restore-event costs (USD per GB retrieved / moved)
    retrieval_per_gb: float
    egress_to_internet_per_gb: float
    egress_intra_aws_per_gb: float

    # Restore-event time penalty (hours) for the chosen retrieval posture.
    # NOTE: S3 Glacier Flexible Retrieval and Deep Archive have multiple retrieval
    # options (expedited/standard/bulk) with different time and pricing.
    # This tool uses a single "thaw" assumption per tier to keep the model simple.
    thaw_hours: float

    # Ongoing storage cost (USD per GB-month). Used for break-even analysis.
    storage_per_gb_month: float


def get_default_pricing(tier: str) -> Pricing:
    """
    Defaults are intended to be simple and explainable (not a full pricing engine).
    Treat these as "starter assumptions" you can later parameterize by region, discounts, etc.
    """
    if tier == "glacier":
        # S3 Glacier Flexible Retrieval (formerly S3 Glacier)
        return Pricing(
            retrieval_per_gb=0.01,
            egress_to_internet_per_gb=0.09,
            egress_intra_aws_per_gb=0.0,
            thaw_hours=4.0,
            # Example published price point often shown for Glacier Flexible Retrieval storage.
            # If you want region precision, we can add a --region + lookup later.
            storage_per_gb_month=0.0036,
        )

    if tier == "deep_archive":
        # S3 Glacier Deep Archive
        return Pricing(
            retrieval_per_gb=0.02,
            egress_to_internet_per_gb=0.09,
            egress_intra_aws_per_gb=0.0,
            thaw_hours=12.0,
            storage_per_gb_month=0.00099,
        )

    raise ValueError(f"Unknown tier: {tier}")


# Backwards-compatible alias (older tests / imports)
AwsRestorePricing = Pricing
