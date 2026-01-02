import subprocess
import sys


def test_cli_sensitivity_runs():
    cmd = [
        "recovery-economics",
        "--tier",
        "deep_archive",
        "--destination",
        "internet",
        "--size-gb",
        "5000",
        "--bandwidth-mbps",
        "1000",
        "--rto-hours",
        "24",
        "--sensitivity",
    ]
    out = subprocess.check_output(cmd, text=True)
    assert "Sensitivity Analysis" in out
