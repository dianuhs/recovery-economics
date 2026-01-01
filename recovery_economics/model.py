from __future__ import annotations

from dataclasses import dataclass

from .aws_pricing import AwsRestorePricing


@dataclass(frozen=True)
class RestoreInputs:
    data_size_gb: float
    bandwidth_mbps: float
    link_efficiency: float  # 0..1
    restore_destination: str  # "internet" | "intra_aws"
    rto_hours: float | None = None


@dataclass(frozen=True)
class RestoreResult:
    retrieval_cost_usd: float
    egress_cost_usd: float
    total_cost_usd: float
    thaw_time_hours: float
    transfer_time_hours: float
    total_time_hours: float
    rto_hours: float | None
    rto_mismatch: bool | None


def _validate(inputs: RestoreInputs) -> None:
    if inputs.data_size_gb <= 0:
        raise ValueError("data_size_gb must be > 0")
    if inputs.bandwidth_mbps <= 0:
        raise ValueError("bandwidth_mbps must be > 0")
    if not (0 < inputs.link_efficiency <= 1):
        raise ValueError("link_efficiency must be in (0, 1]")
    dest = inputs.restore_destination.strip().lower()
    if dest not in {"internet", "intra_aws"}:
        raise ValueError("restore_destination must be 'internet' or 'intra_aws'")
    if inputs.rto_hours is not None and inputs.rto_hours <= 0:
        raise ValueError("rto_hours must be > 0 if provided")


def transfer_time_hours(
    data_size_gb: float, bandwidth_mbps: float, efficiency: float
) -> float:
    """
    Transfer time in hours using effective throughput = bandwidth_mbps * efficiency.
    v1 approximation: 1 GB = 1e9 bytes (documented).
    """
    effective_mbps = bandwidth_mbps * efficiency
    bits = data_size_gb * 1e9 * 8
    seconds = bits / (effective_mbps * 1e6)
    return seconds / 3600.0


def estimate_restore(
    inputs: RestoreInputs, pricing: AwsRestorePricing
) -> RestoreResult:
    _validate(inputs)
    dest = inputs.restore_destination.strip().lower()

    retrieval_cost = inputs.data_size_gb * pricing.retrieval_per_gb

    if dest == "internet":
        egress_cost = inputs.data_size_gb * pricing.egress_to_internet_per_gb
    else:
        egress_cost = inputs.data_size_gb * pricing.egress_intra_aws_per_gb

    total_cost = retrieval_cost + egress_cost

    thaw = pricing.thaw_hours
    transfer = transfer_time_hours(
        inputs.data_size_gb, inputs.bandwidth_mbps, inputs.link_efficiency
    )
    total_time = thaw + transfer

    if inputs.rto_hours is None:
        mismatch = None
    else:
        mismatch = total_time > inputs.rto_hours

    return RestoreResult(
        retrieval_cost_usd=round(retrieval_cost, 2),
        egress_cost_usd=round(egress_cost, 2),
        total_cost_usd=round(total_cost, 2),
        thaw_time_hours=round(thaw, 2),
        transfer_time_hours=round(transfer, 2),
        total_time_hours=round(total_time, 2),
        rto_hours=inputs.rto_hours,
        rto_mismatch=mismatch,
    )
