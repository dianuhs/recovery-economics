from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str):
    return subprocess.run(
        [sys.executable, "-m", "recovery_economics", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_ccac_demo_stdout_is_valid_json_and_deterministic():
    first = run_cli("ccac", "--demo")
    second = run_cli("ccac", "--demo")
    assert first.returncode == 0, first.stderr
    assert first.stdout == second.stdout
    assert json.loads(first.stdout)["producer"]["version"] == "0.2.1"


def test_ccac_demo_writes_only_to_output_file(tmp_path):
    target = tmp_path / "result.json"
    result = run_cli("ccac", "--demo", "--output", str(target))
    assert result.returncode == 0
    assert result.stdout == ""
    assert json.loads(target.read_text())["mode"] == "illustrative"


def test_ccac_yaml_input_normalizes_timestamp_and_runs(tmp_path):
    target = tmp_path / "result.json"
    result = run_cli(
        "ccac",
        "--input",
        str(ROOT / "examples" / "scenario-v2.yml"),
        "--generated-at",
        "2026-08-04T12:10:00Z",
        "--output",
        str(target),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(target.read_text())
    assert payload["mode"] == "real"
    assert payload["extensions"]["recovery_economics"]["restore_test"][
        "tested_at"
    ].endswith("Z")


def test_compare_ccac_runs_with_versioned_scenarios(tmp_path):
    target = tmp_path / "comparison.json"
    result = run_cli(
        "compare-ccac",
        "--baseline",
        str(ROOT / "examples" / "scenario-v2.yml"),
        "--proposed",
        str(ROOT / "examples" / "scenario-v2-proposed.yml"),
        "--generated-at",
        "2026-08-04T12:10:00Z",
        "--output",
        str(target),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(target.read_text())
    assert payload["document_type"] == "tool_result"
    assert (
        payload["extensions"]["recovery_economics"]["comparison"]["proposed"][
            "rto_target_met"
        ]
        is True
    )
