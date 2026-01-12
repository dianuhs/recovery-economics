from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .aws_pricing import Pricing, get_default_pricing
from .model import RestoreInputs, estimate_restore


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="recovery-economics")

    p.add_argument("--tier", required=True, choices=["glacier", "deep_archive"])
    p.add_argument("--destination", choices=["internet", "intra_aws"])
    p.add_argument("--size-gb", required=True, type=float)

    p.add_argument("--bandwidth-mbps", type=float)
    p.add_argument("--efficiency", default=None, type=float)
    p.add_argument("--rto-hours", default=None, type=float)

    p.add_argument("--json", action="store_true", help="Output JSON")

    p.add_argument(
        "--sensitivity",
        action="store_true",
        help="Show sensitivity across bandwidth and efficiency ranges",
    )

    # Scenario presets (you already added these; keep them)
    p.add_argument(
        "--scenario",
        choices=["ransomware", "region_failure", "accidental_delete", "test_restore"],
        default=None,
        help="Apply named scenario defaults (can still override with explicit flags)",
    )

    # Compare mode (you already added these; keep them)
    p.add_argument("--compare", action="store_true", help="Compare A vs B")
    p.add_argument("--compare-tier", choices=["glacier", "deep_archive"], default=None)
    p.add_argument(
        "--compare-destination", choices=["internet", "intra_aws"], default=None
    )

    # NEW: Break-even analysis (FinOps-coded)
    p.add_argument(
        "--break-even",
        action="store_true",
        help="In compare mode, compute months of storage savings to offset restore penalty",
    )

    # NEW: Decision narrative output (clear, human-readable explanation)
    p.add_argument(
        "--explain",
        action="store_true",
        help="Add a short decision narrative (drivers + RTO impact)",
    )

    return p


def apply_scenario_defaults(args: argparse.Namespace) -> dict | None:
    """
    Returns scenario info payload (for JSON output) and mutates args with defaults
    ONLY when the user hasn't explicitly provided that input.
    """
    if not args.scenario:
        return None

    scenarios = {
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
            "efficiency": 0.75,
        },
        "accidental_delete": {
            "destination": "intra_aws",
            "rto_hours": 4.0,
            "bandwidth_mbps": 2000.0,
            "efficiency": 0.80,
        },
        "test_restore": {
            "destination": "intra_aws",
            "rto_hours": 48.0,
            "bandwidth_mbps": 500.0,
            "efficiency": 0.70,
        },
    }

    preset = scenarios[args.scenario]

    applied = {}
    if args.destination is None:
        args.destination = preset["destination"]
        applied["destination"] = args.destination

    if args.rto_hours is None:
        args.rto_hours = preset["rto_hours"]
        applied["rto_hours"] = args.rto_hours

    if args.bandwidth_mbps is None:
        args.bandwidth_mbps = preset["bandwidth_mbps"]
        applied["bandwidth_mbps"] = args.bandwidth_mbps

    if args.efficiency is None:
        args.efficiency = preset["efficiency"]
        applied["efficiency"] = args.efficiency

    return {"name": args.scenario, "applied_defaults": applied}


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


def decision_narrative(
    label: str, inputs: RestoreInputs, pricing: Pricing, result
) -> None:
    """
    Prints a compact explanation: drivers + what it means for RTO.
    """
    print(f"\nExplanation ({label})")
    drivers = []
    if result.thaw_time_hours >= result.transfer_time_hours:
        drivers.append(
            f"Time is dominated by thaw/restore delay ({result.thaw_time_hours:.1f}h)."
        )
    else:
        drivers.append(
            f"Time is dominated by network transfer ({result.transfer_time_hours:.1f}h)."
        )

    if result.egress_cost_usd >= result.retrieval_cost_usd:
        drivers.append(
            f"Cost is dominated by egress (${result.egress_cost_usd:,.0f}) vs retrieval (${result.retrieval_cost_usd:,.0f})."
        )
    else:
        drivers.append(
            f"Cost is dominated by retrieval (${result.retrieval_cost_usd:,.0f}) vs egress (${result.egress_cost_usd:,.0f})."
        )

    for line in drivers:
        print(f"- {line}")

    if result.rto_hours is not None:
        if result.rto_mismatch:
            over = result.total_time_hours - result.rto_hours
            print(
                f"- This misses your RTO by ~{over:.1f} hours under the stated network assumptions."
            )
        else:
            slack = result.rto_hours - result.total_time_hours
            print(
                f"- This meets your RTO with ~{slack:.1f} hours of slack under the stated network assumptions."
            )

    # Make the "engineering" constraint explicit
    print(
        "- Note: Glacier classes have multiple retrieval options with different timing and fees; this model uses one thaw assumption per tier."
    )


def compute_break_even_months(
    size_gb: float,
    pricing_a: Pricing,
    pricing_b: Pricing,
    restore_cost_a: float,
    restore_cost_b: float,
) -> tuple[float | None, float]:
    """
    Returns (months, monthly_savings_usd)

    monthly_savings_usd = storage_cost_a - storage_cost_b
    months = extra_restore_cost / monthly_savings (only if extra_restore_cost > 0 and savings > 0)
    """
    monthly_storage_a = size_gb * pricing_a.storage_per_gb_month
    monthly_storage_b = size_gb * pricing_b.storage_per_gb_month
    monthly_savings = monthly_storage_a - monthly_storage_b

    extra_restore_cost = restore_cost_b - restore_cost_a

    if monthly_savings <= 0:
        return (None, monthly_savings)

    if extra_restore_cost <= 0:
        return (0.0, monthly_savings)

    months = extra_restore_cost / monthly_savings
    return (months, monthly_savings)


def print_result_block(title: str, tier: str, destination: str, result) -> None:
    print(title)
    print(
        f"  Total cost: ${result.total_cost_usd:,.2f}  (retrieval ${result.retrieval_cost_usd:,.2f}, egress ${result.egress_cost_usd:,.2f})"
    )
    print(
        f"  Total time: {result.total_time_hours:.2f}h  (thaw {result.thaw_time_hours:.2f}h, transfer {result.transfer_time_hours:.2f}h)"
    )
    if result.rto_hours is not None:
        status = "MISSED" if result.rto_mismatch else "MET"
        print(f"  RTO:        {result.rto_hours:.2f}h — {status}")


def main() -> None:
    args = build_parser().parse_args()

    scenario_info = apply_scenario_defaults(args)

    # Final required checks (after scenario defaults)
    if args.destination is None:
        raise SystemExit("--destination is required (or provide --scenario)")

    if args.bandwidth_mbps is None:
        raise SystemExit("--bandwidth-mbps is required (or provide --scenario)")

    if args.efficiency is None:
        args.efficiency = 0.70

    pricing_a = get_default_pricing(args.tier)
    inputs_a = RestoreInputs(
        data_size_gb=args.size_gb,
        bandwidth_mbps=args.bandwidth_mbps,
        link_efficiency=args.efficiency,
        restore_destination=args.destination,
        rto_hours=args.rto_hours,
    )
    result_a = estimate_restore(inputs_a, pricing_a)

    payload = {
        "scenario": scenario_info,
        "inputs": asdict(inputs_a),
        "pricing": asdict(pricing_a),
        "result": asdict(result_a),
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return

    print(f"Recovery Economics — AWS Restore Stress Test ({args.tier})")
    if args.scenario:
        print(f"Scenario: {args.scenario}")
    print(f"Destination: {args.destination}\n")

    print(f"Retrieval cost: ${result_a.retrieval_cost_usd:,.2f}")
    print(f"Egress cost:    ${result_a.egress_cost_usd:,.2f}")
    print(f"Total cost:     ${result_a.total_cost_usd:,.2f}\n")

    print(f"Thaw time:      {result_a.thaw_time_hours:,.2f} hours")
    print(f"Transfer time:  {result_a.transfer_time_hours:,.2f} hours")
    print(f"Total time:     {result_a.total_time_hours:,.2f} hours")

    if result_a.rto_hours is not None:
        status = "MISSED" if result_a.rto_mismatch else "MET"
        print(f"RTO:            {result_a.rto_hours:,.2f} hours — {status}")

    if args.explain:
        decision_narrative("A", inputs_a, pricing_a, result_a)

    if args.sensitivity:
        print_sensitivity(
            tier=args.tier,
            destination=args.destination,
            size_gb=args.size_gb,
            rto_hours=args.rto_hours,
        )

    # --- Compare mode (A vs B) ---
    if args.compare:
        if args.compare_tier is None and args.compare_destination is None:
            raise SystemExit(
                "--compare requires --compare-tier and/or --compare-destination"
            )

        tier_b = args.compare_tier or args.tier
        dest_b = args.compare_destination or args.destination

        pricing_b = get_default_pricing(tier_b)
        inputs_b = RestoreInputs(
            data_size_gb=args.size_gb,
            bandwidth_mbps=args.bandwidth_mbps,
            link_efficiency=args.efficiency,
            restore_destination=dest_b,
            rto_hours=args.rto_hours,
        )
        result_b = estimate_restore(inputs_b, pricing_b)

        print("\nComparison (A vs B)")
        print_result_block(
            f"A: {args.tier} → {args.destination}",
            args.tier,
            args.destination,
            result_a,
        )
        print_result_block(f"B: {tier_b} → {dest_b}", tier_b, dest_b, result_b)

        cost_delta = result_b.total_cost_usd - result_a.total_cost_usd
        time_delta = result_b.total_time_hours - result_a.total_time_hours

        print("\nDelta (B - A)")
        print(f"  Cost: {cost_delta:+,.2f}")
        print(f"  Time: {time_delta:+.2f}h")
        if result_a.rto_hours is not None:
            a_status = "MISSED" if result_a.rto_mismatch else "MET"
            b_status = "MISSED" if result_b.rto_mismatch else "MET"
            print(f"  RTO:  A={a_status}  B={b_status}")

        if args.explain:
            decision_narrative("B", inputs_b, pricing_b, result_b)

        if args.break_even:
            months, monthly_savings = compute_break_even_months(
                size_gb=args.size_gb,
                pricing_a=pricing_a,
                pricing_b=pricing_b,
                restore_cost_a=result_a.total_cost_usd,
                restore_cost_b=result_b.total_cost_usd,
            )
            print("\nBreak-even (storage savings vs restore-event cost)")
            print(
                f"  Storage A: ${pricing_a.storage_per_gb_month:.5f}/GB-mo  |  Storage B: ${pricing_b.storage_per_gb_month:.5f}/GB-mo"
            )
            print(f"  Monthly storage savings (A - B): ${monthly_savings:,.2f} / month")

            if months is None:
                print("  Break-even: N/A (B does not reduce monthly storage cost vs A)")
            elif months == 0.0:
                print(
                    "  Break-even: 0 months (B is not more expensive during restore events vs A)"
                )
            else:
                print(
                    f"  Break-even: ~{months:,.1f} months of storage savings to offset restore-event penalty"
                )

    return


if __name__ == "__main__":
    main()
