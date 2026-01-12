from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Any

from .aws_pricing import get_default_pricing
from .model import RestoreInputs, estimate_restore


SCENARIOS: dict[str, dict[str, Any]] = {
    # “Max pain” assumptions. You can tune these later.
    "ransomware": {
        "destination": "internet",
        "rto_hours": 24.0,
        "bandwidth_mbps": 1000.0,
        "efficiency": 0.70,
    },
    "region_failure": {
        "destination": "internet",
        "rto_hours": 48.0,
        "bandwidth_mbps": 500.0,
        "efficiency": 0.65,
    },
    "accidental_delete": {
        "destination": "intra_aws",
        "rto_hours": 8.0,
        "bandwidth_mbps": 1000.0,
        "efficiency": 0.80,
    },
    "test_restore": {
        "destination": "intra_aws",
        "rto_hours": None,
        "bandwidth_mbps": 500.0,
        "efficiency": 0.70,
    },
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="recovery-economics")

    p.add_argument(
        "--tier",
        required=True,
        choices=["glacier", "deep_archive"],
        help="Storage tier used for backup data",
    )

    p.add_argument(
        "--destination",
        choices=["internet", "intra_aws"],
        default=None,
        help="Restore destination (internet/on-prem vs intra-AWS)",
    )

    p.add_argument(
        "--size-gb", required=True, type=float, help="Data size to restore (GB)"
    )

    p.add_argument(
        "--bandwidth-mbps",
        default=None,
        type=float,
        help="Available bandwidth for transfer (Mbps)",
    )

    p.add_argument(
        "--efficiency",
        default=None,
        type=float,
        help="Link efficiency factor (0–1). Default depends on scenario or 0.70.",
    )

    p.add_argument(
        "--rto-hours",
        default=None,
        type=float,
        help="Recovery Time Objective (hours). If provided, tool flags MET/MISSED.",
    )

    p.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS.keys()),
        default=None,
        help="Apply a realistic scenario preset (sets defaults; your flags can override).",
    )

    p.add_argument("--json", action="store_true", help="Output JSON")

    p.add_argument(
        "--sensitivity",
        action="store_true",
        help="Show sensitivity across bandwidth and efficiency ranges",
    )

    # Compare mode
    p.add_argument(
        "--compare",
        action="store_true",
        help="Compare your run (A) against an alternate decision (B).",
    )
    p.add_argument(
        "--compare-tier",
        choices=["glacier", "deep_archive"],
        default=None,
        help="Alternate tier for comparison (B).",
    )
    p.add_argument(
        "--compare-destination",
        choices=["internet", "intra_aws"],
        default=None,
        help="Alternate destination for comparison (B).",
    )
    p.add_argument(
        "--compare-bandwidth-mbps",
        type=float,
        default=None,
        help="Alternate bandwidth for comparison (B).",
    )
    p.add_argument(
        "--compare-efficiency",
        type=float,
        default=None,
        help="Alternate link efficiency for comparison (B).",
    )
    p.add_argument(
        "--compare-rto-hours",
        type=float,
        default=None,
        help="Alternate RTO for comparison (B). Defaults to A if omitted.",
    )

    return p


def _apply_scenario_defaults(args: argparse.Namespace) -> dict[str, Any] | None:
    if not args.scenario:
        return None

    defaults = SCENARIOS[args.scenario].copy()

    # Apply scenario defaults only when user didn’t specify explicit flags.
    if args.destination is None:
        args.destination = defaults["destination"]

    if args.bandwidth_mbps is None:
        args.bandwidth_mbps = defaults["bandwidth_mbps"]

    if args.efficiency is None:
        args.efficiency = defaults["efficiency"]

    if args.rto_hours is None:
        args.rto_hours = defaults["rto_hours"]

    # Safety: if scenario’s RTO is None, keep None (no RTO evaluation)
    return defaults


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


def _hours_delta_label(delta_hours: float) -> str:
    sign = "+" if delta_hours > 0 else ""
    return f"{sign}{delta_hours:.2f}h"


def _usd_delta_label(delta_usd: float) -> str:
    sign = "+" if delta_usd > 0 else ""
    return f"{sign}${delta_usd:,.2f}"


def _monthly_storage_cost(size_gb: float, tier: str) -> float:
    pricing = get_default_pricing(tier)
    return size_gb * pricing.storage_per_gb_month


def _print_narrative(
    *,
    tier: str,
    destination: str,
    size_gb: float,
    result_total_time: float,
    rto_hours: float | None,
    pricing_tier_monthly: float,
) -> None:
    print("\nDecision Narrative")
    print("-----------------")

    # 1) Plain-English framing for time + RTO
    if rto_hours is not None:
        if result_total_time > rto_hours:
            miss_by = result_total_time - rto_hours
            print(
                f"Under these assumptions, this restore misses your RTO by {miss_by:.2f} hours "
                f"(total {result_total_time:.2f}h vs RTO {rto_hours:.2f}h)."
            )
        else:
            headroom = rto_hours - result_total_time
            print(
                f"Under these assumptions, this restore meets your RTO with {headroom:.2f} hours of headroom "
                f"(total {result_total_time:.2f}h vs RTO {rto_hours:.2f}h)."
            )
    else:
        print(
            "This run does not evaluate an RTO. Add --rto-hours to see whether recovery time meets the business target."
        )

    # 2) Monthly storage context (the “hidden tradeoff” frame)
    dest_label = "internet/on-prem" if destination == "internet" else "intra-AWS"
    print(
        f"Monthly storage cost for {tier} at {size_gb:,.0f} GB is ~${pricing_tier_monthly:,.2f}/month "
        f"(restore destination: {dest_label})."
    )

    # 3) Subtle “what this tool is for”
    print(
        "Use this to sanity-check whether storage savings are worth the recovery-time and recovery-cost profile."
    )


def _print_compare_insights(
    *,
    size_gb: float,
    tier_a: str,
    tier_b: str,
    cost_a: float,
    cost_b: float,
    time_a: float,
    time_b: float,
) -> None:
    # Monthly storage deltas (B - A)
    storage_a = _monthly_storage_cost(size_gb, tier_a)
    storage_b = _monthly_storage_cost(size_gb, tier_b)
    storage_delta = storage_b - storage_a  # positive = B costs more monthly

    print("\nCompare Insights")
    print("---------------")

    # Storage savings framing
    if abs(storage_delta) < 1e-9:
        print(
            "Monthly storage cost is effectively the same between A and B at this size."
        )
    elif storage_delta < 0:
        print(f"B saves {_usd_delta_label(-storage_delta)} per month in storage vs A.")
    else:
        print(
            f"B costs {_usd_delta_label(storage_delta)} more per month in storage vs A."
        )

    # “Restore shock premium” framing
    restore_cost_delta = cost_b - cost_a
    restore_time_delta = time_b - time_a

    if restore_cost_delta < 0:
        print(
            f"B lowers one restore event cost by {_usd_delta_label(-restore_cost_delta)} vs A."
        )
    elif restore_cost_delta > 0:
        print(
            f"B increases one restore event cost by {_usd_delta_label(restore_cost_delta)} vs A."
        )
    else:
        print("Restore event cost is the same between A and B under these assumptions.")

    if abs(restore_time_delta) > 1e-9:
        direction = "faster" if restore_time_delta < 0 else "slower"
        print(
            f"B is {abs(restore_time_delta):.2f} hours {direction} to recover than A."
        )
    else:
        print("Restore time is the same between A and B under these assumptions.")

    # Break-even: months of storage savings to “pay” for a higher restore bill
    # Only meaningful if there is monthly savings AND B increases restore cost
    monthly_savings = (
        -storage_delta if storage_delta < 0 else 0.0
    )  # savings if B cheaper monthly
    extra_restore_cost = restore_cost_delta if restore_cost_delta > 0 else 0.0

    if monthly_savings > 0 and extra_restore_cost > 0:
        months = extra_restore_cost / monthly_savings
        print(
            f"Break-even: it takes ~{months:.1f} months of storage savings for B to offset one higher restore bill."
        )


def main() -> None:
    args = build_parser().parse_args()

    scenario_defaults = _apply_scenario_defaults(args)

    # Final defaulting for non-scenario runs:
    if args.destination is None:
        args.destination = "internet"
    if args.bandwidth_mbps is None:
        args.bandwidth_mbps = 1000.0
    if args.efficiency is None:
        args.efficiency = 0.70

    pricing = get_default_pricing(args.tier)
    inputs = RestoreInputs(
        data_size_gb=args.size_gb,
        bandwidth_mbps=args.bandwidth_mbps,
        link_efficiency=args.efficiency,
        restore_destination=args.destination,
        rto_hours=args.rto_hours,
    )
    result = estimate_restore(inputs, pricing)

    payload: dict[str, Any] = {
        "inputs": asdict(inputs),
        "pricing": asdict(pricing),
        "result": asdict(result),
    }
    if args.scenario:
        payload["scenario"] = {
            "name": args.scenario,
            "applied_defaults": scenario_defaults or {},
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

    # Narrative output (clear English)
    monthly = args.size_gb * pricing.storage_per_gb_month
    _print_narrative(
        tier=args.tier,
        destination=args.destination,
        size_gb=args.size_gb,
        result_total_time=result.total_time_hours,
        rto_hours=result.rto_hours,
        pricing_tier_monthly=monthly,
    )

    if args.sensitivity:
        print_sensitivity(
            tier=args.tier,
            destination=args.destination,
            size_gb=args.size_gb,
            rto_hours=args.rto_hours,
        )

    # Compare mode
    if args.compare:
        tier_b = args.compare_tier or args.tier
        dest_b = args.compare_destination or args.destination
        bw_b = args.compare_bandwidth_mbps or args.bandwidth_mbps
        eff_b = args.compare_efficiency or args.efficiency
        rto_b = (
            args.compare_rto_hours
            if args.compare_rto_hours is not None
            else args.rto_hours
        )

        pricing_b = get_default_pricing(tier_b)
        inputs_b = RestoreInputs(
            data_size_gb=args.size_gb,
            bandwidth_mbps=bw_b,
            link_efficiency=eff_b,
            restore_destination=dest_b,
            rto_hours=rto_b,
        )
        result_b = estimate_restore(inputs_b, pricing_b)

        print("\nComparison (A vs B)")
        print(f"A: {args.tier} → {args.destination}")
        print(
            f"  Total cost: ${result.total_cost_usd:,.2f}  (retrieval ${result.retrieval_cost_usd:,.2f}, egress ${result.egress_cost_usd:,.2f})"
        )
        print(
            f"  Total time: {result.total_time_hours:.2f}h  (thaw {result.thaw_time_hours:.2f}h, transfer {result.transfer_time_hours:.2f}h)"
        )
        if result.rto_hours is not None:
            print(
                f"  RTO:        {result.rto_hours:.2f}h — {'MISSED' if result.rto_mismatch else 'MET'}"
            )

        print(f"B: {tier_b} → {dest_b}")
        print(
            f"  Total cost: ${result_b.total_cost_usd:,.2f}  (retrieval ${result_b.retrieval_cost_usd:,.2f}, egress ${result_b.egress_cost_usd:,.2f})"
        )
        print(
            f"  Total time: {result_b.total_time_hours:.2f}h  (thaw {result_b.thaw_time_hours:.2f}h, transfer {result_b.transfer_time_hours:.2f}h)"
        )
        if result_b.rto_hours is not None:
            print(
                f"  RTO:        {result_b.rto_hours:.2f}h — {'MISSED' if result_b.rto_mismatch else 'MET'}"
            )

        print("\nDelta (B - A)")
        print(
            f"  Cost: {_usd_delta_label(result_b.total_cost_usd - result.total_cost_usd)}"
        )
        print(
            f"  Time: {_hours_delta_label(result_b.total_time_hours - result.total_time_hours)}"
        )
        if result.rto_hours is not None or result_b.rto_hours is not None:
            a_stat = "MISSED" if result.rto_mismatch else "MET"
            b_stat = "MISSED" if result_b.rto_mismatch else "MET"
            print(f"  RTO:  A={a_stat}  B={b_stat}")

        _print_compare_insights(
            size_gb=args.size_gb,
            tier_a=args.tier,
            tier_b=tier_b,
            cost_a=result.total_cost_usd,
            cost_b=result_b.total_cost_usd,
            time_a=result.total_time_hours,
            time_b=result_b.total_time_hours,
        )


if __name__ == "__main__":
    main()
