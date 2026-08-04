"""Versioned resilience scenario model with explicit estimate semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Mapping

SCENARIO_VERSION = "recovery-economics/2.0"
MONEY = Decimal("0.01")


class ScenarioError(ValueError):
    """Raised when a scenario is incomplete or internally inconsistent."""


def decimal(
    value: Any,
    field: str,
    *,
    minimum: Decimal = Decimal("0"),
    maximum: Decimal | None = None,
) -> Decimal:
    if value is None or value == "" or isinstance(value, bool):
        raise ScenarioError(f"{field} is required and must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ScenarioError(f"{field} must be numeric") from exc
    if (
        not parsed.is_finite()
        or parsed < minimum
        or (maximum is not None and parsed > maximum)
    ):
        bounds = (
            f"between {minimum} and {maximum}"
            if maximum is not None
            else f">= {minimum}"
        )
        raise ScenarioError(f"{field} must be finite and {bounds}")
    return parsed


def text(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ScenarioError(f"{field} is required")
    return result


def money(value: Decimal) -> float:
    return float(value.quantize(MONEY, rounding=ROUND_HALF_UP))


def number(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _section(source: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = source.get(name)
    if not isinstance(value, Mapping):
        raise ScenarioError(f"{name} must be an object")
    return value


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    workload_id: str
    workload_name: str
    criticality: str
    currency: str
    rto_target_hours: Decimal
    rpo_target_hours: Decimal
    modeled_rto_hours: Decimal
    modeled_rpo_hours: Decimal
    rto_met: bool
    rpo_met: bool
    effective_stored_gb: Decimal
    monthly_storage_cost: Decimal
    monthly_backup_request_cost: Decimal
    monthly_design_cost: Decimal
    retrieval_cost: Decimal
    restore_compute_cost: Decimal
    egress_cost: Decimal
    failover_cost: Decimal
    failback_cost: Decimal
    recovery_event_cost: Decimal
    expected_monthly_recovery_cost: Decimal
    outage_impact_per_event: Decimal
    expected_monthly_outage_exposure: Decimal
    expected_monthly_economic_exposure: Decimal
    sensitivity_low: Decimal
    sensitivity_high: Decimal
    restore_test: dict[str, Any] | None
    formulas: dict[str, str]
    assumptions: dict[str, Any]


def calculate_scenario(source: Mapping[str, Any]) -> ScenarioResult:
    if source.get("schema_version") != SCENARIO_VERSION:
        raise ScenarioError(f"schema_version must be {SCENARIO_VERSION}")
    scenario_id = text(source.get("scenario_id"), "scenario_id")
    currency = text(source.get("currency"), "currency").upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ScenarioError("currency must be a three-letter ISO code")
    workload = _section(source, "workload")
    backup = _section(source, "backup")
    recovery = _section(source, "recovery")
    risk = _section(source, "risk")

    workload_id = text(workload.get("id"), "workload.id")
    workload_name = text(workload.get("name"), "workload.name")
    criticality = text(workload.get("criticality"), "workload.criticality").lower()
    if criticality not in {"low", "medium", "high", "critical"}:
        raise ScenarioError(
            "workload.criticality must be low, medium, high, or critical"
        )
    data_gb = decimal(
        workload.get("data_gb"), "workload.data_gb", minimum=Decimal("0.0001")
    )
    rto_target = decimal(
        workload.get("rto_target_hours"),
        "workload.rto_target_hours",
        minimum=Decimal("0.0001"),
    )
    rpo_target = decimal(
        workload.get("rpo_target_hours"),
        "workload.rpo_target_hours",
        minimum=Decimal("0.0001"),
    )

    frequency_hours = decimal(
        backup.get("frequency_hours"),
        "backup.frequency_hours",
        minimum=Decimal("0.0001"),
    )
    retention_days = decimal(
        backup.get("retention_days"), "backup.retention_days", minimum=Decimal("1")
    )
    full_interval = decimal(
        backup.get("full_backup_interval_days"),
        "backup.full_backup_interval_days",
        minimum=Decimal("1"),
    )
    daily_change_pct = decimal(
        backup.get("daily_change_percent"),
        "backup.daily_change_percent",
        maximum=Decimal("100"),
    )
    compression_ratio = decimal(
        backup.get("compression_ratio"),
        "backup.compression_ratio",
        minimum=Decimal("0.0001"),
        maximum=Decimal("1"),
    )
    dedup_ratio = decimal(
        backup.get("deduplication_ratio"),
        "backup.deduplication_ratio",
        minimum=Decimal("0.0001"),
        maximum=Decimal("1"),
    )
    storage_rate = decimal(
        backup.get("storage_rate_per_gb_month"), "backup.storage_rate_per_gb_month"
    )
    request_cost = decimal(
        backup.get("request_cost_per_backup"), "backup.request_cost_per_backup"
    )

    restore_gb = decimal(
        recovery.get("restore_gb"), "recovery.restore_gb", minimum=Decimal("0.0001")
    )
    throughput = decimal(
        recovery.get("restore_throughput_gb_per_hour"),
        "recovery.restore_throughput_gb_per_hour",
        minimum=Decimal("0.0001"),
    )
    retrieval_rate = decimal(
        recovery.get("retrieval_rate_per_gb"), "recovery.retrieval_rate_per_gb"
    )
    compute_hours = decimal(recovery.get("compute_hours"), "recovery.compute_hours")
    compute_rate = decimal(
        recovery.get("compute_rate_per_hour"), "recovery.compute_rate_per_hour"
    )
    egress_gb = decimal(recovery.get("egress_gb"), "recovery.egress_gb")
    egress_rate = decimal(
        recovery.get("egress_rate_per_gb"), "recovery.egress_rate_per_gb"
    )
    failover_cost = decimal(recovery.get("failover_cost"), "recovery.failover_cost")
    failback_cost = decimal(recovery.get("failback_cost"), "recovery.failback_cost")
    orchestration_hours = decimal(
        recovery.get("orchestration_hours"), "recovery.orchestration_hours"
    )

    events_year = decimal(
        risk.get("recovery_events_per_year"), "risk.recovery_events_per_year"
    )
    outage_hour = decimal(
        risk.get("outage_impact_per_hour"), "risk.outage_impact_per_hour"
    )
    uncertainty = decimal(
        risk.get("uncertainty_percent"),
        "risk.uncertainty_percent",
        maximum=Decimal("100"),
    ) / Decimal("100")

    full_copies = (retention_days / full_interval).to_integral_value(
        rounding="ROUND_CEILING"
    )
    incremental_days = max(retention_days - full_copies, Decimal("0"))
    changed_gb = data_gb * daily_change_pct / Decimal("100") * incremental_days
    effective_stored = (
        (data_gb * full_copies + changed_gb) * compression_ratio * dedup_ratio
    )
    backups_month = Decimal("30") * Decimal("24") / frequency_hours
    storage_cost = effective_stored * storage_rate
    backup_request_cost = backups_month * request_cost
    design_cost = storage_cost + backup_request_cost
    modeled_rto = restore_gb / throughput + orchestration_hours + compute_hours
    modeled_rpo = frequency_hours
    retrieval_cost = restore_gb * retrieval_rate
    restore_compute_cost = compute_hours * compute_rate
    egress_cost = egress_gb * egress_rate
    event_cost = (
        retrieval_cost
        + restore_compute_cost
        + egress_cost
        + failover_cost
        + failback_cost
    )
    expected_events_per_month = events_year / Decimal("12")
    expected_recovery = event_cost * expected_events_per_month
    outage_event = modeled_rto * outage_hour
    expected_outage = outage_event * expected_events_per_month
    exposure = design_cost + expected_recovery + expected_outage

    restore_test = source.get("restore_test")
    parsed_test = None
    if restore_test is not None:
        if not isinstance(restore_test, Mapping):
            raise ScenarioError("restore_test must be an object or omitted")
        tested_at = text(restore_test.get("tested_at"), "restore_test.tested_at")
        try:
            datetime.fromisoformat(tested_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ScenarioError("restore_test.tested_at must be RFC3339") from exc
        parsed_test = {
            "tested_at": tested_at,
            "restore_duration_hours": number(
                decimal(
                    restore_test.get("restore_duration_hours"),
                    "restore_test.restore_duration_hours",
                    minimum=Decimal("0.0001"),
                )
            ),
            "recovered_point_age_hours": number(
                decimal(
                    restore_test.get("recovered_point_age_hours"),
                    "restore_test.recovered_point_age_hours",
                    minimum=Decimal("0"),
                )
            ),
            "result": text(restore_test.get("result"), "restore_test.result").lower(),
        }
        if parsed_test["result"] not in {"passed", "failed", "partial"}:
            raise ScenarioError(
                "restore_test.result must be passed, failed, or partial"
            )

    formulas = {
        "effective_stored_gb": "((data_gb * ceil(retention_days / full_backup_interval_days)) + (data_gb * daily_change_percent / 100 * max(retention_days - retained_full_copies, 0))) * compression_ratio * deduplication_ratio",
        "monthly_design_cost": "effective_stored_gb * storage_rate_per_gb_month + (30 * 24 / frequency_hours) * request_cost_per_backup",
        "modeled_rto_hours": "restore_gb / restore_throughput_gb_per_hour + orchestration_hours + compute_hours",
        "recovery_event_cost": "restore_gb * retrieval_rate_per_gb + compute_hours * compute_rate_per_hour + egress_gb * egress_rate_per_gb + failover_cost + failback_cost",
        "expected_monthly_outage_exposure": "modeled_rto_hours * outage_impact_per_hour * recovery_events_per_year / 12",
    }
    assumptions = {
        "full_copies_retained": number(full_copies),
        "monthly_backup_operations": number(backups_month),
        "recovery_events_per_year": number(events_year),
        "expected_events_per_month": number(expected_events_per_month),
        "uncertainty_percent": number(uncertainty * 100),
    }
    return ScenarioResult(
        scenario_id,
        workload_id,
        workload_name,
        criticality,
        currency,
        rto_target,
        rpo_target,
        modeled_rto,
        modeled_rpo,
        modeled_rto <= rto_target,
        modeled_rpo <= rpo_target,
        effective_stored,
        storage_cost,
        backup_request_cost,
        design_cost,
        retrieval_cost,
        restore_compute_cost,
        egress_cost,
        failover_cost,
        failback_cost,
        event_cost,
        expected_recovery,
        outage_event,
        expected_outage,
        exposure,
        exposure * (Decimal("1") - uncertainty),
        exposure * (Decimal("1") + uncertainty),
        parsed_test,
        formulas,
        assumptions,
    )


def illustrative_scenario() -> dict[str, Any]:
    return {
        "schema_version": SCENARIO_VERSION,
        "scenario_id": "illustrative-orders-db",
        "currency": "USD",
        "workload": {
            "id": "orders-db",
            "name": "Illustrative Orders Database",
            "criticality": "critical",
            "data_gb": 5000,
            "rto_target_hours": 2,
            "rpo_target_hours": 1,
        },
        "backup": {
            "frequency_hours": 4,
            "retention_days": 30,
            "full_backup_interval_days": 7,
            "daily_change_percent": 3,
            "compression_ratio": 0.65,
            "deduplication_ratio": 0.7,
            "storage_rate_per_gb_month": 0.023,
            "request_cost_per_backup": 0.01,
        },
        "recovery": {
            "restore_gb": 5000,
            "restore_throughput_gb_per_hour": 1000,
            "retrieval_rate_per_gb": 0.01,
            "compute_hours": 1,
            "compute_rate_per_hour": 4,
            "egress_gb": 0,
            "egress_rate_per_gb": 0.09,
            "failover_cost": 100,
            "failback_cost": 100,
            "orchestration_hours": 0.5,
        },
        "risk": {
            "recovery_events_per_year": 0.2,
            "outage_impact_per_hour": 50000,
            "uncertainty_percent": 25,
        },
        "restore_test": {
            "tested_at": "2026-06-15T12:00:00Z",
            "restore_duration_hours": 5.2,
            "recovered_point_age_hours": 3.8,
            "result": "partial",
        },
    }
