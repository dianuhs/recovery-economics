# Recovery Economics

Recovery Economics is a decision tool for stress‑testing cloud backup and restore choices.

It focuses on a part of cloud cost optimization that rarely gets modeled with any depth:
**what actually happens when you need your data back**.

Instead of stopping at “this storage tier is cheaper,” Recovery Economics helps answer questions like:

- How long will recovery actually take in a real incident?
- Does that fit within the RTO we’ve committed to?
- How much value is at risk if we miss it?
- How do detection delays change the economics?
- Over time, are storage savings worth the recovery risk?

The output is deterministic, auditable, and intentionally opinionated.  
All assumptions are visible.

---

## Why this exists

Cold storage is often treated as a simple win.
Move data to cheaper tiers, lower the monthly bill, move on.

But recovery is where those decisions get tested.

During a real incident:

- retrieval fees appear
- egress costs matter
- bandwidth and efficiency stop being theoretical
- detection delays compound recovery time
- downtime cost dominates storage savings

Recovery Economics reframes storage optimization as a **risk decision**, not just a cost line item.

---

## What it does

Recovery Economics models the real‑world economics of restoring data from AWS cold storage tiers.

Given a data size, storage tier, and a few operational assumptions, it estimates:

- thaw time
- transfer time
- total restore time
- detection lag and end‑to‑end downtime
- restore‑only RTO vs end‑to‑end RTO
- retrieval and egress costs
- monthly storage cost
- per‑incident downtime loss
- expected downtime loss over a planning horizon

On top of the base model, it supports:

- scenario presets for common failure modes
- side‑by‑side comparison of two decisions
- sensitivity analysis across bandwidth and efficiency
- optional AI‑generated decision narratives
- local decision history with similarity lookup

---

## Scenarios

Built‑in scenarios apply realistic defaults for urgency and recovery conditions:

- `ransomware`
- `region_failure`
- `accidental_delete`
- `test_restore`

All scenario values can be overridden explicitly on the command line.

---

## Core example: ransomware recovery decision

The example below models a ransomware restore of 5 TB from Deep Archive,
then compares it to Glacier.

Assumptions:

- Internet restore
- 2‑hour detection lag
- 24‑hour RTO
- $8,000/hour downtime cost
- One incident every 5 years (0.2/year)
- 3‑year planning horizon

```bash
recovery-economics \
  --tier deep_archive \
  --size-gb 5000 \
  --scenario ransomware \
  --rto-hours 24 \
  --detection-lag-hours 2 \
  --downtime-cost-per-hour 8000 \
  --incident-frequency-per-year 0.2 \
  --planning-horizon-years 3 \
  --compare \
  --compare-tier glacier \
  --destination internet \
  --compare-destination internet
```

### Excerpted output

```text
Total time:     27.87 hours
Detection lag:  2.00 hours
End-to-end downtime: 29.87 hours
RTO (restore-only): 24.00 hours — MISSED
RTO (end-to-end):  24.00 hours — MISSED

Decision Narrative
-----------------
This restore misses your end-to-end RTO by 5.87 hours (29.87h vs 24.00h).
Storage for deep_archive at 5,000 GB is ~$4.95/month.
Downtime cost is modeled at $8,000.00/hour. Estimated value at risk for a single incident with this profile is $46,960.00.
Over a 3.0-year horizon at 0.20 incidents/year, expected downtime loss for this choice is ~$28,176.00.
```

### Comparison insight

```text
Storage: B costs $13.05/month more than A.
Recovery time: B is 8.00h faster.
Downtime impact (per event): B reduces estimated downtime loss by $46,960.00 vs A.
```

This reframes the decision:
cheap storage saves a few dollars per month, but concentrates risk during recovery.

---

## AI decision narrative (optional)

You can layer an AI‑generated explanation on top of the deterministic output:

```bash
recovery-economics ... --ai-narrative
```

The AI narrative:

- explains the tradeoffs already calculated
- does not guess or detect anomalies
- is intentionally narrow and auditable

If the OpenAI client or API key is missing, the tool continues to work without AI output.

---

## Similar decisions (local history)

Each run can be written to a local `history.jsonl` file.

You can ask Recovery Economics to surface similar past decisions based on numeric features:

```bash
recovery-economics ... --ai-similar
```

This helps answer:
“Have we made a decision like this before, and how did it compare?”

---

## Sensitivity analysis

To explore how recovery time changes across assumptions:

```bash
recovery-economics \
  --tier glacier \
  --size-gb 2000 \
  --destination internet \
  --rto-hours 24 \
  --sensitivity
```

This prints a small grid of total restore times, highlighting where RTO is missed.

---

## JSON output

For programmatic use:

```bash
recovery-economics ... --json
```

The JSON output includes all modeled values, including downtime economics and comparison data.

---

## Who this is for

- FinOps practitioners
- Cloud cost and infrastructure engineers
- SRE and reliability teams
- Anyone translating between finance, engineering, and operational risk

Recovery Economics is intentionally focused.
It favors clarity over coverage, and decision quality over dashboards.

It pairs naturally with tools like FinOps Lite and FinOps Watchdog as the **recovery decision layer**.
