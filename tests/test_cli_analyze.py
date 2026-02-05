import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "recovery_economics", *args]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)


def test_analyze_simple_config() -> None:
    input_file = FIXTURES_DIR / "simple_config.csv"

    result = run_cli(
        "analyze",
        "--input",
        str(input_file),
        "--output-format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["schema_version"] == "1.0"
    assert payload["summary"]["total_workloads"] == 2
    assert payload["summary"]["total_monthly_storage_cost"] == 99.0
    assert payload["summary"]["total_monthly_restore_cost"] == 1.5
    assert payload["summary"]["total_monthly_resilience_cost"] == 100.5

    workloads_by_name = {
        workload["workload"]: workload for workload in payload["workloads"]
    }
    assert workloads_by_name["orders-api"]["total_monthly_resilience_cost"] == 24.5
    assert workloads_by_name["billing-db"]["total_monthly_resilience_cost"] == 76.0


def test_analyze_missing_column_exit4() -> None:
    input_file = FIXTURES_DIR / "missing_column.csv"

    result = run_cli(
        "analyze",
        "--input",
        str(input_file),
        "--output-format",
        "json",
    )

    assert result.returncode == 4
    assert "Missing required columns" in result.stderr
    assert "restore_rate_per_gb" in result.stderr


def test_analyze_non_numeric_exit4() -> None:
    input_file = FIXTURES_DIR / "non_numeric.csv"

    result = run_cli(
        "analyze",
        "--input",
        str(input_file),
        "--output-format",
        "json",
    )

    assert result.returncode == 4
    assert "non-numeric" in result.stderr
    assert "data_gb" in result.stderr


def test_analyze_requires_input_flag_exit2() -> None:
    result = run_cli(
        "analyze",
        "--output-format",
        "json",
    )

    assert result.returncode == 2
    assert "--input" in result.stderr


def test_analyze_header_only_csv_returns_zero_workloads(tmp_path: Path) -> None:
    input_file = tmp_path / "header_only.csv"
    input_file.write_text(
        "workload,data_gb,backup_frequency_per_month,retention_months,"
        "storage_rate_per_gb_month,restore_gb_per_month,restore_rate_per_gb\n",
        encoding="utf-8",
    )

    result = run_cli(
        "analyze",
        "--input",
        str(input_file),
        "--output-format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary"]["total_workloads"] == 0
    assert payload["workloads"] == []
