from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .aws_pricing import get_default_pricing
from .model import RestoreInputs, estimate_restore


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="recovery-economics")
    p.add_argument("--tier", required=True, choices=["glacier", "deep_archive"])
    p.add_argument("--destination", required=True, choices=["internet", "intra_aws"])
    p.add_argument("--size-gb", required=True, type=float)
    p.add_argument("--bandwidth-mbps", required=True, type=float)
    p.add_argument("--efficiency", default=0.70, type=float)
    p.add_argument("--rto-hours", default=None, type=float)
    p.add_argument("--json", action="store_true", help="Output JSON")
    p.add_argument(
        "--sensitivity",
        action="store_true",
        help="Show sensitivity across bandwidth and efficiency ranges",
    )
    return p


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
        "inputs": asdict(inputs),
        "pricing": asdict(pricing),
        "result": asdict(result),
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return

    print(f"Recovery Economics — AWS Restore Stress Test ({args.tier})")
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
