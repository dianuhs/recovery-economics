# Recovery Economics (v1)

A small, auditable FinOps model that estimates **restore cost and restore time**
for archival storage recovery.

This project is intentionally **not** a dashboard and **not** a cloud connection tool.
It is a decision-stress model that answers a simple but commonly missed question:

> What does this storage decision cost when you actually need the data back?

---

## Why this exists

Storage optimization is heavily modeled in cloud cost management.
The **cost of recovery** and **time-to-restore** are usually not modeled until a real
incident forces the math.

This leads teams to optimize for low $/GB while quietly accepting:
- long restore times
- unexpected egress bills
- missed RTOs during incidents

Recovery Economics makes those tradeoffs explicit **before** a failure occurs.

---

## What v1 does

- Models AWS restore scenarios for:
  - `glacier`
  - `deep_archive`
- Supports two restore destinations:
  - `internet` (Data Transfer Out, max-pain baseline)
  - `intra_aws` (simplified baseline)
- Calculates:
  - retrieval cost
  - egress cost
  - total restore cost
  - thaw time
  - transfer time (with link efficiency)
  - total time to availability
  - optional RTO mismatch

---

## What v1 intentionally does NOT do

- No cloud authentication (IAM, OIDC, API keys)
- No live account connections
- No multi-cloud claims
- No dashboards or UI
- No optimization recommendations

v1 focuses on modeling **consequences**, not managing infrastructure.

---

## Install (development)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

---

## Run

Example: restore **5 TB** from Deep Archive to the Internet over a **1 Gbps** link,
assuming **70% efficiency** and a **24-hour RTO**.

```bash
recovery-economics \
  --tier deep_archive \
  --destination internet \
  --size-gb 5000 \
  --bandwidth-mbps 1000 \
  --efficiency 0.70 \
  --rto-hours 24
```

JSON output:

```bash
recovery-economics \
  --tier deep_archive \
  --destination internet \
  --size-gb 5000 \
  --bandwidth-mbps 1000 \
  --rto-hours 24 \
  --json
```

---

## Assumptions (v1)

- Transfer time uses effective throughput:
  `bandwidth_mbps × link_efficiency`
- v1 approximates `1 GB = 1e9 bytes` for clarity and auditability
- Pricing defaults are explicit in code and overrideable

---

## Tests

```bash
pytest
```

---

## Roadmap

This project is intentionally narrow. Future iterations will stay focused on
**auditable, decision-oriented modeling**, not platform features.

Planned improvements:
- Replace pricing defaults with sourced AWS tier and region tables
- Add request-level cost components where applicable
- Add a simple sensitivity view (bandwidth and efficiency ranges)
- Expand Recovery Economics beyond restore scenarios to other high-risk cost events

