# Changelog

All notable changes to Recovery Economics are documented here.

## [Unreleased]

- Add a standard `recovery-economics --version` installation smoke check.
- Correct event-frequency terminology and align the documented protected-storage formula with the canonical implementation.

## [0.2.0] — 2026-08-04

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
