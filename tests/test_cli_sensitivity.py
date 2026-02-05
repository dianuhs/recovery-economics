import csv
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "recovery_economics", *args]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)


def test_analyze_csv_output_per_workload_rows() -> None:
    input_file = FIXTURES_DIR / "simple_config.csv"

    result = run_cli(
        "analyze",
        "--input",
        str(input_file),
        "--output-format",
        "csv",
    )

    assert result.returncode == 0, result.stderr

    rows = list(csv.DictReader(result.stdout.splitlines()))
    assert len(rows) == 2
    assert rows[0]["workload"] == "orders-api"
    assert rows[0]["total_monthly_resilience_cost"] == "24.5"
    assert rows[1]["workload"] == "billing-db"
    assert rows[1]["total_monthly_resilience_cost"] == "76.0"
