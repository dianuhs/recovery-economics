# Changelog

All notable changes to Recovery Economics are documented here.

## [Unreleased]

## [0.3.0] — 2026-08-07

- Add explicit CCAC 1.0 and diagnostic-only CCAC 1.1 output while retaining
  CCAC 1.0 as the default and preserving the approved legacy demonstration
  byte-for-byte.
- Keep the CCAC 1.1 document period aligned with the future pipeline while
  labeling scenario estimates with their monthly modeled period and observed
  restore-test metrics with their observation-day period.
- Preserve Recovery Economics as a partial, total-ineligible diagnostic
  producer with no canonical technology-spend metrics or opportunities.
- Add fail-closed output reconciliation and exact released-CCAC validation.
- Keep `compare-ccac` limited to its established CCAC 1.0 behavior.
- Use Hatchling because fixed-epoch A/B builds with the original setuptools
  backend produced identical wheels but nondeterministic sdists; Hatchling
  makes both artifact types byte-reproducible.

## [0.2.1] — 2026-08-05

- Correct the public CLI help identity with version-neutral wording and advance
  package version surfaces to `0.2.1`.
- This release does not alter calculations, modeling, CCAC structure, trust
  behavior, or remediation semantics.

## [0.2.0] — 2026-08-04

- Add a standard `recovery-economics --version` installation smoke check.
- Correct event-frequency terminology and align the documented protected-storage formula with the canonical implementation.

### Added
- Versioned `recovery-economics/2.0` YAML/JSON scenario input.
- Deterministic `ccac --demo` and read-only local `ccac --input` paths.
- Full/incremental storage, reduction ratios, requests, retrieval, compute, egress, failover/failback, RTO/RPO, frequency-weighted exposure, sensitivity, and restore-test evidence modeling.
- CCAC `tool_result` output with source hash, formulas, assumptions, evidence freshness, findings, and explicit accounting boundary.
- Canonical `compare-ccac` baseline/proposed strategy analysis with target-regression findings and estimated deltas that remain outside verified savings.

### Corrected
- Reject empty CSVs, duplicate workload identifiers, NaN/infinity, and mismatched comparison workload sets.
- Replaced unsupported README claims with tested commands and explicit legacy boundaries.
- Classified pre-v0.2 scenario YAML files as incompatible research inputs rather than executable examples.

### Added
- **`compare` subcommand** — `recovery-economics compare --baseline a.csv --proposed b.csv` loads both scenario CSVs, computes per-workload monthly costs, and prints a side-by-side table with delta sorted by absolute change and a TOTAL row.
- **Unit cost metrics** — `analyze` output now includes `cost_per_gb` (total monthly cost per GB of data protected) and `cost_per_backup` (total monthly cost per backup operation) per workload, making efficiency comparison across workloads straightforward for finance teams.
- **Pipeline framing** — README rewritten to open with the Visibility → Variance → Tradeoffs system context and cross-links to all four pipeline tools.
- **GitHub Actions CI** — pytest runs on Python 3.10, 3.11, and 3.12 on every push.
- **examples/** — sample workload config CSV and expected output walkthrough.

## [0.1.0] — Initial release

- `analyze` command: CSV-in, resilience cost out
- Output formats: `json`, `yaml`, `csv`
- Per-workload cost breakdown: storage, restore, total
- Explicit exit codes for automation (0, 2, 3, 4, 5)
- Zero-dependency YAML fallback (no PyYAML required at runtime)
