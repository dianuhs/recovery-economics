from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AwsRestorePricing:
    """
    v1 keeps pricing explicit and overrideable.

    These defaults are placeholders to get the model + plumbing working.
    Next step: replace defaults with sourced values + region/tier tables in README.
    """

    retrieval_per_gb: float
    egress_to_internet_per_gb: float
    egress_intra_aws_per_gb: float
    thaw_hours: float


DEFAULT_AWS_PRICING: dict[str, AwsRestorePricing] = {
    "glacier": AwsRestorePricing(
        retrieval_per_gb=0.01,
        egress_to_internet_per_gb=0.09,
        egress_intra_aws_per_gb=0.00,
        thaw_hours=4.0,
    ),
    "deep_archive": AwsRestorePricing(
        retrieval_per_gb=0.02,
        egress_to_internet_per_gb=0.09,
        egress_intra_aws_per_gb=0.00,
        thaw_hours=12.0,
    ),
}


def get_default_pricing(storage_tier: str) -> AwsRestorePricing:
    tier = storage_tier.strip().lower()
    if tier not in DEFAULT_AWS_PRICING:
        raise ValueError(f"Unsupported storage_tier: {storage_tier}")
    return DEFAULT_AWS_PRICING[tier]
