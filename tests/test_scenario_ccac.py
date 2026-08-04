from __future__ import annotations

import copy
import json
from io import StringIO

import pytest

from recovery_economics.ccac import build_comparison_result, demo_result
from recovery_economics.cli import build_parser, run_ccac
from recovery_economics.scenario import (
    ScenarioError,
    calculate_scenario,
    illustrative_scenario,
)


def test_scenario_math_and_accounting_boundaries():
    result = calculate_scenario(illustrative_scenario())
    assert result.modeled_rto_hours == pytest.approx(6.5)
    assert result.modeled_rpo_hours == 4
    assert result.rto_met is False
    assert result.rpo_met is False
    assert result.monthly_design_cost > 0
    assert result.expected_monthly_outage_exposure > result.monthly_design_cost


def test_demo_is_deterministic_and_never_emits_opportunities_or_verified_values():
    first = demo_result()
    second = demo_result()
    assert first == second
    assert first["contract"] == "ccac/1.0.0"
    assert first["mode"] == "illustrative"
    assert first["quality"]["status"] == "valid"
    assert first["opportunities"] == []
    assert all(metric["basis"] != "verified" for metric in first["metrics"])
    assert all(
        metric["dimensions"]["scope"] == "resilience_scenario"
        for metric in first["metrics"]
    )
    assert (
        "excluded from observed technology spend"
        in first["extensions"]["recovery_economics"]["accounting_boundary"]
    )


def test_demo_exposes_gaps_and_restore_evidence_limit():
    payload = demo_result()
    titles = {finding["title"] for finding in payload["findings"]}
    assert any("RTO exceeds" in title for title in titles)
    assert any("RPO exceeds" in title for title in titles)
    assert any("not substantiated" in title for title in titles)
    assert any("Restore test missed the RTO" in title for title in titles)
    assert any(metric["basis"] == "observed" for metric in payload["metrics"])
    assert (
        payload["extensions"]["recovery_economics"]["restore_test_freshness"]["status"]
        == "fresh"
    )


@pytest.mark.parametrize("bad", [None, "", "NaN", "Infinity", -1, True])
def test_required_financial_input_fails_closed(bad):
    source = illustrative_scenario()
    source["risk"]["outage_impact_per_hour"] = bad
    with pytest.raises(ScenarioError):
        calculate_scenario(source)


def test_missing_restore_test_does_not_imply_recoverability():
    source = illustrative_scenario()
    del source["restore_test"]
    result = calculate_scenario(source)
    assert result.restore_test is None


def test_full_copy_interval_and_reduction_factors_materially_change_storage():
    source = illustrative_scenario()
    baseline = calculate_scenario(source)
    alternative = copy.deepcopy(source)
    alternative["backup"]["compression_ratio"] = 1
    alternative["backup"]["deduplication_ratio"] = 1
    unreduced = calculate_scenario(alternative)
    assert unreduced.effective_stored_gb > baseline.effective_stored_gb


def test_demo_json_round_trip():
    assert (
        json.loads(json.dumps(demo_result()))["producer"]["name"]
        == "recovery-economics"
    )


def test_demo_cli_honors_pipeline_identity_options():
    args = build_parser().parse_args(
        [
            "ccac",
            "--demo",
            "--run-id",
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "--generated-at",
            "2026-08-04T12:00:00Z",
        ]
    )
    output = StringIO()
    assert run_ccac(args, output) == 0
    payload = json.loads(output.getvalue())
    assert payload["run_id"] == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert payload["generated_at"] == "2026-08-04T12:00:00Z"


def test_future_restore_test_is_rejected_against_run_timestamp():
    source = illustrative_scenario()
    source["restore_test"]["tested_at"] = "2026-09-01T00:00:00Z"
    from recovery_economics.ccac import build_result

    with pytest.raises(ScenarioError, match="cannot be later"):
        build_result(source, mode="illustrative", generated_at="2026-08-04T00:00:00Z")


def test_comparison_keeps_estimated_delta_out_of_savings():
    baseline = illustrative_scenario()
    proposed = copy.deepcopy(baseline)
    proposed["scenario_id"] = "proposed"
    proposed["backup"]["frequency_hours"] = 1
    proposed["recovery"]["restore_throughput_gb_per_hour"] = 10000
    payload = build_comparison_result(
        baseline,
        proposed,
        mode="illustrative",
        run_id="123e4567-e89b-12d3-a456-426614174021",
        generated_at="2026-08-04T12:10:00Z",
    )
    assert payload["opportunities"] == []
    assert all(metric["basis"] == "estimated" for metric in payload["metrics"])
    assert (
        "verified savings"
        in payload["extensions"]["recovery_economics"]["accounting_boundary"]
    )


def test_comparison_rejects_different_workloads():
    baseline = illustrative_scenario()
    proposed = copy.deepcopy(baseline)
    proposed["workload"]["id"] = "different"
    with pytest.raises(ScenarioError, match="must match"):
        build_comparison_result(baseline, proposed, mode="illustrative")
