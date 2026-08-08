import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "recovery_economics", *args]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)


def test_version_option() -> None:
    result = run_cli("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == "recovery-economics 0.3.0"


def test_top_level_help_has_version_neutral_current_identity() -> None:
    result = run_cli("--help")
    assert result.returncode == 0
    assert "v0.1" not in result.stdout
    assert "Model resilience scenario economics" in result.stdout
    assert "RTO/RPO targets" in result.stdout
    assert "restore evidence" in result.stdout


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


def test_analyze_header_only_csv_fails_instead_of_claiming_zero_workloads(
    tmp_path: Path,
) -> None:
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

    assert result.returncode == 4
    assert "no workload rows" in result.stderr


def test_analyze_rejects_nan(tmp_path: Path) -> None:
    source = (FIXTURES_DIR / "simple_config.csv").read_text()
    target = tmp_path / "nan.csv"
    target.write_text(source.replace("100", "NaN", 1))
    result = run_cli("analyze", "--input", str(target), "--output-format", "json")
    assert result.returncode == 4


def test_analyze_rejects_duplicate_workload(tmp_path: Path) -> None:
    lines = (FIXTURES_DIR / "simple_config.csv").read_text().splitlines()
    target = tmp_path / "duplicate.csv"
    target.write_text("\n".join(lines + [lines[1]]) + "\n")
    result = run_cli("analyze", "--input", str(target), "--output-format", "json")
    assert result.returncode == 4
    assert "Duplicate workload" in result.stderr
