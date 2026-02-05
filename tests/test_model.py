from recovery_economics.model import WorkloadConfig, calculate_workload_cost, summarize_costs


def test_calculate_workload_cost_math() -> None:
    config = WorkloadConfig(
        workload="orders-api",
        data_gb=500.0,
        backup_frequency_per_month=30.0,
        retention_months=3.0,
        storage_rate_per_gb_month=0.02,
        restore_gb_per_month=50.0,
        restore_rate_per_gb=0.05,
    )

    workload = calculate_workload_cost(config)

    assert workload.monthly_storage_cost == 900.0
    assert workload.monthly_restore_cost == 2.5
    assert workload.total_monthly_resilience_cost == 902.5


def test_summarize_costs() -> None:
    workloads = [
        calculate_workload_cost(
            WorkloadConfig(
                workload="a",
                data_gb=100.0,
                backup_frequency_per_month=4.0,
                retention_months=3.0,
                storage_rate_per_gb_month=0.02,
                restore_gb_per_month=10.0,
                restore_rate_per_gb=0.05,
            )
        ),
        calculate_workload_cost(
            WorkloadConfig(
                workload="b",
                data_gb=250.0,
                backup_frequency_per_month=30.0,
                retention_months=1.0,
                storage_rate_per_gb_month=0.01,
                restore_gb_per_month=50.0,
                restore_rate_per_gb=0.02,
            )
        ),
    ]

    summary = summarize_costs(workloads)

    assert summary == {
        "total_workloads": 2,
        "total_monthly_storage_cost": 99.0,
        "total_monthly_restore_cost": 1.5,
        "total_monthly_resilience_cost": 100.5,
    }
