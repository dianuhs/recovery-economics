# Recovery Economics

Recovery Economics is a decision tool for stress-testing cloud backup and recovery choices.

It focuses on a part of cloud cost optimization that is usually hand-waved or oversimplified:
**what actually happens when you need your data back**.

Instead of stopping at “this storage tier is cheaper,” Recovery Economics helps answer questions like:

* How long will recovery actually take in a real incident?
* Does that fit within the RTO we’ve committed to?
* How much value is at risk if we miss it?
* How do detection delays change the economics?
* Over time, are storage savings worth the recovery risk?

The output is deterministic, auditable, and intentionally opinionated.
All assumptions are explicit and visible.

---

## Why this exists

Cold storage is often treated as a straightforward win.
Move data to cheaper tiers, lower the monthly bill, move on.

But recovery is where those decisions get tested.

During a real incident:

* retrieval fees appear immediately
* egress costs matter
* bandwidth and efficiency stop being theoretical
* detection delays compound recovery time
* downtime cost dominates storage savings

Recovery Economics reframes storage optimization as a **risk decision**, not just a cost line item.

---

## What it does

Recovery Economics models the real-world economics of restoring data from AWS cold storage tiers.

Given a data size, storage tier, and operational assumptions, it estimates:

* thaw time
* transfer time
* total restore time
* detection lag and end-to-end downtime
* restore-only RTO vs end-to-end RTO
* retrieval and egress costs
* monthly storage cost
* per-incident downtime loss
* expected risk over a planning horizon

On top of the base model, it supports:

* scenario-driven modeling via YAML files
* multiple recovery strategies per scenario
* side-by-side strategy comparison
* deterministic JSON output for automation
* optional AI-generated decision narratives
* local decision history for comparison over time

---

## Scenario-driven modeling

Recovery Economics starts with **business scenarios**, not infrastructure primitives.

Scenarios capture:

* business unit context
* RTO and RPO expectations
* cost per minute of downtime
* detection delay assumptions
* regulatory penalty risk
* incident frequency and planning horizon
* multiple recovery strategies with different tradeoffs

Scenarios are defined as simple YAML files.

Included examples:

* Ransomware impacting a core payments system
* Region-wide cloud outage affecting analytics workloads

---

## Core example: ransomware recovery

```bash
python -m recovery_economics.cli \
  --scenario-file scenarios/ransomware_fast_recovery.yml \
  --compare-strategies
```

```text
Strategy       Tier→Dest                 E2E (h) RTO miss (h)    Downtime/evt    Total risk/evt   Exp risk horizon
------------------------------------------------------------------------------------------------------------------
ai_assisted    glacier→intra_aws            6.94         5.94 $     7,132,000 $       7,732,000         $7,732,000
manual_only    deep_archive→internet       27.14        26.14 $    31,372,000 $      31,972,000        $31,972,000
hybrid         glacier→internet            10.68         9.68 $    11,620,000 $      12,220,000        $12,220,000
```

Manual recovery saves a few dollars per month in storage
but concentrates tens of millions of dollars of risk during an incident.

---

## JSON output

```bash
python -m recovery_economics.cli \
  --scenario-file scenarios/ransomware_fast_recovery.yml \
  --strategy ai_assisted \
  --json
```

---

## AI decision narrative (optional)

```bash
python -m recovery_economics.cli \
  --scenario-file scenarios/ransomware_fast_recovery.yml \
  --strategy ai_assisted \
  --ai-narrative
```

The AI narrative explains only what has already been calculated.
If AI is unavailable, the tool still works normally.

---

## Who this is for

* FinOps practitioners
* Cloud cost and infrastructure engineers
* SRE and reliability teams
* Finance leaders evaluating operational risk

Recovery Economics is intentionally focused.
It favors clarity over coverage, and decision quality over dashboards.

It pairs naturally with FinOps Lite and FinOps Watchdog as the **recovery decision layer**.

