"""CCAC producer for Recovery Economics scenarios."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

from . import __version__
from .scenario import (
    ScenarioError,
    calculate_scenario,
    illustrative_scenario,
    money,
    number,
)

CONTRACTS = {"1.0.0": "ccac/1.0.0", "1.1.0": "ccac/1.1.0"}
CONTRACT = CONTRACTS["1.0.0"]
LEGACY_VERSION = "0.2.1"
ILLUSTRATIVE_RUN_PERIOD = {
    "start": "2026-07-01",
    "end": "2026-07-22",
    "timezone": "UTC",
}


def load_scenario(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
        value = (
            json.loads(raw) if path.suffix.lower() == ".json" else yaml.safe_load(raw)
        )
    except FileNotFoundError as exc:
        raise ScenarioError(f"input file not found: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ScenarioError(f"unable to read scenario: {exc}") from exc
    if not isinstance(value, dict):
        raise ScenarioError("scenario document must be an object")
    return _json_safe(value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _timestamp(value: str | None) -> str:
    if value is None:
        parsed = datetime.now(timezone.utc)
    else:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ScenarioError("generated_at must be RFC3339") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (
        parsed.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:60] or "scenario"


def _metric(
    mid: str,
    name: str,
    value: float,
    unit: str,
    currency: str | None,
    basis: str,
    additivity: str,
    period: dict[str, str],
    dims: dict[str, Any],
    formula: str | None,
    evidence: str,
) -> dict[str, Any]:
    return {
        "id": mid,
        "name": name,
        "value": value,
        "unknown_reason": None,
        "unit": unit,
        "currency": currency,
        "basis": basis,
        "additivity": additivity,
        "period": period,
        "dimensions": dims,
        "formula": formula,
        "input_metric_ids": [],
        "evidence_ids": [evidence],
        "quality_status": "valid",
    }


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        _json_safe(dict(value)),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


def _half_open_period(value: Mapping[str, Any] | None, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ScenarioError(f"{field} is required")
    try:
        start = date.fromisoformat(str(value.get("start")))
        end = date.fromisoformat(str(value.get("end")))
    except ValueError as exc:
        raise ScenarioError(f"{field} must use ISO dates") from exc
    if end <= start or value.get("timezone", "UTC") != "UTC":
        raise ScenarioError(f"{field} must be start-inclusive, end-exclusive, and UTC")
    return {"start": start.isoformat(), "end": end.isoformat(), "timezone": "UTC"}


def _monthly_period(day: date) -> dict[str, str]:
    start = day.replace(day=1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return {"start": start.isoformat(), "end": end.isoformat(), "timezone": "UTC"}


def _observation_period(value: str) -> dict[str, str]:
    try:
        observed_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScenarioError("restore_test.tested_at must be RFC3339") from exc
    if observed_at.tzinfo is None:
        raise ScenarioError("restore_test.tested_at must include a timezone")
    observed_day = observed_at.astimezone(timezone.utc).date()
    return {
        "start": observed_day.isoformat(),
        "end": (observed_day + timedelta(days=1)).isoformat(),
        "timezone": "UTC",
    }


def _build_result(
    source: Mapping[str, Any],
    *,
    mode: str,
    run_id: str | None = None,
    generated_at: str | None = None,
    contract_version: str = "1.0.0",
    document_period: Mapping[str, Any] | None = None,
    legacy_provenance: bool = False,
) -> dict[str, Any]:
    if contract_version not in CONTRACTS:
        raise ScenarioError(
            f"unsupported CCAC contract version: {contract_version!r}; expected 1.0.0 or 1.1.0"
        )
    if mode not in {"illustrative", "real"}:
        raise ScenarioError("mode must be illustrative or real")
    result = calculate_scenario(source)
    try:
        rid = str(uuid.UUID(run_id)) if run_id else str(uuid.uuid4())
    except (ValueError, TypeError) as exc:
        raise ScenarioError("run_id must be a UUID") from exc
    generated = _timestamp(generated_at)
    source_bytes = _canonical(source)
    digest = hashlib.sha256(source_bytes).hexdigest()
    component = _id(result.workload_id)
    source_id = "source.recovery-economics.scenario"
    evidence_id = "evidence.recovery-economics.scenario-input"
    today = datetime.fromisoformat(generated.replace("Z", "+00:00")).date()
    if contract_version == "1.1.0":
        run_period = _half_open_period(
            document_period
            or (ILLUSTRATIVE_RUN_PERIOD if mode == "illustrative" else None),
            "CCAC 1.1 document period",
        )
        metric_period = _monthly_period(date.fromisoformat(run_period["start"]))
    else:
        if document_period is not None:
            raise ScenarioError("document period is supported only for CCAC 1.1")
        metric_period = _monthly_period(today)
        run_period = metric_period
    producer_version = LEGACY_VERSION if legacy_provenance else __version__
    dims = {
        "scope": "resilience_scenario",
        "workload": result.workload_id,
        "criticality": result.criticality,
        "scenario": result.scenario_id,
    }
    prefix = f"metric.resilience.{component}"
    metrics = [
        _metric(
            f"{prefix}.effective-stored-gb",
            "Modeled effective protected storage",
            number(result.effective_stored_gb),
            "GB",
            None,
            "estimated",
            "non_additive",
            metric_period,
            dims,
            result.formulas["effective_stored_gb"],
            evidence_id,
        ),
        _metric(
            f"{prefix}.monthly-design-cost",
            "Modeled monthly resilience design cost",
            money(result.monthly_design_cost),
            "currency",
            result.currency,
            "estimated",
            "additive",
            metric_period,
            dims,
            result.formulas["monthly_design_cost"],
            evidence_id,
        ),
        _metric(
            f"{prefix}.monthly-storage-cost",
            "Modeled monthly protected-storage cost",
            money(result.monthly_storage_cost),
            "currency",
            result.currency,
            "estimated",
            "additive",
            metric_period,
            dims,
            "effective_stored_gb * storage_rate_per_gb_month",
            evidence_id,
        ),
        _metric(
            f"{prefix}.monthly-backup-request-cost",
            "Modeled monthly backup request cost",
            money(result.monthly_backup_request_cost),
            "currency",
            result.currency,
            "estimated",
            "additive",
            metric_period,
            dims,
            "monthly_backup_operations * request_cost_per_backup",
            evidence_id,
        ),
        _metric(
            f"{prefix}.modeled-rto-hours",
            "Modeled recovery time",
            number(result.modeled_rto_hours),
            "hours",
            None,
            "estimated",
            "non_additive",
            metric_period,
            dims,
            result.formulas["modeled_rto_hours"],
            evidence_id,
        ),
        _metric(
            f"{prefix}.modeled-rpo-hours",
            "Modeled recovery point interval",
            number(result.modeled_rpo_hours),
            "hours",
            None,
            "estimated",
            "non_additive",
            metric_period,
            dims,
            "backup.frequency_hours",
            evidence_id,
        ),
        _metric(
            f"{prefix}.recovery-event-cost",
            "Modeled recovery execution cost per event",
            money(result.recovery_event_cost),
            "currency",
            result.currency,
            "estimated",
            "non_additive",
            metric_period,
            dims,
            result.formulas["recovery_event_cost"],
            evidence_id,
        ),
        _metric(
            f"{prefix}.retrieval-cost-per-event",
            "Modeled retrieval cost per recovery event",
            money(result.retrieval_cost),
            "currency",
            result.currency,
            "estimated",
            "non_additive",
            metric_period,
            dims,
            "restore_gb * retrieval_rate_per_gb",
            evidence_id,
        ),
        _metric(
            f"{prefix}.compute-cost-per-event",
            "Modeled compute cost per recovery event",
            money(result.restore_compute_cost),
            "currency",
            result.currency,
            "estimated",
            "non_additive",
            metric_period,
            dims,
            "compute_hours * compute_rate_per_hour",
            evidence_id,
        ),
        _metric(
            f"{prefix}.egress-cost-per-event",
            "Modeled egress cost per recovery event",
            money(result.egress_cost),
            "currency",
            result.currency,
            "estimated",
            "non_additive",
            metric_period,
            dims,
            "egress_gb * egress_rate_per_gb",
            evidence_id,
        ),
        _metric(
            f"{prefix}.failover-cost-per-event",
            "Modeled failover cost per recovery event",
            money(result.failover_cost),
            "currency",
            result.currency,
            "estimated",
            "non_additive",
            metric_period,
            dims,
            "recovery.failover_cost",
            evidence_id,
        ),
        _metric(
            f"{prefix}.failback-cost-per-event",
            "Modeled failback cost per recovery event",
            money(result.failback_cost),
            "currency",
            result.currency,
            "estimated",
            "non_additive",
            metric_period,
            dims,
            "recovery.failback_cost",
            evidence_id,
        ),
        _metric(
            f"{prefix}.expected-monthly-recovery-cost",
            "Frequency-weighted monthly recovery execution cost",
            money(result.expected_monthly_recovery_cost),
            "currency",
            result.currency,
            "estimated",
            "additive",
            metric_period,
            dims,
            "recovery_event_cost * recovery_events_per_year / 12",
            evidence_id,
        ),
        _metric(
            f"{prefix}.expected-monthly-outage-exposure",
            "Frequency-weighted monthly outage exposure",
            money(result.expected_monthly_outage_exposure),
            "currency",
            result.currency,
            "estimated",
            "additive",
            metric_period,
            dims,
            result.formulas["expected_monthly_outage_exposure"],
            evidence_id,
        ),
        _metric(
            f"{prefix}.expected-monthly-economic-exposure",
            "Modeled monthly resilience economic exposure",
            money(result.expected_monthly_economic_exposure),
            "currency",
            result.currency,
            "estimated",
            "additive",
            metric_period,
            dims,
            "monthly_design_cost + expected_monthly_recovery_cost + expected_monthly_outage_exposure",
            evidence_id,
        ),
    ]
    evidence = [
        {
            "id": evidence_id,
            "kind": "formula",
            "source_ids": [source_id],
            "description": "Versioned resilience scenario assumptions and transparent model formulas.",
            "locator": "canonical-json:scenario",
            "observed_at": generated,
            "content_sha256": digest,
        }
    ]
    restore_freshness = {
        "status": "missing",
        "age_days": None,
        "freshness_threshold_days": 90,
    }
    observed_metric_period = None
    test_evidence_id = "evidence.recovery-economics.restore-test"
    if result.restore_test is not None:
        tested_at = datetime.fromisoformat(
            result.restore_test["tested_at"].replace("Z", "+00:00")
        )
        observed_metric_period = _observation_period(result.restore_test["tested_at"])
        age_days = (
            datetime.fromisoformat(generated.replace("Z", "+00:00")) - tested_at
        ).days
        if age_days < 0:
            raise ScenarioError(
                "restore_test.tested_at cannot be later than generated_at"
            )
        restore_freshness = {
            "status": "fresh" if age_days <= 90 else "stale",
            "age_days": age_days,
            "freshness_threshold_days": 90,
        }
        evidence.append(
            {
                "id": test_evidence_id,
                "kind": "restore_test",
                "source_ids": [source_id],
                "description": f"Supplied restore-test result: {result.restore_test['result']}.",
                "locator": "canonical-json:scenario.restore_test",
                "observed_at": result.restore_test["tested_at"],
                "content_sha256": digest,
            }
        )
        metrics.extend(
            [
                _metric(
                    f"{prefix}.tested-restore-duration-hours",
                    "Observed restore-test duration",
                    result.restore_test["restore_duration_hours"],
                    "hours",
                    None,
                    "observed",
                    "non_additive",
                    (
                        observed_metric_period
                        if contract_version == "1.1.0"
                        else metric_period
                    ),
                    dims,
                    None,
                    test_evidence_id,
                ),
                _metric(
                    f"{prefix}.tested-recovered-point-age-hours",
                    "Observed recovered point age in restore test",
                    result.restore_test["recovered_point_age_hours"],
                    "hours",
                    None,
                    "observed",
                    "non_additive",
                    (
                        observed_metric_period
                        if contract_version == "1.1.0"
                        else metric_period
                    ),
                    dims,
                    None,
                    test_evidence_id,
                ),
            ]
        )
    findings = []
    if not result.rto_met:
        findings.append(
            {
                "id": f"finding.resilience-gap.{component}.rto",
                "finding_type": "resilience_gap",
                "title": f"Modeled RTO exceeds target for {result.workload_name}",
                "description": f"Modeled recovery time is {number(result.modeled_rto_hours)} hours versus a {number(result.rto_target_hours)} hour target. This is a scenario estimate, not proof of recoverability.",
                "severity": (
                    "high" if result.criticality in {"high", "critical"} else "medium"
                ),
                "status": "open",
                "metric_ids": [f"{prefix}.modeled-rto-hours"],
                "evidence_ids": [evidence_id],
                "first_observed_at": generated,
                "last_observed_at": generated,
            }
        )
    if not result.rpo_met:
        findings.append(
            {
                "id": f"finding.resilience-gap.{component}.rpo",
                "finding_type": "resilience_gap",
                "title": f"Modeled RPO exceeds target for {result.workload_name}",
                "description": f"Backup interval is {number(result.modeled_rpo_hours)} hours versus a {number(result.rpo_target_hours)} hour target.",
                "severity": (
                    "high" if result.criticality in {"high", "critical"} else "medium"
                ),
                "status": "open",
                "metric_ids": [f"{prefix}.modeled-rpo-hours"],
                "evidence_ids": [evidence_id],
                "first_observed_at": generated,
                "last_observed_at": generated,
            }
        )
    test_substantiates = (
        result.restore_test is not None
        and result.restore_test["result"] == "passed"
        and restore_freshness["status"] == "fresh"
    )
    if not test_substantiates:
        findings.append(
            {
                "id": f"finding.resilience-gap.{component}.restore-evidence",
                "finding_type": "resilience_gap",
                "title": f"Recoverability is not substantiated for {result.workload_name}",
                "description": "No fresh passing restore-test evidence was supplied. Modeled RTO/RPO values must not be presented as demonstrated recovery capability.",
                "severity": "high" if result.criticality == "critical" else "medium",
                "status": "open",
                "metric_ids": [
                    f"{prefix}.modeled-rto-hours",
                    f"{prefix}.modeled-rpo-hours",
                ],
                "evidence_ids": (
                    [test_evidence_id]
                    if result.restore_test is not None
                    else [evidence_id]
                ),
                "first_observed_at": generated,
                "last_observed_at": generated,
            }
        )
    if result.restore_test is not None and result.restore_test[
        "restore_duration_hours"
    ] > number(result.rto_target_hours):
        findings.append(
            {
                "id": f"finding.resilience-gap.{component}.tested-rto",
                "finding_type": "resilience_gap",
                "title": f"Restore test missed the RTO target for {result.workload_name}",
                "description": "Observed restore-test duration exceeded the declared RTO target.",
                "severity": "critical" if result.criticality == "critical" else "high",
                "status": "open",
                "metric_ids": [f"{prefix}.tested-restore-duration-hours"],
                "evidence_ids": [test_evidence_id],
                "first_observed_at": generated,
                "last_observed_at": generated,
            }
        )
    if result.restore_test is not None and result.restore_test[
        "recovered_point_age_hours"
    ] > number(result.rpo_target_hours):
        findings.append(
            {
                "id": f"finding.resilience-gap.{component}.tested-rpo",
                "finding_type": "resilience_gap",
                "title": f"Restore test missed the RPO target for {result.workload_name}",
                "description": "Observed recovered point age exceeded the declared RPO target.",
                "severity": "critical" if result.criticality == "critical" else "high",
                "status": "open",
                "metric_ids": [f"{prefix}.tested-recovered-point-age-hours"],
                "evidence_ids": [test_evidence_id],
                "first_observed_at": generated,
                "last_observed_at": generated,
            }
        )
    extension = {
        "rto_target_met": result.rto_met,
        "rpo_target_met": result.rpo_met,
        "restore_test": result.restore_test,
        "restore_test_freshness": restore_freshness,
        "sensitivity": {
            "low": money(result.sensitivity_low),
            "expected": money(result.expected_monthly_economic_exposure),
            "high": money(result.sensitivity_high),
            "currency": result.currency,
        },
        "assumptions": result.assumptions,
        "formulas": result.formulas,
        "accounting_boundary": "Modeled scenario values are excluded from observed technology spend totals.",
    }
    if contract_version == "1.1.0":
        extension.update(
            {
                "organizational_coverage": "partial",
                "total_eligible": False,
                "document_period_role": "pipeline_analysis_window",
                "modeled_metric_period_role": "monthly_modeled_scenario_horizon",
                "modeled_metric_period": metric_period,
                "observed_restore_metric_period_role": "restore_test_observation_day",
                "observed_restore_metric_period": observed_metric_period,
                "observed_billing": False,
                "live_system_access": False,
            }
        )
    return {
        "contract": CONTRACTS[contract_version],
        "document_type": "tool_result",
        "producer": {"name": "recovery-economics", "version": producer_version},
        "run_id": rid,
        "generated_at": generated,
        "mode": mode,
        "period": run_period,
        "inputs": [
            {
                "id": source_id,
                "source_type": "resilience_scenario",
                "source_version": str(source["schema_version"]),
                "adapter_version": producer_version,
                "content_sha256": digest,
                "access": (
                    "illustrative_fixture"
                    if mode == "illustrative"
                    else "local_read_only"
                ),
                "data_classification": (
                    "public_illustrative"
                    if mode == "illustrative"
                    else "customer_confidential"
                ),
                "lossy_mapping": False,
                "mapping_notes": [
                    "Scenario assumptions are modeled inputs, not invoice facts."
                ],
            }
        ],
        "quality": {"status": "valid", "issues": []},
        "metrics": metrics,
        "findings": findings,
        "opportunities": [],
        "evidence": evidence,
        "extensions": {"recovery_economics": extension},
    }


def _unique_ids(items: Any, field: str) -> set[str]:
    if not isinstance(items, list):
        raise ScenarioError(f"{field} must be an array")
    identities = [
        str(item.get("id") or "") for item in items if isinstance(item, Mapping)
    ]
    if len(identities) != len(items) or any(not item for item in identities):
        raise ScenarioError(f"{field} identities are required")
    if len(identities) != len(set(identities)):
        raise ScenarioError(f"{field} identities must be unique")
    return set(identities)


def validate_result(
    payload: Mapping[str, Any],
    source: Mapping[str, Any],
    *,
    contract_version: str,
    legacy_provenance: bool = False,
) -> None:
    if contract_version not in CONTRACTS:
        raise ScenarioError(f"unsupported CCAC contract version: {contract_version!r}")
    if payload.get("contract") != CONTRACTS[contract_version]:
        raise ScenarioError(
            "CCAC output contract does not match the requested contract"
        )
    if payload.get("document_type") != "tool_result":
        raise ScenarioError("CCAC output document_type must be tool_result")
    expected_version = LEGACY_VERSION if legacy_provenance else __version__
    if payload.get("producer") != {
        "name": "recovery-economics",
        "version": expected_version,
    }:
        raise ScenarioError("CCAC output producer declaration is invalid")
    mode = payload.get("mode")
    if mode not in {"illustrative", "real"}:
        raise ScenarioError("CCAC output mode must be illustrative or real")
    try:
        uuid.UUID(str(payload.get("run_id")))
    except (ValueError, TypeError) as exc:
        raise ScenarioError("CCAC output run_id must be a UUID") from exc
    _half_open_period(payload.get("period"), "CCAC output period")
    source_ids = _unique_ids(payload.get("inputs"), "source")
    evidence_ids = _unique_ids(payload.get("evidence"), "evidence")
    metric_ids = _unique_ids(payload.get("metrics"), "metric")
    finding_ids = _unique_ids(payload.get("findings"), "finding")
    if len(finding_ids) != len(payload.get("findings", [])):
        raise ScenarioError("finding inventory is invalid")
    expected_access = (
        ("illustrative_fixture", "public_illustrative")
        if mode == "illustrative"
        else ("local_read_only", "customer_confidential")
    )
    source_digest = hashlib.sha256(_canonical(source)).hexdigest()
    for item in payload["inputs"]:
        if (item.get("access"), item.get("data_classification")) != expected_access:
            raise ScenarioError(
                "source access and classification contradict output mode"
            )
        if item.get("content_sha256") != source_digest:
            raise ScenarioError(
                "source content hash does not match normalized scenario"
            )
    for item in payload["evidence"]:
        refs = item.get("source_ids")
        if (
            not isinstance(refs, list)
            or not refs
            or any(ref not in source_ids for ref in refs)
        ):
            raise ScenarioError(
                "evidence contains a missing or unknown source reference"
            )
        if item.get("content_sha256") != source_digest:
            raise ScenarioError(
                "evidence content hash does not match normalized scenario"
            )
    for item in payload["metrics"]:
        refs = item.get("evidence_ids")
        inputs = item.get("input_metric_ids", [])
        if (
            not isinstance(refs, list)
            or not refs
            or any(ref not in evidence_ids for ref in refs)
        ):
            raise ScenarioError(
                "metric contains a missing or unknown evidence reference"
            )
        if not isinstance(inputs, list) or any(ref not in metric_ids for ref in inputs):
            raise ScenarioError("metric contains an unknown metric reference")
    if contract_version == "1.1.0":
        modeled_period = _monthly_period(date.fromisoformat(payload["period"]["start"]))
        restore_test = source.get("restore_test")
        observed_period = (
            _observation_period(str(restore_test.get("tested_at")))
            if isinstance(restore_test, Mapping)
            else None
        )
        observed_metric_ids = {
            metric_id
            for metric_id in metric_ids
            if metric_id.endswith(".tested-restore-duration-hours")
            or metric_id.endswith(".tested-recovered-point-age-hours")
        }
        if observed_period is None and observed_metric_ids:
            raise ScenarioError("restore-test metrics require restore-test evidence")
        for item in payload["metrics"]:
            is_observed_restore = item["id"] in observed_metric_ids
            expected_period = observed_period if is_observed_restore else modeled_period
            expected_basis = "observed" if is_observed_restore else "estimated"
            if item.get("period") != expected_period:
                raise ScenarioError(
                    "metric period contradicts its modeled or observed meaning"
                )
            if item.get("basis") != expected_basis:
                raise ScenarioError(
                    "metric basis contradicts its modeled or observed meaning"
                )
    for item in payload["findings"]:
        if any(ref not in metric_ids for ref in item.get("metric_ids", [])):
            raise ScenarioError("finding contains an unknown metric reference")
        if any(ref not in evidence_ids for ref in item.get("evidence_ids", [])):
            raise ScenarioError("finding contains an unknown evidence reference")
    serialized = json.dumps(payload, sort_keys=True)
    if any(
        forbidden in serialized
        for forbidden in (
            "metric.tech-spend.scope.",
            "canonical_scope_spend",
            "technology_spend_total",
        )
    ):
        raise ScenarioError(
            "Recovery Economics must not emit canonical technology spend"
        )
    if payload.get("opportunities") != []:
        raise ScenarioError(
            "Recovery Economics must not emit optimization opportunities"
        )
    extension = payload.get("extensions", {}).get("recovery_economics", {})
    if contract_version == "1.1.0" and (
        extension.get("organizational_coverage") != "partial"
        or extension.get("total_eligible") is not False
    ):
        raise ScenarioError(
            "Recovery Economics must remain partial and total-ineligible"
        )
    document_period = payload.get("period") if contract_version == "1.1.0" else None
    expected = _build_result(
        source,
        mode=str(mode),
        run_id=str(payload["run_id"]),
        generated_at=str(payload.get("generated_at")),
        contract_version=contract_version,
        document_period=document_period,
        legacy_provenance=legacy_provenance,
    )
    if payload != expected:
        raise ScenarioError(
            "CCAC output contradicts independently recomputed scenario results"
        )


def build_result(
    source: Mapping[str, Any],
    *,
    mode: str,
    run_id: str | None = None,
    generated_at: str | None = None,
    contract_version: str = "1.0.0",
    document_period: Mapping[str, Any] | None = None,
    legacy_provenance: bool = False,
) -> dict[str, Any]:
    payload = _build_result(
        source,
        mode=mode,
        run_id=run_id,
        generated_at=generated_at,
        contract_version=contract_version,
        document_period=document_period,
        legacy_provenance=legacy_provenance,
    )
    validate_result(
        payload,
        source,
        contract_version=contract_version,
        legacy_provenance=legacy_provenance,
    )
    return payload


def demo_result(contract_version: str = "1.0.0") -> dict[str, Any]:
    return build_result(
        illustrative_scenario(),
        mode="illustrative",
        run_id="123e4567-e89b-12d3-a456-426614174020",
        generated_at="2026-08-04T12:10:00Z",
        contract_version=contract_version,
        legacy_provenance=contract_version == "1.0.0",
    )


def build_comparison_result(
    baseline_source: Mapping[str, Any],
    proposed_source: Mapping[str, Any],
    *,
    mode: str,
    run_id: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    baseline = calculate_scenario(baseline_source)
    proposed = calculate_scenario(proposed_source)
    if baseline.workload_id != proposed.workload_id:
        raise ScenarioError("baseline and proposed workload.id must match")
    if baseline.currency != proposed.currency:
        raise ScenarioError("baseline and proposed currency must match")
    if mode not in {"illustrative", "real"}:
        raise ScenarioError("mode must be illustrative or real")
    try:
        rid = str(uuid.UUID(run_id)) if run_id else str(uuid.uuid4())
    except (ValueError, TypeError) as exc:
        raise ScenarioError("run_id must be a UUID") from exc
    generated = _timestamp(generated_at)
    today = datetime.fromisoformat(generated.replace("Z", "+00:00")).date()
    period = _monthly_period(today)
    sources = []
    evidence = []
    for label, raw in (("baseline", baseline_source), ("proposed", proposed_source)):
        digest = hashlib.sha256(
            json.dumps(
                dict(raw), sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
        sid = f"source.recovery-economics.{label}-scenario"
        eid = f"evidence.recovery-economics.{label}-scenario"
        sources.append(
            {
                "id": sid,
                "source_type": "resilience_scenario",
                "source_version": str(raw["schema_version"]),
                "adapter_version": __version__,
                "content_sha256": digest,
                "access": (
                    "illustrative_fixture"
                    if mode == "illustrative"
                    else "local_read_only"
                ),
                "data_classification": (
                    "public_illustrative"
                    if mode == "illustrative"
                    else "customer_confidential"
                ),
                "lossy_mapping": False,
                "mapping_notes": [
                    f"{label.title()} strategy assumptions are modeled inputs, not invoice facts."
                ],
            }
        )
        evidence.append(
            {
                "id": eid,
                "kind": "formula",
                "source_ids": [sid],
                "description": f"{label.title()} resilience scenario assumptions.",
                "locator": f"canonical-json:{label}",
                "observed_at": generated,
                "content_sha256": digest,
            }
        )
    dims = {
        "scope": "resilience_scenario_comparison",
        "workload": baseline.workload_id,
        "baseline": baseline.scenario_id,
        "proposed": proposed.scenario_id,
    }
    component = _id(baseline.workload_id)
    baseline_id = f"metric.resilience-comparison.{component}.baseline-exposure"
    proposed_id = f"metric.resilience-comparison.{component}.proposed-exposure"
    delta_id = f"metric.resilience-comparison.{component}.proposed-minus-baseline"
    metrics = [
        _metric(
            baseline_id,
            "Baseline modeled monthly economic exposure",
            money(baseline.expected_monthly_economic_exposure),
            "currency",
            baseline.currency,
            "estimated",
            "non_additive",
            period,
            dims,
            "baseline monthly design cost + expected recovery cost + expected outage exposure",
            "evidence.recovery-economics.baseline-scenario",
        ),
        _metric(
            proposed_id,
            "Proposed modeled monthly economic exposure",
            money(proposed.expected_monthly_economic_exposure),
            "currency",
            proposed.currency,
            "estimated",
            "non_additive",
            period,
            dims,
            "proposed monthly design cost + expected recovery cost + expected outage exposure",
            "evidence.recovery-economics.proposed-scenario",
        ),
        _metric(
            delta_id,
            "Proposed minus baseline modeled monthly economic exposure",
            money(
                proposed.expected_monthly_economic_exposure
                - baseline.expected_monthly_economic_exposure
            ),
            "currency",
            baseline.currency,
            "estimated",
            "non_additive",
            period,
            dims,
            "proposed exposure - baseline exposure",
            "evidence.recovery-economics.proposed-scenario",
        ),
    ]
    metrics[2]["input_metric_ids"] = [baseline_id, proposed_id]
    findings = []
    if proposed.rto_met is False and baseline.rto_met is True:
        findings.append(
            {
                "id": f"finding.resilience-gap.{component}.proposed-rto-regression",
                "finding_type": "resilience_gap",
                "title": f"Proposed strategy introduces an RTO gap for {baseline.workload_name}",
                "description": "The proposed strategy reduces target coverage relative to the baseline; cost delta must not be presented without this tradeoff.",
                "severity": "high",
                "status": "open",
                "metric_ids": [delta_id],
                "evidence_ids": [
                    "evidence.recovery-economics.baseline-scenario",
                    "evidence.recovery-economics.proposed-scenario",
                ],
                "first_observed_at": generated,
                "last_observed_at": generated,
            }
        )
    if proposed.rpo_met is False and baseline.rpo_met is True:
        findings.append(
            {
                "id": f"finding.resilience-gap.{component}.proposed-rpo-regression",
                "finding_type": "resilience_gap",
                "title": f"Proposed strategy introduces an RPO gap for {baseline.workload_name}",
                "description": "The proposed strategy reduces target coverage relative to the baseline; cost delta must not be presented without this tradeoff.",
                "severity": "high",
                "status": "open",
                "metric_ids": [delta_id],
                "evidence_ids": [
                    "evidence.recovery-economics.baseline-scenario",
                    "evidence.recovery-economics.proposed-scenario",
                ],
                "first_observed_at": generated,
                "last_observed_at": generated,
            }
        )
    return {
        "contract": CONTRACT,
        "document_type": "tool_result",
        "producer": {"name": "recovery-economics", "version": __version__},
        "run_id": rid,
        "generated_at": generated,
        "mode": mode,
        "period": period,
        "inputs": sources,
        "quality": {"status": "valid", "issues": []},
        "metrics": metrics,
        "findings": findings,
        "opportunities": [],
        "evidence": evidence,
        "extensions": {
            "recovery_economics": {
                "comparison": {
                    "baseline": {
                        "scenario_id": baseline.scenario_id,
                        "rto_target_met": baseline.rto_met,
                        "rpo_target_met": baseline.rpo_met,
                        "monthly_design_cost": money(baseline.monthly_design_cost),
                        "expected_monthly_exposure": money(
                            baseline.expected_monthly_economic_exposure
                        ),
                    },
                    "proposed": {
                        "scenario_id": proposed.scenario_id,
                        "rto_target_met": proposed.rto_met,
                        "rpo_target_met": proposed.rpo_met,
                        "monthly_design_cost": money(proposed.monthly_design_cost),
                        "expected_monthly_exposure": money(
                            proposed.expected_monthly_economic_exposure
                        ),
                    },
                    "delta": money(
                        proposed.expected_monthly_economic_exposure
                        - baseline.expected_monthly_economic_exposure
                    ),
                },
                "accounting_boundary": "Comparison deltas are modeled estimates and excluded from observed technology spend and verified savings.",
            }
        },
    }
