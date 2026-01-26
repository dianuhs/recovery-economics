
from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .aws_pricing import AwsRestorePricing, get_default_pricing
from .model import RestoreInputs, estimate_restore


SCENARIOS: Dict[str, Dict[str, Any]] = {
    "ransomware": {
        "destination": "internet",
        "bandwidth_mbps": 1000.0,
        "efficiency": 0.70,
        "rto_hours": 24.0,
        # Optional: you can add a detection lag default here later if you want
        # "detection_lag_hours": 2.0,
    },
    "region_failure": {
        "destination": "internet",
        "bandwidth_mbps": 500.0,
        "efficiency": 0.60,
        "rto_hours": 48.0,
    },
    "accidental_delete": {
        "destination": "intra_aws",
        "bandwidth_mbps": 2000.0,
        "efficiency": 0.85,
        "rto_hours": 8.0,
    },
    "test_restore": {
        "destination": "intra_aws",
        "bandwidth_mbps": 500.0,
        "efficiency": 0.80,
        "rto_hours": None,
    },
}

HISTORY_FILE = pathlib.Path("history.jsonl")


# ---------- Small helpers ----------


def _usd_delta_label(delta: float) -> str:
    sign = "+" if delta > 0 else "-" if delta < 0 else ""
    return f"{sign}${abs(delta):,.2f}"


def _hours_delta_label(delta: float) -> str:
    sign = "+" if delta > 0 else "-" if delta < 0 else ""
    return f"{sign}{abs(delta):.2f}h"


def _compute_downtime_loss(
    total_time_hours: float,
    detection_lag_hours: float,
    rto_hours: Optional[float],
    downtime_cost_per_hour: Optional[float],
) -> Tuple[float, float, float]:
    """Return (rto_miss_hours, estimated_downtime_loss_usd, end_to_end_downtime_hours).

    End-to-end downtime is modeled as detection lag + restore time.
    If RTO or downtime_cost_per_hour is missing, this returns zeros for miss and loss.
    """
    detection = max(0.0, detection_lag_hours or 0.0)
    end_to_end = total_time_hours + detection

    if rto_hours is None or downtime_cost_per_hour is None:
        return 0.0, 0.0, end_to_end

    miss = max(0.0, end_to_end - rto_hours)
    loss = miss * downtime_cost_per_hour
    return miss, loss, end_to_end


def log_decision(record: Dict[str, Any]) -> None:
    """Append a single decision record to history.jsonl.

    This never breaks the CLI: failures are logged to stderr and ignored.
    """
    try:
        with HISTORY_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Failed to write history: {exc}", file=sys.stderr)


def load_history() -> List[Dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []
    records: List[Dict[str, Any]] = []
    with HISTORY_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _feature_vector(rec: Dict[str, Any]) -> List[float]:
    return [
        float(rec.get("size_gb", 0.0)),
        float(rec.get("bandwidth_mbps") or 0.0),
        float(rec.get("efficiency") or 0.0),
        float(rec.get("rto_hours") or 0.0),
        float(rec.get("total_time_hours") or 0.0),
        float(rec.get("end_to_end_downtime_hours") or 0.0),
        float(rec.get("rto_miss_hours") or 0.0),
        float(rec.get("total_cost_usd") or 0.0),
        float(rec.get("monthly_storage_usd") or 0.0),
        float(rec.get("downtime_cost_per_hour") or 0.0),
        float(rec.get("estimated_downtime_loss_usd") or 0.0),
        float(rec.get("incident_frequency_per_year") or 0.0),
        float(rec.get("planning_horizon_years") or 0.0),
        float(rec.get("expected_downtime_loss_usd") or 0.0),
    ]


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def find_similar_decisions(
    current: Dict[str, Any],
    k: int = 3,
) -> List[Tuple[Dict[str, Any], float]]:
    history = load_history()
    if not history:
        return []

    current_vec = _feature_vector(current)
    scored: List[Tuple[Dict[str, Any], float]] = []
    for rec in history:
        vec = _feature_vector(rec)
        sim = _cosine_similarity(current_vec, vec)
        scored.append((rec, sim))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [x for x in scored[:k] if x[1] > 0.0]


def print_similar_decisions(similars: List[Tuple[Dict[str, Any], float]]) -> None:
    print("\nSimilar Decisions (local history)")
    print("---------------------------------")
    if not similars:
        print("No prior decisions found in local history.")
        return

    for rec, score in similars:
        scenario = rec.get("scenario")
        tier = rec.get("tier")
        destination = rec.get("destination")
        size_gb = rec.get("size_gb") or 0.0
        rto_miss = rec.get("rto_miss_hours")
        est_loss = rec.get("estimated_downtime_loss_usd")
        exp_loss = rec.get("expected_downtime_loss_usd")
        ts = rec.get("timestamp")
        compare = rec.get("compare") or {}
        alt_tier = compare.get("alt_tier")
        alt_destination = compare.get("alt_destination")

        # Handle None values gracefully for printing
        rto_miss_str = (
            f"{rto_miss:.2f}h" if isinstance(rto_miss, (int, float)) else "n/a"
        )
        est_loss_str = (
            f"${est_loss:,.2f}" if isinstance(est_loss, (int, float)) else "n/a"
        )
        exp_loss_str = (
            f"${exp_loss:,.2f}" if isinstance(exp_loss, (int, float)) else "n/a"
        )

        print(
            f"* [{score:.2f} similarity] {scenario} | {size_gb:,.0f} GB | "
            f"{tier} → {destination} vs {alt_tier or 'n/a'} → {alt_destination or 'n/a'} | "
            f"RTO miss (per event): {rto_miss_str} | "
            f"downtime loss (per event): {est_loss_str} | "
            f"expected loss over horizon: {exp_loss_str} | "
            f"{ts}"
        )


# ---------- CLI construction ----------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="recovery-economics")

    p.add_argument("--tier", required=True, choices=["glacier", "deep_archive"])
    p.add_argument("--size-gb", required=True, type=float)

    p.add_argument("--destination", choices=["internet", "intra_aws"])
    p.add_argument("--bandwidth-mbps", type=float)
    p.add_argument("--efficiency", type=float)
    p.add_argument("--rto-hours", type=float)

    p.add_argument("--scenario", choices=SCENARIOS.keys())
    p.add_argument("--json", action="store_true")
    p.add_argument("--sensitivity", action="store_true")

    p.add_argument("--compare", action="store_true")
    p.add_argument("--compare-tier", choices=["glacier", "deep_archive"])
    p.add_argument("--compare-destination", choices=["internet", "intra_aws"])

    # Downtime economics + AI + history
    p.add_argument(
        "--downtime-cost-per-hour",
        type=float,
        help="Estimated cost of downtime per hour (e.g. 8000 for $8,000/h).",
    )
    p.add_argument(
        "--incident-frequency-per-year",
        type=float,
        help="Expected incident frequency per year for this scenario (e.g. 0.2 for one every 5 years).",
    )
    p.add_argument(
        "--planning-horizon-years",
        type=float,
        help="Planning horizon in years for expected downtime loss (e.g. 3).",
    )
    p.add_argument(
        "--detection-lag-hours",
        type=float,
        help="Assumed lag between incident start and detection (hours).",
    )
    p.add_argument(
        "--ai-narrative",
        action="store_true",
        help="Use an LLM to generate an executive-style decision narrative.",
    )
    p.add_argument(
        "--ai-similar",
        action="store_true",
        help="Look up similar past decisions from local history.",
    )
    p.add_argument(
        "--no-history",
        action="store_true",
        help="Do not write this decision to local history.",
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


# ---------- AI narrative ----------


def generate_ai_narrative(
    base_record: Dict[str, Any],
    compare_record: Optional[Dict[str, Any]],
) -> Optional[str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except ImportError:
        return None

    client = OpenAI(api_key=api_key)

    system_prompt = (
        "You are writing for a FinOps and cloud reliability audience under the Cloud & Capital brand.\n"
        "You are given JSON with recovery metrics for one restore decision, and sometimes a comparison.\n"
        "Write 3–4 sentences in a calm, practitioner voice. Be specific about RTO hit or miss, total recovery time, "
        "monthly storage tradeoffs, and the rough order of magnitude of downtime risk.\n"
        "Do not use buzzwords, do not talk about yourself, do not say things like 'in today's world' or similar filler. "
        "Sound like a senior engineer or FinOps lead explaining the trade to a CFO and an SRE in the same room."
    )

    payload: Dict[str, Any] = {"base": base_record}
    if compare_record is not None:
        payload["compare"] = compare_record

    try:
        resp = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, indent=2)},
            ],
            max_tokens=300,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] AI narrative generation failed: {exc}", file=sys.stderr)
        return None


# ---------- Main flow ----------


def main() -> None:
    args = build_parser().parse_args()

    scenario_defaults: Dict[str, Any] = {}
    if args.scenario:
        scenario_defaults = SCENARIOS[args.scenario]

    destination = args.destination or scenario_defaults.get("destination")
    bandwidth = args.bandwidth_mbps or scenario_defaults.get("bandwidth_mbps")
    efficiency = args.efficiency or scenario_defaults.get("efficiency", 0.7)
    rto_hours = (
        args.rto_hours
        if args.rto_hours is not None
        else scenario_defaults.get("rto_hours")
    )
    detection_lag_hours = (
        args.detection_lag_hours
        if args.detection_lag_hours is not None
        else scenario_defaults.get("detection_lag_hours", 0.0)
    )

    pricing_a: AwsRestorePricing = get_default_pricing(args.tier)

    inputs_a = RestoreInputs(
        data_size_gb=args.size_gb,
        bandwidth_mbps=bandwidth,
        link_efficiency=efficiency,
        restore_destination=destination,
        rto_hours=rto_hours,
    )

    result_a = estimate_restore(inputs_a, pricing_a)
    monthly_storage_a = args.size_gb * pricing_a.storage_per_gb_month

    # Downtime economics for A (per event, end-to-end)
    rto_miss_a, downtime_loss_a, end_to_end_a = _compute_downtime_loss(
        result_a.total_time_hours,
        detection_lag_hours,
        rto_hours,
        args.downtime_cost_per_hour,
    )

    # Expected loss over a planning horizon (A)
    expected_loss_a: float = 0.0
    if (
        args.incident_frequency_per_year is not None
        and args.planning_horizon_years is not None
        and args.downtime_cost_per_hour is not None
    ):
        expected_loss_a = (
            downtime_loss_a
            * args.incident_frequency_per_year
            * args.planning_horizon_years
        )

    compare_present = False
    tier_b: Optional[str] = None
    dest_b: Optional[str] = None
    result_b = None
    monthly_storage_b: Optional[float] = None
    rto_miss_b: float = 0.0
    downtime_loss_b: float = 0.0
    end_to_end_b: float = 0.0
    expected_loss_b: float = 0.0

    if args.compare:
        compare_present = True
        tier_b = args.compare_tier or args.tier
        dest_b = args.compare_destination or destination

        pricing_b = get_default_pricing(tier_b)
        inputs_b = RestoreInputs(
            data_size_gb=args.size_gb,
            bandwidth_mbps=bandwidth,
            link_efficiency=efficiency,
            restore_destination=dest_b,
            rto_hours=rto_hours,
        )
        result_b = estimate_restore(inputs_b, pricing_b)
        monthly_storage_b = args.size_gb * pricing_b.storage_per_gb_month

        rto_miss_b, downtime_loss_b, end_to_end_b = _compute_downtime_loss(
            result_b.total_time_hours,
            detection_lag_hours,
            rto_hours,
            args.downtime_cost_per_hour,
        )

        if (
            args.incident_frequency_per_year is not None
            and args.planning_horizon_years is not None
            and args.downtime_cost_per_hour is not None
        ):
            expected_loss_b = (
                downtime_loss_b
                * args.incident_frequency_per_year
                * args.planning_horizon_years
            )

    # JSON mode
    if args.json:
        payload: Dict[str, Any] = {
            "scenario": args.scenario,
            "inputs": asdict(inputs_a),
            "pricing": asdict(pricing_a),
            "result": asdict(result_a),
            "monthly_storage_usd": monthly_storage_a,
            "downtime_cost_per_hour": args.downtime_cost_per_hour,
            "rto_miss_hours": rto_miss_a,
            "estimated_downtime_loss_usd": downtime_loss_a,
            "detection_lag_hours": detection_lag_hours,
            "end_to_end_downtime_hours": end_to_end_a,
            "incident_frequency_per_year": args.incident_frequency_per_year,
            "planning_horizon_years": args.planning_horizon_years,
            "expected_downtime_loss_usd": expected_loss_a,
        }
        if compare_present and result_b is not None:
            payload["compare"] = {
                "tier_b": tier_b,
                "destination_b": dest_b,
                "pricing_b": asdict(get_default_pricing(tier_b)),
                "result_b": asdict(result_b),
                "monthly_storage_b_usd": monthly_storage_b,
                "rto_miss_b_hours": rto_miss_b,
                "estimated_downtime_loss_b_usd": downtime_loss_b,
                "end_to_end_downtime_b_hours": end_to_end_b,
                "expected_downtime_loss_b_usd": expected_loss_b,
            }

        print(json.dumps(payload, indent=2))
        if not args.no_history:
            base_record = _build_history_record(
                args=args,
                destination=destination,
                result_a=result_a,
                monthly_storage_a=monthly_storage_a,
                detection_lag_hours=detection_lag_hours,
                end_to_end_a=end_to_end_a,
                rto_miss_a=rto_miss_a,
                downtime_loss_a=downtime_loss_a,
                expected_loss_a=expected_loss_a,
                compare_present=compare_present,
                tier_b=tier_b,
                dest_b=dest_b,
                result_b=result_b,
                monthly_storage_b=monthly_storage_b,
                end_to_end_b=end_to_end_b,
                rto_miss_b=rto_miss_b,
                downtime_loss_b=downtime_loss_b,
                expected_loss_b=expected_loss_b,
            )
            log_decision(base_record)
        return

    # Human-readable output
    print(f"Recovery Economics — AWS Restore Stress Test ({args.tier})")
    if args.scenario:
        print(f"Scenario: {args.scenario}")
    print(f"Destination: {destination}\n")

    print(f"Retrieval cost: ${result_a.retrieval_cost_usd:,.2f}")
    print(f"Egress cost:    ${result_a.egress_cost_usd:,.2f}")
    print(f"Total cost:     ${result_a.total_cost_usd:,.2f}\n")

    print(f"Thaw time:      {result_a.thaw_time_hours:,.2f} hours")
    print(f"Transfer time:  {result_a.transfer_time_hours:,.2f} hours")
    print(f"Total time:     {result_a.total_time_hours:,.2f} hours")

    if detection_lag_hours:
        print(f"Detection lag:  {detection_lag_hours:,.2f} hours")
        print(f"End-to-end downtime: {end_to_end_a:,.2f} hours")

    if rto_hours is not None:
        status = "MISSED" if result_a.rto_mismatch else "MET"
        print(f"RTO (restore-only): {rto_hours:,.2f} hours — {status}")
        if detection_lag_hours:
            end_to_end_status = "MISSED" if end_to_end_a > rto_hours else "MET"
            print(
                f"RTO (end-to-end):  {rto_hours:,.2f} hours — {end_to_end_status}"
            )

    print("\nDecision Narrative")
    print("-----------------")

    if rto_hours is not None and args.downtime_cost_per_hour is not None:
        if rto_miss_a > 0:
            print(
                f"This restore misses your end-to-end RTO by {rto_miss_a:,.2f} hours "
                f"({end_to_end_a:,.2f}h vs {rto_hours:,.2f}h)."
            )
        else:
            headroom = max(0.0, rto_hours - end_to_end_a)
            print(
                f"This restore meets your end-to-end RTO with {headroom:,.2f} hours of headroom "
                f"({end_to_end_a:,.2f}h vs {rto_hours:,.2f}h)."
            )

    monthly_storage_msg = (
        f"Storage for {args.tier} at {args.size_gb:,.0f} GB is ~${monthly_storage_a:,.2f}/month."
    )
    print(monthly_storage_msg)

    if args.downtime_cost_per_hour is not None and rto_hours is not None:
        print(
            f"Downtime cost is modeled at ${args.downtime_cost_per_hour:,.2f}/hour. "
            f"Estimated value at risk for a single incident with this profile is ${downtime_loss_a:,.2f}."
        )
        if expected_loss_a > 0:
            print(
                f"Over a {args.planning_horizon_years:.1f}-year horizon at "
                f"{args.incident_frequency_per_year:.2f} incidents/year, "
                f"expected downtime loss for this choice is ~${expected_loss_a:,.2f}."
            )

    print(
        "This is the trade: cheaper storage can quietly turn into slower recovery and higher downtime "
        "when you actually need it."
    )

    if args.sensitivity:
        print_sensitivity(args.tier, destination, args.size_gb, rto_hours)

    # Comparison block
    if compare_present and result_b is not None and monthly_storage_b is not None:
        print("\nComparison (A vs B)")
        print(f"A: {args.tier} → {destination}")
        print(
            f"  Total cost: ${result_a.total_cost_usd:,.2f}  "
            f"(retrieval ${result_a.retrieval_cost_usd:,.2f}, egress ${result_a.egress_cost_usd:,.2f})"
        )
        print(
            f"  Total time: {result_a.total_time_hours:.2f}h  "
            f"(thaw {result_a.thaw_time_hours:.2f}h, transfer {result_a.transfer_time_hours:.2f}h)"
        )
        if detection_lag_hours:
            print(
                f"  End-to-end downtime: {end_to_end_a:.2f}h "
                f"(including {detection_lag_hours:.2f}h detection lag)"
            )

        print(f"B: {tier_b} → {dest_b}")
        print(
            f"  Total cost: ${result_b.total_cost_usd:,.2f}  "
            f"(retrieval ${result_b.retrieval_cost_usd:,.2f}, egress ${result_b.egress_cost_usd:,.2f})"
        )
        print(
            f"  Total time: {result_b.total_time_hours:.2f}h  "
            f"(thaw {result_b.thaw_time_hours:.2f}h, transfer {result_b.transfer_time_hours:.2f}h)"
        )
        if detection_lag_hours:
            print(
                f"  End-to-end downtime: {end_to_end_b:.2f}h "
                f"(including {detection_lag_hours:.2f}h detection lag)"
            )

        storage_delta = monthly_storage_b - monthly_storage_a
        cost_delta = result_b.total_cost_usd - result_a.total_cost_usd
        time_delta = result_b.total_time_hours - result_a.total_time_hours

        print("\nCompare Insights")
        print("---------------")

        if abs(storage_delta) < 1e-9:
            print("Storage: same monthly cost.")
        elif storage_delta < 0:
            print(f"Storage: B saves ${abs(storage_delta):,.2f}/month vs A.")
        else:
            print(
                f"Storage: B costs ${storage_delta:,.2f}/month more than A."
            )

        if abs(cost_delta) < 1e-9:
            print("Restore event: same cost.")
        elif cost_delta < 0:
            print(
                f"Restore event: B is ${abs(cost_delta):,.2f} cheaper than A."
            )
        else:
            print(
                f"Restore event: B is ${cost_delta:,.2f} more expensive than A."
            )

        if abs(time_delta) < 1e-9:
            print("Recovery time: same.")
        elif time_delta < 0:
            print(f"Recovery time: B is {abs(time_delta):.2f}h faster.")
        else:
            print(f"Recovery time: B is {time_delta:.2f}h slower.")

        if args.downtime_cost_per_hour is not None and rto_hours is not None:
            downtime_delta = downtime_loss_b - downtime_loss_a
            if abs(downtime_delta) < 1e-9:
                print("Downtime impact (per event): same estimated value at risk.")
            elif downtime_delta < 0:
                print(
                    f"Downtime impact (per event): B reduces estimated downtime loss by "
                    f"${abs(downtime_delta):,.2f} vs A."
                )
            else:
                print(
                    f"Downtime impact (per event): B increases estimated downtime loss by "
                    f"${downtime_delta:,.2f} vs A."
                )

            if expected_loss_a > 0 and expected_loss_b > 0:
                expected_delta = expected_loss_b - expected_loss_a
                if abs(expected_delta) < 1e-9:
                    print(
                        "Downtime impact (expected over horizon): same expected downtime loss."
                    )
                elif expected_delta < 0:
                    print(
                        f"Downtime impact (expected): B reduces expected downtime loss over the planning horizon "
                        f"by ${abs(expected_delta):,.2f} vs A."
                    )
                else:
                    print(
                        f"Downtime impact (expected): B increases expected downtime loss over the planning horizon "
                        f"by ${expected_delta:,.2f} vs A."
                    )

    # Base record for AI + history
    base_record: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scenario": args.scenario,
        "tier": args.tier,
        "destination": destination,
        "size_gb": args.size_gb,
        "bandwidth_mbps": bandwidth,
        "efficiency": efficiency,
        "rto_hours": rto_hours,
        "total_time_hours": result_a.total_time_hours,
        "end_to_end_downtime_hours": end_to_end_a,
        "rto_miss_hours": rto_miss_a,
        "total_cost_usd": result_a.total_cost_usd,
        "monthly_storage_usd": monthly_storage_a,
        "downtime_cost_per_hour": args.downtime_cost_per_hour,
        "estimated_downtime_loss_usd": downtime_loss_a,
        "detection_lag_hours": detection_lag_hours,
        "incident_frequency_per_year": args.incident_frequency_per_year,
        "planning_horizon_years": args.planning_horizon_years,
        "expected_downtime_loss_usd": expected_loss_a,
    }

    compare_record: Optional[Dict[str, Any]] = None
    if compare_present and result_b is not None and monthly_storage_b is not None:
        compare_record = {
            "tier": tier_b,
            "destination": dest_b,
            "total_time_hours": result_b.total_time_hours,
            "end_to_end_downtime_hours": end_to_end_b,
            "rto_miss_hours": rto_miss_b,
            "total_cost_usd": result_b.total_cost_usd,
            "monthly_storage_usd": monthly_storage_b,
            "estimated_downtime_loss_usd": downtime_loss_b,
            "expected_downtime_loss_usd": expected_loss_b,
        }

    # AI narrative (optional)
    if args.ai_narrative:
        ai_text = generate_ai_narrative(base_record, compare_record)
        print("\nAI Decision Narrative")
        print("---------------------")
        if ai_text:
            print(ai_text)
        else:
            print("AI narrative not available (missing client or API key).")

    # Similar decisions (numeric similarity over history)
    if args.ai_similar:
        similars = find_similar_decisions(base_record)
        print_similar_decisions(similars)

    # Log to history unless disabled
    if not args.no_history:
        if compare_present and compare_record is not None:
            hist = dict(base_record)
            hist["compare"] = {
                "alt_tier": compare_record["tier"],
                "alt_destination": compare_record["destination"],
                "alt_total_time_hours": compare_record["total_time_hours"],
                "alt_end_to_end_downtime_hours": compare_record[
                    "end_to_end_downtime_hours"
                ],
                "alt_total_cost_usd": compare_record["total_cost_usd"],
                "alt_monthly_storage_usd": compare_record["monthly_storage_usd"],
                "alt_estimated_downtime_loss_usd": compare_record[
                    "estimated_downtime_loss_usd"
                ],
                "alt_expected_downtime_loss_usd": compare_record[
                    "expected_downtime_loss_usd"
                ],
            }
            log_decision(hist)
        else:
            log_decision(base_record)


def _build_history_record(
    args: argparse.Namespace,
    destination: str,
    result_a: Any,
    monthly_storage_a: float,
    detection_lag_hours: float,
    end_to_end_a: float,
    rto_miss_a: float,
    downtime_loss_a: float,
    expected_loss_a: float,
    compare_present: bool,
    tier_b: Optional[str],
    dest_b: Optional[str],
    result_b: Optional[Any],
    monthly_storage_b: Optional[float],
    end_to_end_b: float,
    rto_miss_b: float,
    downtime_loss_b: float,
    expected_loss_b: float,
) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scenario": args.scenario,
        "tier": args.tier,
        "destination": destination,
        "size_gb": args.size_gb,
        "bandwidth_mbps": args.bandwidth_mbps
        or SCENARIOS.get(args.scenario or "", {}).get("bandwidth_mbps"),
        "efficiency": args.efficiency
        or SCENARIOS.get(args.scenario or "", {}).get("efficiency", 0.7),
        "rto_hours": args.rto_hours
        if args.rto_hours is not None
        else SCENARIOS.get(args.scenario or "", {}).get("rto_hours"),
        "total_time_hours": result_a.total_time_hours,
        "end_to_end_downtime_hours": end_to_end_a,
        "rto_miss_hours": rto_miss_a,
        "total_cost_usd": result_a.total_cost_usd,
        "monthly_storage_usd": monthly_storage_a,
        "downtime_cost_per_hour": args.downtime_cost_per_hour,
        "estimated_downtime_loss_usd": downtime_loss_a,
        "detection_lag_hours": detection_lag_hours,
        "incident_frequency_per_year": args.incident_frequency_per_year,
        "planning_horizon_years": args.planning_horizon_years,
        "expected_downtime_loss_usd": expected_loss_a,
    }

    if compare_present and result_b is not None and monthly_storage_b is not None:
        record["compare"] = {
            "alt_tier": tier_b,
            "alt_destination": dest_b,
            "alt_total_time_hours": result_b.total_time_hours,
            "alt_end_to_end_downtime_hours": end_to_end_b,
            "alt_rto_miss_hours": rto_miss_b,
            "alt_total_cost_usd": result_b.total_cost_usd,
            "alt_monthly_storage_usd": monthly_storage_b,
            "alt_estimated_downtime_loss_usd": downtime_loss_b,
            "alt_expected_downtime_loss_usd": expected_loss_b,
        }

    return record


if __name__ == "__main__":
    main()
