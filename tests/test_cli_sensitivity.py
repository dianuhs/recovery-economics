import subprocess


def test_cli_scenario_compare_runs():
    cmd = [
        "recovery-economics",
        "--scenario-file",
        "scenarios/ransomware_fast_recovery.yml",
        "--compare-strategies",
    ]
    out = subprocess.check_output(cmd, text=True)
    # Basic sanity checks on the output
    assert "Recovery Economics — Scenario Strategy Comparison" in out
    assert "ai_assisted" in out
    assert "manual_only" in out
    assert "hybrid" in out
