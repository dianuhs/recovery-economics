from __future__ import annotations

import copy
import hashlib
import json

import pytest

from recovery_economics.ccac import (
    ILLUSTRATIVE_RUN_PERIOD,
    build_comparison_result,
    build_result,
    demo_result,
    validate_result,
)
from recovery_economics.scenario import ScenarioError, illustrative_scenario


def canonical(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def test_default_and_explicit_1_0_are_identical_to_approved_demo() -> None:
    default = canonical(demo_result())
    explicit = canonical(demo_result("1.0.0"))
    assert default == explicit
    assert hashlib.sha256(
        (json.dumps(demo_result(), indent=2, sort_keys=True) + "\n").encode()
    ).hexdigest() == (
        "adb6c3402619e1fafa71bd927cb35562106859721b214e058a6f87098c6ef7f7"
    )
    assert demo_result()["producer"]["version"] == "0.2.1"


def test_1_1_is_deterministic_diagnostic_only_and_period_truthful() -> None:
    first = demo_result("1.1.0")
    second = demo_result("1.1.0")
    assert first == second
    assert first["contract"] == "ccac/1.1.0"
    assert first["producer"]["version"] == "0.3.0"
    assert first["period"] == ILLUSTRATIVE_RUN_PERIOD
    assert first["opportunities"] == []
    extension = first["extensions"]["recovery_economics"]
    assert extension["organizational_coverage"] == "partial"
    assert extension["total_eligible"] is False
    assert extension["observed_billing"] is False
    assert extension["live_system_access"] is False
    for metric in first["metrics"]:
        assert metric["period"] == {
            "start": "2026-07-01",
            "end": "2026-08-01",
            "timezone": "UTC",
        }
        if metric["unit"] == "currency":
            assert metric["basis"] == "estimated"
    serialized = canonical(first)
    for forbidden in (
        "metric.tech-spend.scope.",
        "canonical_scope_spend",
        "technology_spend_total",
        "remediation_command",
        "verified_savings",
        "realized_savings",
    ):
        assert forbidden not in serialized


def test_equivalent_1_0_and_1_1_are_financially_and_diagnostically_equal() -> None:
    legacy = demo_result("1.0.0")
    bridge = demo_result("1.1.0")
    legacy_values = {metric["id"]: metric["value"] for metric in legacy["metrics"]}
    bridge_values = {metric["id"]: metric["value"] for metric in bridge["metrics"]}
    assert legacy_values == bridge_values
    assert legacy["findings"] == bridge["findings"]
    assert (
        legacy["extensions"]["recovery_economics"]["formulas"]
        == bridge["extensions"]["recovery_economics"]["formulas"]
    )


def test_real_1_1_requires_explicit_period_and_truthful_lineage() -> None:
    source = illustrative_scenario()
    with pytest.raises(ScenarioError, match="period.*required"):
        build_result(source, mode="real", contract_version="1.1.0")
    payload = build_result(
        source,
        mode="real",
        run_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        generated_at="2026-07-22T00:00:00Z",
        contract_version="1.1.0",
        document_period=ILLUSTRATIVE_RUN_PERIOD,
    )
    assert payload["inputs"][0]["access"] == "local_read_only"
    assert payload["inputs"][0]["data_classification"] == "customer_confidential"


@pytest.mark.parametrize("version", ["", "1.0", "1.2.0", "latest"])
def test_unsupported_contract_fails_closed(version: str) -> None:
    with pytest.raises(ScenarioError, match="unsupported CCAC contract version"):
        build_result(
            illustrative_scenario(), mode="illustrative", contract_version=version
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda p: p.update(contract="ccac/1.0.0"), "contract"),
        (lambda p: p.update(document_type="trusted_report"), "document_type"),
        (
            lambda p: p.update(producer={"name": "other", "version": "0.3.0"}),
            "producer",
        ),
        (lambda p: p.update(run_id="not-a-uuid"), "run_id"),
        (lambda p: p.update(mode="live"), "mode"),
        (lambda p: p["period"].update(end="2026-07-01"), "end-exclusive"),
        (lambda p: p["inputs"][0].update(access="provider_api"), "access"),
        (
            lambda p: p["inputs"][0].update(
                data_classification="customer_confidential"
            ),
            "classification",
        ),
        (lambda p: p["inputs"][0].update(content_sha256="0" * 64), "hash"),
        (lambda p: p["evidence"][0].update(content_sha256="0" * 64), "hash"),
        (lambda p: p["evidence"][0].update(source_ids=[]), "source reference"),
        (lambda p: p["metrics"][0].update(evidence_ids=[]), "evidence reference"),
        (
            lambda p: p["metrics"][0].update(input_metric_ids=["metric.unknown"]),
            "metric reference",
        ),
        (
            lambda p: p["findings"][0].update(metric_ids=["metric.unknown"]),
            "metric reference",
        ),
        (lambda p: p["metrics"][0].update(basis="observed"), "recomputed"),
        (lambda p: p["metrics"][-1].update(basis="estimated"), "recomputed"),
        (lambda p: p["metrics"][1].update(currency="EUR"), "recomputed"),
        (lambda p: p["metrics"][1].update(value=-1), "recomputed"),
        (lambda p: p["metrics"][1].update(formula="invoice amount"), "recomputed"),
        (
            lambda p: p["extensions"]["recovery_economics"].update(total_eligible=True),
            "total-ineligible",
        ),
        (
            lambda p: p.update(opportunities=[{"id": "opportunity.fake"}]),
            "opportunities",
        ),
    ],
)
def test_tampered_1_1_output_fails_closed(mutation, message: str) -> None:
    source = illustrative_scenario()
    payload = demo_result("1.1.0")
    mutation(payload)
    with pytest.raises(ScenarioError, match=message):
        validate_result(payload, source, contract_version="1.1.0")


@pytest.mark.parametrize("inventory", ["inputs", "evidence", "metrics", "findings"])
def test_duplicate_output_identity_fails_closed(inventory: str) -> None:
    payload = demo_result("1.1.0")
    payload[inventory].append(copy.deepcopy(payload[inventory][0]))
    with pytest.raises(ScenarioError, match="identities must be unique"):
        validate_result(payload, illustrative_scenario(), contract_version="1.1.0")


@pytest.mark.parametrize("value", [None, "", "NaN", "Infinity", -1, True])
def test_invalid_1_1_financial_input_fails_closed(value: object) -> None:
    source = illustrative_scenario()
    source["risk"]["outage_impact_per_hour"] = value
    with pytest.raises(ScenarioError):
        build_result(source, mode="illustrative", contract_version="1.1.0")


def test_comparison_1_1_is_estimated_and_not_savings() -> None:
    baseline = illustrative_scenario()
    proposed = copy.deepcopy(baseline)
    proposed["scenario_id"] = "proposed"
    proposed["backup"]["frequency_hours"] = 1
    payload = build_comparison_result(
        baseline,
        proposed,
        mode="real",
        run_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        generated_at="2026-07-22T00:00:00Z",
        contract_version="1.1.0",
        document_period=ILLUSTRATIVE_RUN_PERIOD,
    )
    assert all(metric["basis"] == "estimated" for metric in payload["metrics"])
    assert payload["opportunities"] == []
    assert (
        "verified savings"
        in payload["extensions"]["recovery_economics"]["accounting_boundary"]
    )


@pytest.mark.parametrize(
    ("variant", "expected_status"),
    [
        ("missing", "missing"),
        ("stale", "stale"),
        ("failed", "fresh"),
        ("partial", "fresh"),
    ],
)
def test_non_substantiating_restore_evidence_stays_truthful(
    variant: str, expected_status: str
) -> None:
    source = illustrative_scenario()
    if variant == "missing":
        del source["restore_test"]
    elif variant == "stale":
        source["restore_test"]["tested_at"] = "2025-01-01T00:00:00Z"
        source["restore_test"]["result"] = "passed"
    else:
        source["restore_test"]["result"] = variant
    payload = build_result(
        source,
        mode="illustrative",
        run_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        generated_at="2026-07-22T00:00:00Z",
        contract_version="1.1.0",
        document_period=ILLUSTRATIVE_RUN_PERIOD,
    )
    extension = payload["extensions"]["recovery_economics"]
    assert extension["restore_test_freshness"]["status"] == expected_status
    assert any("not substantiated" in item["title"] for item in payload["findings"])


def test_future_restore_evidence_fails_closed_in_1_1() -> None:
    source = illustrative_scenario()
    source["restore_test"]["tested_at"] = "2026-07-23T00:00:00Z"
    with pytest.raises(ScenarioError, match="cannot be later"):
        build_result(
            source,
            mode="illustrative",
            generated_at="2026-07-22T00:00:00Z",
            contract_version="1.1.0",
            document_period=ILLUSTRATIVE_RUN_PERIOD,
        )
