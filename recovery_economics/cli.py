from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .aws_pricing import get_default_pricing
from .model import RestoreInputs, estimate_restore

# -----------------------------
# Scenario presets (v1)
# -----------------------------
SCENARIOS = {
    # Lower urgency, usually validated inside cloud
    "test_restore": {
        "destination": "intra_aws",
        "rto_hours": 72.0,
        "bandwidth_mbps": 500.0,
        "efficiency": 0.80,
    },
    # Urgent internal restore (fat-finger / accidental deletion)
    "accidental_delete": {
        "destination": "intra_aws",
        "rto_hours": 24.0,
        "bandwidth_mbps": 1000.0,
        "efficiency": 0.80,
    },
    # Common “max pain” path: restore out to on-prem / clean room over internet
    "ransomware": {
        "destination": "internet",
        "rto_hours": 24.0,
        "bandwidth_mbps": 1000.0,
        "efficiency": 0.70,
    },
    # Highly urgent, messy conditions (reduced effective throughput)
    "region_failure": {
        "destination": "internet",
        "rto_hours": 12.0,
        "bandwidth_mbps": 2000.0,
        "efficiency": 0.60,
    },
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="recovery-economics")

    p.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS.keys()),
        default=None,
        help="Apply a preset scenario (sets destination/rto/bandwidth/efficiency; explicit flags override).",
    )

    p.add_argument("--tier", required=True, choices=["glacier", "deep_archive"])

    # These become optional so scenario can set them. If no scenario, we validate later.
    p.add_argument("--destination", default=None, choices=["internet", "intra_aws"])
    p.add_argument("--size-gb", required=True, type=float)
    p.add_argument("--bandwidth-mbps", default=None, type=float)

    p.add_argument("--efficiency", default=None, type=float)
    p.add_argument("--rto-hours", default=None, type=float)

    p.add_argument("--json", action="store_true", help="Output JSON")
    p.add_argument(
        "--sensitivity",
        action="store_true",
        help="Show sensitivity across bandwidth and efficiency ranges",
    )
    return p


def apply_scenario_defaults(args: argparse.Namespace) -> dict | None:
    """
    Apply scenario defaults onto argparse args ONLY where the user did not provide a flag.
    Returns the scenario preset dict used (or None).
    """
    if args.scenario is None:
        return None

    preset = SCENARIOS[args.scenario]

    if args.destination is None:
        args.destination = preset["destination"]
    if args.bandwidth_mbps is None:
        args.bandwidth_mbps = preset["bandwidth_mbps"]
    if args.efficiency is None:
        args.efficiency = preset["efficiency"]
    if args.rto_hours is None:
        args.rto_hours = preset["rto_hours"]

    return preset


def validate_required_after_defaults(args: argparse.Namespace) -> None:
    """
    After scenarios/defaults, ensure required runtime fields exist.
    """
    missing = []
    if args.destination is None:
        missing.append("--destination (or --scenario)")
    if args.bandwidth_mbps is None:
        missing.append("--bandwidth-mbps (or --scenario)")
    if args.efficiency is None:
        # We always set a base default if still None, but keep this for clarity.
        pass

    if missing:
        raise SystemExit(
            "Missing required arguments: "
            + ", ".join(missing)
            + "\nTip: try --scenario ransomware (or test_restore / accidental_delete / region_failure)."
        )

    # Base default if not set by scenario or flag
    if args.efficiency is None:
        args.efficiency = 0.70


def print_sensitivity(
    tier: str,
    destination: str,
    size_gb: float,
    rto_hours: float | None,
) -> None:
    pricing = get_default_pricing(tier)

    bandwidths = [100, 500, 1000]
    efficiencies = [0.5, 0.7, 0.9]

    print("\nSensitivity Analysis (Total Restore Time, hours)")
    header = "Bandwidth ↓ / Efficiency → | " + " | ".join(
        f"{e:.1f}" for e in efficiencies
    )
    print(header)
    print("-" * len(header))

    for bw in bandwidths:
        row = [f"{bw:>6} Mbps"]
        for eff in efficiencies:
            inputs = RestoreInputs(
                data_size_gb=size_gb,
                bandwidth_mbps=bw,
                link_efficiency=eff,
                restore_destination=destination,
                rto_hours=rto_hours,
            )
            result = estimate_restore(inputs, pricing)
            cell = f"{result.total_time_hours:.1f}"
            if rto_hours is not None and result.rto_mismatch:
                cell += " ⚠"
            row.append(cell)
        print(" | ".join(row))


def main() -> None:
    args = build_parser().parse_args()

    used_preset = apply_scenario_defaults(args)
    validate_required_after_defaults(args)

    pricing = get_default_pricing(args.tier)
    inputs = RestoreInputs(
        data_size_gb=args.size_gb,
        bandwidth_mbps=args.bandwidth_mbps,
        link_efficiency=args.efficiency,
        restore_destination=args.destination,
        rto_hours=args.rto_hours,
    )
    result = estimate_restore(inputs, pricing)

    payload = {
        "scenario": {
            "name": args.scenario,
            "applied_defaults": used_preset,
        },
        "inputs": asdict(inputs),
        "pricing": asdict(pricing),
        "result": asdict(result),
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return

    print(f"Recovery Economics — AWS Restore Stress Test ({args.tier})")
    if args.scenario:
        print(f"Scenario: {args.scenario}")
    print(f"Destination: {args.destination}\n")

    print(f"Retrieval cost: ${result.retrieval_cost_usd:,.2f}")
    print(f"Egress cost:    ${result.egress_cost_usd:,.2f}")
    print(f"Total cost:     ${result.total_cost_usd:,.2f}\n")

    print(f"Thaw time:      {result.thaw_time_hours:,.2f} hours")
    print(f"Transfer time:  {result.transfer_time_hours:,.2f} hours")
    print(f"Total time:     {result.total_time_hours:,.2f} hours")

    if result.rto_hours is not None:
        status = "MISSED" if result.rto_mismatch else "MET"
        print(f"RTO:            {result.rto_hours:,.2f} hours — {status}")

    if args.sensitivity:
        print_sensitivity(
            tier=args.tier,
            destination=args.destination,
            size_gb=args.size_gb,
            rto_hours=args.rto_hours,
        )


if __name__ == "__main__":
    main()
