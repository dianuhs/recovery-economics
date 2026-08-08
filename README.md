# Recovery Economics

Recovery Economics is an open-source resilience scenario and evidence engine. It models the economics of protecting and recovering a workload, tests modeled RTO/RPO against declared targets, and distinguishes scenario estimates from observed restore-test evidence.

For the complete six-tool demo and roadmap, see [Tech Spend Command Center](https://github.com/cloudandcapital/tech-spend-command-center).

It does not inspect cloud accounts, mutate infrastructure, prove recoverability from assumptions, or add modeled resilience costs to observed technology spend.

## What v0.3 calculates

- Full plus incremental protected-storage footprint
- Compression and deduplication effects
- Backup request and storage design cost
- Retrieval, compute, egress, failover, and failback cost per recovery event
- Frequency-weighted monthly recovery execution cost
- Modeled recovery time and backup interval versus RTO/RPO targets
- Frequency-weighted monthly outage exposure
- Low, expected, and high sensitivity values
- Restore-test evidence, freshness, and demonstrated target gaps

All scenario-derived financial metrics use `basis: estimated`. Supplied restore-test duration and recovered-point age use `basis: observed`. Neither is called verified savings.

The public demo is credential-free and uses entirely illustrative data.

## Install the released CLI

Python 3.10 or newer is required.

```bash
pipx install "git+https://github.com/cloudandcapital/recovery-economics.git@v0.2.1"
recovery-economics --help
```

For development from a clone:

```bash
python -m pip install -e ".[dev]"
```

## Five-minute public demo

```bash
recovery-economics ccac --demo --output recovery-result.json
```

CCAC 1.0 remains the default. Select the diagnostic-only CCAC 1.1 bridge
explicitly when assembling a future unified run:

```bash
recovery-economics ccac --demo --contract-version 1.1.0 --output recovery-result-1.1.json
```

The command writes `recovery-result.json`; rerunning with the same path
replaces that explicitly named local file.

The acceptance suite validates this result against the shared CCAC reference schemas. Contributors may run `ccac validate recovery-result.json` after installing the separate CCAC reference package.

**Illustrative sample resilience data. No customer accounts, credentials, billing exports, or production resources are connected.**

The demo is deterministic and passes through the same calculator and CCAC producer as a local user scenario.

## Analyze a local scenario

```bash
recovery-economics ccac \
  --input examples/scenario-v2.yml \
  --output recovery-result.json
```

Compare two strategies for the same workload:

```bash
recovery-economics compare-ccac \
  --baseline examples/scenario-v2.yml \
  --proposed examples/scenario-v2-proposed.yml \
  --output comparison.json
```

The comparison reports baseline, proposed, and delta exposure alongside target-coverage regressions. A favorable modeled delta is not emitted as verified savings or an optimization opportunity.

Input is file-first and read-only. YAML and JSON are supported. Required sections are:

- `workload`: identity, criticality, data size, RTO, and RPO
- `backup`: frequency, retention, full-backup interval, daily change, reduction ratios, storage and request rates
- `recovery`: restore volume and throughput, retrieval, compute, egress, failover, failback, and orchestration assumptions
- `risk`: event frequency, outage impact, and uncertainty
- `restore_test`: optional observed test timestamp, duration, recovered-point age, and result

Required numeric values never default to zero. Missing, non-numeric, negative, NaN, infinite, or out-of-range values fail closed.

Rates are supplied explicitly by the user. Recovery Economics does not perform live cloud-pricing lookups; the older `aws_pricing.py` module contains legacy starter assumptions and is not used by the canonical model.

## Core formulas

```text
effective stored GB =
  (data GB × retained full copies
   + data GB × daily change % × max(retention days - retained full copies, 0))
  × compression ratio × deduplication ratio

monthly design cost =
  effective stored GB × storage rate
  + monthly backup operations × request cost

modeled RTO =
  restore GB ÷ throughput + orchestration hours + compute hours

recovery-event cost =
  retrieval + restore compute + egress + failover + failback

expected monthly outage exposure =
  modeled RTO × outage impact per hour × annual recovery events ÷ 12
```

Each retained full copy represents one full-backup day. Daily changed data is
modeled for the remaining retained days; the model does not simulate a more
granular backup schedule within those days.

Every formula and assumption is also included in the CCAC extension for auditability.

## Accounting boundary

`monthly_design_cost`, `expected_monthly_recovery_cost`, `expected_monthly_outage_exposure`, and `expected_monthly_economic_exposure` are scenario estimates. They are not invoices and must not enter canonical technology-spend totals.

Recovery Economics emits findings, but no optimization opportunities or remediation commands. A later comparison workflow may propose review-first alternatives with explicit overlap and approval controls.

## Restore-test interpretation

- Modeled RTO/RPO never demonstrate recoverability.
- A fresh passing restore test is evidence of that test only, not a permanent guarantee.
- Evidence older than 90 days is labeled stale.
- Failed, partial, missing, stale, or future-dated evidence cannot substantiate recoverability.
- Observed test duration and recovered-point age are compared directly with declared targets.

## Legacy CSV compatibility

The v0.1 commands remain available:

```bash
recovery-economics analyze --input examples/workload-config-sample.csv --output-format json
recovery-economics compare --baseline current.csv --proposed proposed.csv
```

The legacy formula treats each retained backup as a full copy and is intentionally not the canonical v0.2 pipeline model. Legacy comparisons now require identical workload sets; missing rows are not interpreted as `$0`.

## Pipeline compatibility

Recovery Economics `0.3.x` supports explicit `ccac/1.0.0` and `ccac/1.1.0`
standard diagnostic tool results. CCAC 1.0 remains the default for
compatibility, and `compare-ccac` remains CCAC 1.0 only. The standard 1.1 path
is a diagnostic bridge for a future unified pipeline: its run-level period can
align with that pipeline while modeled metrics retain an explicit monthly
horizon and observed restore-test metrics retain their observation-day period.
Recovery Economics contributes no Cloud, direct-AI, SaaS, or total technology
spend.

The tool reads only illustrative or user-supplied local files. It does not
inspect accounts, mutate infrastructure, query billing exports or provider
APIs, perform live pricing lookups, or prove recoverability. Tech Spend Command
Center `0.2.x` continues to support the existing CCAC 1.0 pipeline; CCAC 1.1
Command Center integration is a separate later phase.

## Development

```bash
uv run --extra dev pytest
```

## License

MIT © 2025–2026 Diana Molski, Cloud & Capital
