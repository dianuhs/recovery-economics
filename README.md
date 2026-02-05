# Recovery Economics

Recovery Economics is a small, deterministic CLI for modeling **monthly resilience cost** from local backup/restore configuration data.

This repository is currently scoped to **v0.1**:

- CSV in
- machine-readable output (JSON, YAML, or CSV)
- no cloud API calls
- explicit exit codes

## v0.1 scope

Given a CSV with one row per workload, the CLI computes per-workload and aggregate monthly cost.

### Required input columns

- `workload` (or custom name via `--workload-column`)
- `data_gb`
- `backup_frequency_per_month`
- `retention_months`
- `storage_rate_per_gb_month`
- `restore_gb_per_month`
- `restore_rate_per_gb`

### Formulas

For each workload:

- `effective_backups_kept = backup_frequency_per_month * retention_months`
- `monthly_storage_cost = data_gb * backup_frequency_per_month * retention_months * storage_rate_per_gb_month`
- `monthly_restore_cost = restore_gb_per_month * restore_rate_per_gb`
- `total_monthly_resilience_cost = monthly_storage_cost + monthly_restore_cost`

Costs are rounded to 2 decimals.

## CLI contract

### Command

```bash
recovery-economics analyze \
  --input tests/fixtures/simple_config.csv \
  --output-format json
```

`python -m recovery_economics ...` is also supported.

### Flags

Required:

- `--input` : path to CSV file
- `--output-format` : `json` | `yaml` | `csv`

Optional:

- `--workload-column` : defaults to `workload`

## Output contract

### JSON / YAML

`json` and `yaml` emit the same structure:

- `schema_version` (constant: `"1.0"`)
- `metadata.generated_at` (UTC ISO-8601)
- `metadata.input_file`
- `summary`
- `workloads` (array)

If the CSV has a valid header and zero data rows, output is still valid with:

- `summary.total_workloads = 0`
- zero totals
- `workloads = []`

### CSV

`csv` emits one row per workload with:

- `workload`
- `monthly_storage_cost`
- `monthly_restore_cost`
- `total_monthly_resilience_cost`

Stdout contains only the payload for all formats.

## Exit codes

- `0` = success
- `2` = CLI usage error (missing/invalid flags)
- `3` = input file error (not found/unreadable)
- `4` = schema/data error (missing columns, non-numeric values, invalid values)
- `5` = internal/runtime error

High modeled cost is data, not an error.

## Out of scope in v0.1

- cloud API calls or pricing API calls
- storage-class price lookups
- direct RPO/RTO modeling
- simulation/time-travel modeling
- daemon/scheduler/alerting behavior

## Development

Install locally:

```bash
pip install -e .
```

Run tests:

```bash
pytest
```
