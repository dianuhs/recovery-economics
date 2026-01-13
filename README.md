# Recovery Economics

Recovery Economics is a tool for stress-testing cloud backup and restore decisions.

It focuses on a part of cloud cost optimization that often gets glossed over:  
what actually happens when you need your data back.

---

## Why this exists

Cold storage is usually treated as a straightforward cost win.  
Move data to cheaper tiers, reduce monthly spend, move on.

But recovery is where those decisions get tested.

When an incident happens:

- retrieval fees show up  
- egress costs matter  
- bandwidth and efficiency stop being theoretical  
- recovery time becomes the real constraint  

Recovery Economics makes those tradeoffs explicit so storage decisions can be evaluated as **risk decisions**, not just line items on a bill.

---

## What it does

Recovery Economics models the real-world economics of restoring data from cold storage, including:

- retrieval and egress costs  
- thaw times for cold tiers  
- bandwidth and link efficiency assumptions  
- recovery time versus stated RTO  
- scenario-based defaults that reflect how restores actually happen  
- side-by-side comparison of different choices  
- plain-language decision summaries  

The model is deterministic and auditable. All assumptions are visible.

---

## Example: ransomware restore

```bash
recovery-economics \
  --scenario ransomware \
  --tier deep_archive \
  --size-gb 5000 \
  --compare \
  --compare-tier glacier
```

Excerpt from the output:

```
Decision Narrative
-----------------
This restore misses your RTO by 3.87 hours (27.87h vs 24.00h).
Storage for deep_archive at 5,000 GB is ~$4.95/month.
This is the trade: cheaper storage can quietly turn into slower recovery when you actually need it.

Compare Insights
---------------
Storage: B costs +$13.05/month more than A.
Restore event: B is -$50.00 cheaper than A.
Recovery time: B is -8.00h faster.
```

This reframes storage optimization as a balance between **monthly savings** and **recovery risk**.

---

## Scenarios

The tool includes scenario presets that apply realistic defaults:

- `ransomware`  
- `region_failure`  
- `accidental_delete`  
- `test_restore`  

Each scenario sets expectations for urgency, destination, bandwidth, and efficiency.  
All values can be overridden explicitly.

---

## Comparison mode

Recovery Economics can compare two decisions directly, such as:

- Deep Archive vs Glacier  
- Internet restore vs intra-AWS restore  
- Different bandwidth assumptions  

The comparison highlights:

- cost differences  
- recovery time differences  
- RTO impact  
- how storage savings compare to recovery penalties  

This makes it easier to answer a simple question:  
**was the savings worth it?**

---

## Who this is for

- FinOps practitioners  
- cloud cost and infrastructure engineers  
- teams thinking about backup, DR, and recovery planning  
- anyone translating between finance, engineering, and operational risk  

---

## Project status

This is an intentionally focused project.

The goal is clarity, not coverage.  
Depth over breadth.
