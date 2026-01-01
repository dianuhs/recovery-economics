from recovery_economics.aws_pricing import AwsRestorePricing
from recovery_economics.model import (
    RestoreInputs,
    estimate_restore,
    transfer_time_hours,
)


def test_transfer_time_increases_with_size():
    t1 = transfer_time_hours(data_size_gb=100, bandwidth_mbps=1000, efficiency=0.7)
    t2 = transfer_time_hours(data_size_gb=200, bandwidth_mbps=1000, efficiency=0.7)
    assert t2 > t1


def test_transfer_time_decreases_with_bandwidth():
    slow = transfer_time_hours(data_size_gb=1000, bandwidth_mbps=100, efficiency=0.7)
    fast = transfer_time_hours(data_size_gb=1000, bandwidth_mbps=1000, efficiency=0.7)
    assert fast < slow


def test_estimate_restore_cost_components_internet():
    pricing = AwsRestorePricing(
        retrieval_per_gb=0.02,
        egress_to_internet_per_gb=0.09,
        egress_intra_aws_per_gb=0.0,
        thaw_hours=12.0,
    )
    inputs = RestoreInputs(
        data_size_gb=5000,
        bandwidth_mbps=1000,
        link_efficiency=0.7,
        restore_destination="internet",
        rto_hours=24.0,
    )
    result = estimate_restore(inputs, pricing)
    assert result.total_cost_usd == 550.0
    assert result.thaw_time_hours == 12.0
    assert result.rto_mismatch is True


def test_estimate_restore_intra_aws_has_lower_egress():
    pricing = AwsRestorePricing(
        retrieval_per_gb=0.02,
        egress_to_internet_per_gb=0.09,
        egress_intra_aws_per_gb=0.0,
        thaw_hours=12.0,
    )
    internet_inputs = RestoreInputs(
        data_size_gb=100,
        bandwidth_mbps=1000,
        link_efficiency=0.7,
        restore_destination="internet",
        rto_hours=None,
    )
    intra_inputs = RestoreInputs(
        data_size_gb=100,
        bandwidth_mbps=1000,
        link_efficiency=0.7,
        restore_destination="intra_aws",
        rto_hours=None,
    )
    internet = estimate_restore(internet_inputs, pricing)
    intra = estimate_restore(intra_inputs, pricing)
    assert intra.egress_cost_usd < internet.egress_cost_usd
