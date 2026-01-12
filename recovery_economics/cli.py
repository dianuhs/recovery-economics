from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .aws_pricing import get_default_pricing
from .model import RestoreInputs, RestoreResult, estimate_restore

# -----------------------------
# Scenario presets (v1)
# -----------------------------
SCENARIOS = {
    "test_restore": {
        "destination": "intra_aws",
        "rto_hours": 72.0,
        "bandwidth_mbps": 500.0,
        "efficiency": 0.80,
    },
    "accidental_delete": {
        "destination": "intra_aws",
        "rto_hours": 24.0,
        "bandwidth_mbps": 1000.0,
        "efficiency": 0.80,
    },
    "ransomware": {
        "destination": "internet",
        "rto_hours": 24.0,
        "bandwidth_mbps": 1000.0,
        "efficiency": 0.70,
    },
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

    # -----------------------------
    # Compare mode
    # -----------------------------
    p.add_argument(
        "--compare",
        action="store_true",
        help="Compare a second configuration B against the primary configuration A",
    )
    p.add_argument("--compare-tier", choices=["glacier", "deep_archive"], default=None)
    p.add_argument(
        "--compare-destination", choices=["internet", "intra_aws"], default=None
    )
    p.add_argument("--compare-bandwidth-mbps", type=float, default=None)
    p.add_argument("--compare-efficiency", type=float, default=None)
    p.add_argument("--compare-rto-hours", type=float, default=None)

    return p


def apply_scenario_defaults(args: argparse.Namespace) -> dict | None:
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
    missing = []
    if args.destination is None:
        missing.append("--destination (or --scenario)")
    if args.bandwidth_mbps is None:
        missing.append("--bandwidth-mbps (or --scenario)")

    if missing:
        raise SystemExit(
            "Missing required arguments: "
            + ", ".join(missing)
            + "\nTip: try --scenario ransomware (or test_restore / accidental_delete / region_failure)."
        )

    if args.efficiency is None:
        args.efficiency = 0.70


def build_inputs_from_args(
    *,
    size_gb: float,
    destination: str,
    bandwidth_mbps: float,
    efficiency: float,
    rto_hours: float | None,
) -> RestoreInputs:
    return RestoreInputs(
        data_size_gb=size_gb,
        bandwidth_mbps=bandwidth_mbps,
        link_efficiency=efficiency,
        restore_destination=destination,
        rto_hours=rto_hours,
    )


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


def fmt_rto(result: RestoreResult) -> str:
    if result.rto_hours is None:
        return "N/A"
    return "MISSED" if result.rto_mismatch else "MET"


def print_one(label: str, tier: str, destination: str, result: RestoreResult) -> None:
    print(f"{label}: {tier} → {destination}")
    print(
        f"  Total cost: ${result.total_cost_usd:,.2f}  (retrieval ${result.retrieval_cost_usd:,.2f}, egress ${result.egress_cost_usd:,.2f})"
    )
    print(
        f"  Total time: {result.total_time_hours:,.2f}h  (thaw {result.thaw_time_hours:,.2f}h, transfer {result.transfer_time_hours:,.2f}h)"
    )
    if result.rto_hours is not None:
        print(f"  RTO:        {result.rto_hours:,.2f}h — {fmt_rto(result)}")


def main() -> None:
    args = build_parser().parse_args()

    used_preset = apply_scenario_defaults(args)
    validate_required_after_defaults(args)

    # Primary A
    tier_a = args.tier
    dest_a = args.destination
    bw_a = float(args.bandwidth_mbps)
    eff_a = float(args.efficiency)
    rto_a = args.rto_hours

    pricing_a = get_default_pricing(tier_a)
    inputs_a = build_inputs_from_args(
        size_gb=args.size_gb,
        destination=dest_a,
        bandwidth_mbps=bw_a,
        efficiency=eff_a,
        rto_hours=rto_a,
    )
    result_a = estimate_restore(inputs_a, pricing_a)

    # Optional compare B
    result_b = None
    inputs_b = None
    pricing_b = None
    tier_b = None
    dest_b = None

    if args.compare:
        tier_b = args.compare_tier or tier_a
        dest_b = args.compare_destination or dest_a
        bw_b = args.compare_bandwidth_mbps or bw_a
        eff_b = args.compare_efficiency or eff_a
        rto_b = args.compare_rto_hours if args.compare_rto_hours is not None else rto_a

        pricing_b = get_default_pricing(tier_b)
        inputs_b = build_inputs_from_args(
            size_gb=args.size_gb,
            destination=dest_b,
            bandwidth_mbps=float(bw_b),
            efficiency=float(eff_b),
            rto_hours=rto_b,
        )
        result_b = estimate_restore(inputs_b, pricing_b)

    payload = {
        "scenario": {
            "name": args.scenario,
            "applied_defaults": used_preset,
        },
        "run_a": {
            "inputs": asdict(inputs_a),
            "pricing": asdict(pricing_a),
            "result": asdict(result_a),
            "tier": tier_a,
            "destination": dest_a,
        },
    }

    if (
        args.compare
        and result_b is not None
        and inputs_b is not None
        and pricing_b is not None
    ):
        payload["run_b"] = {
            "inputs": asdict(inputs_b),
            "pricing": asdict(pricing_b),
            "result": asdict(result_b),
            "tier": tier_b,
            "destination": dest_b,
        }
        payload["delta"] = {
            "cost_usd": round(result_b.total_cost_usd - result_a.total_cost_usd, 2),
            "time_hours": round(
                result_b.total_time_hours - result_a.total_time_hours, 2
            ),
            "rto_a": fmt_rto(result_a),
            "rto_b": fmt_rto(result_b),
        }

    if args.json:
        print(json.dumps(payload, indent=2))
        return

    print(f"Recovery Economics — AWS Restore Stress Test ({tier_a})")
    if args.scenario:
        print(f"Scenario: {args.scenario}")
    print(f"Destination: {dest_a}\n")

    print(f"Retrieval cost: ${result_a.retrieval_cost_usd:,.2f}")
    print(f"Egress cost:    ${result_a.egress_cost_usd:,.2f}")
    print(f"Total cost:     ${result_a.total_cost_usd:,.2f}\n")

    print(f"Thaw time:      {result_a.thaw_time_hours:,.2f} hours")
    print(f"Transfer time:  {result_a.transfer_time_hours:,.2f} hours")
    print(f"Total time:     {result_a.total_time_hours:,.2f} hours")

    if result_a.rto_hours is not None:
        print(f"RTO:            {result_a.rto_hours:,.2f} hours — {fmt_rto(result_a)}")

    if args.sensitivity:
        print_sensitivity(
            tier=tier_a,
            destination=dest_a,
            size_gb=args.size_gb,
            rto_hours=rto_a,
        )

    if (
        args.compare
        and result_b is not None
        and tier_b is not None
        and dest_b is not None
    ):
        print("\nComparison (A vs B)")
        print_one("A", tier_a, dest_a, result_a)
        print_one("B", tier_b, dest_b, result_b)

        delta_cost = result_b.total_cost_usd - result_a.total_cost_usd
        delta_time = result_b.total_time_hours - result_a.total_time_hours

        sign_cost = "+" if delta_cost >= 0 else "-"
        sign_time = "+" if delta_time >= 0 else "-"

        print("\nDelta (B - A)")
        print(f"  Cost: {sign_cost}${abs(delta_cost):,.2f}")
        print(f"  Time: {sign_time}{abs(delta_time):,.2f}h")
        if result_a.rto_hours is not None:
            print(f"  RTO:  A={fmt_rto(result_a)}  B={fmt_rto(result_b)}")


if __name__ == "__main__":
    main()
