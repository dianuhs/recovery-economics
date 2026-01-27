import pytest
import math

from recovery_economics.model import RestoreInputs, estimate_restore
from recovery_economics.aws_pricing import get_default_pricing


def test_estimate_restore_glacier_intra_aws_basic():
    pricing = get_default_pricing("glacier")
    inputs = RestoreInputs(
        data_size_gb=1000.0,
        bandwidth_mbps=1000.0,
        link_efficiency=0.8,
        restore_destination="intra_aws",
        rto_hours=8.0,
    )
    result = estimate_restore(inputs, pricing)

    # Basic sanity checks: no negative times, totals make sense, cost is finite
    assert result.thaw_time_hours > 0
    assert result.transfer_time_hours > 0
    assert math.isfinite(result.total_time_hours)
    assert result.total_time_hours == pytest.approx(
        result.thaw_time_hours + result.transfer_time_hours, rel=1e-6
    )
    assert result.total_cost_usd >= 0
