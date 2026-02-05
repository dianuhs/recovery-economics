from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List

SCHEMA_VERSION = "1.0"
DEFAULT_WORKLOAD_COLUMN = "workload"

REQUIRED_NUMERIC_COLUMNS = (
    "data_gb",
    "backup_frequency_per_month",
    "retention_months",
    "storage_rate_per_gb_month",
    "restore_gb_per_month",
    "restore_rate_per_gb",
)

_MONEY_QUANT = Decimal("0.01")


def _round_money(value: float) -> float:
    return float(Decimal(str(value)).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP))


def utc_now_iso8601() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class WorkloadConfig:
    workload: str
    data_gb: float
    backup_frequency_per_month: float
    retention_months: float
    storage_rate_per_gb_month: float
    restore_gb_per_month: float
    restore_rate_per_gb: float


@dataclass(frozen=True)
class WorkloadCost:
    workload: str
    data_gb: float
    backup_frequency_per_month: float
    retention_months: float
    storage_rate_per_gb_month: float
    restore_gb_per_month: float
    restore_rate_per_gb: float
    effective_backups_kept: float
    monthly_storage_cost: float
    monthly_restore_cost: float
    total_monthly_resilience_cost: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "workload": self.workload,
            "data_gb": self.data_gb,
            "backup_frequency_per_month": self.backup_frequency_per_month,
            "retention_months": self.retention_months,
            "storage_rate_per_gb_month": self.storage_rate_per_gb_month,
            "restore_gb_per_month": self.restore_gb_per_month,
            "restore_rate_per_gb": self.restore_rate_per_gb,
            "effective_backups_kept": self.effective_backups_kept,
            "monthly_storage_cost": self.monthly_storage_cost,
            "monthly_restore_cost": self.monthly_restore_cost,
            "total_monthly_resilience_cost": self.total_monthly_resilience_cost,
        }


def calculate_workload_cost(config: WorkloadConfig) -> WorkloadCost:
    monthly_storage_cost = (
        config.data_gb
        * config.backup_frequency_per_month
        * config.retention_months
        * config.storage_rate_per_gb_month
    )
    monthly_restore_cost = config.restore_gb_per_month * config.restore_rate_per_gb
    total_monthly_resilience_cost = monthly_storage_cost + monthly_restore_cost

    return WorkloadCost(
        workload=config.workload,
        data_gb=config.data_gb,
        backup_frequency_per_month=config.backup_frequency_per_month,
        retention_months=config.retention_months,
        storage_rate_per_gb_month=config.storage_rate_per_gb_month,
        restore_gb_per_month=config.restore_gb_per_month,
        restore_rate_per_gb=config.restore_rate_per_gb,
        effective_backups_kept=_round_money(
            config.backup_frequency_per_month * config.retention_months
        ),
        monthly_storage_cost=_round_money(monthly_storage_cost),
        monthly_restore_cost=_round_money(monthly_restore_cost),
        total_monthly_resilience_cost=_round_money(total_monthly_resilience_cost),
    )


def summarize_costs(workloads: List[WorkloadCost]) -> Dict[str, Any]:
    total_monthly_storage_cost = _round_money(
        sum(workload.monthly_storage_cost for workload in workloads)
    )
    total_monthly_restore_cost = _round_money(
        sum(workload.monthly_restore_cost for workload in workloads)
    )
    total_monthly_resilience_cost = _round_money(
        sum(workload.total_monthly_resilience_cost for workload in workloads)
    )

    return {
        "total_workloads": len(workloads),
        "total_monthly_storage_cost": total_monthly_storage_cost,
        "total_monthly_restore_cost": total_monthly_restore_cost,
        "total_monthly_resilience_cost": total_monthly_resilience_cost,
    }


def build_report_payload(workloads: List[WorkloadCost], input_file: str) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "generated_at": utc_now_iso8601(),
            "input_file": input_file,
        },
        "summary": summarize_costs(workloads),
        "workloads": [workload.as_dict() for workload in workloads],
    }
