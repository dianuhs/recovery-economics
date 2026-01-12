from recovery_economics.aws_pricing import AwsRestorePricing
from recovery_economics.model import RestoreInputs, estimate_restore


def test_estimate_restore_cost_components_internet():
    pricing = AwsRestorePricing(
        retrieval_per_gb=0.02,
        egress_to_internet_per_gb=0.09,
        egress_intra_aws_per_gb=0.0,
        thaw_hours=12.0,
        storage_per_gb_month=0.00099,  # Deep Archive example
    )

    inputs = RestoreInputs(
        data_size_gb=1000,
        bandwidth_mbps=1000,
        link_efficiency=1.0,
        restore_destination="internet",
        rto_hours=None,
    )

    result = estimate_restore(inputs, pricing)

    assert result.retrieval_cost_usd == 20.0
    assert result.egress_cost_usd == 90.0
    assert result.total_cost_usd == 110.0


def test_estimate_restore_intra_aws_has_lower_egress():
    pricing = AwsRestorePricing(
        retrieval_per_gb=0.02,
        egress_to_internet_per_gb=0.09,
        egress_intra_aws_per_gb=0.0,
        thaw_hours=12.0,
        storage_per_gb_month=0.00099,
    )

    inputs = RestoreInputs(
        data_size_gb=1000,
        bandwidth_mbps=1000,
        link_efficiency=1.0,
        restore_destination="intra_aws",
        rto_hours=None,
    )

    result = estimate_restore(inputs, pricing)

    assert result.egress_cost_usd == 0.0
    assert result.total_cost_usd == 20.0
