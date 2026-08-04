from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import List, Sequence, TextIO

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - depends on runtime environment
    yaml = None

from . import __version__
from .ccac import build_comparison_result
from .ccac import build_result as build_ccac_result
from .ccac import demo_result, load_scenario
from .model import (
    DEFAULT_WORKLOAD_COLUMN,
    REQUIRED_NUMERIC_COLUMNS,
    WorkloadConfig,
    WorkloadCost,
    build_report_payload,
    calculate_workload_cost,
)
from .scenario import ScenarioError, illustrative_scenario

EXIT_SUCCESS = 0
EXIT_USAGE_ERROR = 2
EXIT_INPUT_FILE_ERROR = 3
EXIT_SCHEMA_DATA_ERROR = 4
EXIT_INTERNAL_RUNTIME_ERROR = 5


class InputFileError(Exception):
    pass


class SchemaDataError(Exception):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="recovery-economics",
        description=(
            "Recovery Economics v0.1: calculate monthly resilience cost from local CSV input."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser(
        "analyze",
        help="Analyze backup/restore strategy costs from a CSV file.",
    )
    analyze.add_argument(
        "--input",
        required=True,
        help="Path to the workload CSV file.",
    )
    analyze.add_argument(
        "--output-format",
        required=True,
        choices=("json", "yaml", "csv"),
        help="Output format.",
    )
    analyze.add_argument(
        "--workload-column",
        default=DEFAULT_WORKLOAD_COLUMN,
        help="Column name for workload identifiers.",
    )

    compare = subparsers.add_parser(
        "compare",
        help="Compare monthly cost delta between two scenario CSV files.",
    )
    compare.add_argument(
        "--baseline",
        required=True,
        help="Path to the baseline scenario CSV file.",
    )

    ccac = subparsers.add_parser(
        "ccac", help="Model a versioned resilience scenario and emit CCAC JSON."
    )
    mode = ccac.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--demo", action="store_true", help="Use deterministic illustrative data."
    )
    mode.add_argument(
        "--input", help="Read a recovery-economics/2.0 YAML or JSON scenario."
    )
    ccac.add_argument("--output", help="Write JSON to a file instead of stdout.")
    ccac.add_argument("--run-id", help="Pipeline run UUID; generated when omitted.")
    ccac.add_argument("--generated-at", help="RFC3339 timestamp for reproducible runs.")

    compare_ccac = subparsers.add_parser(
        "compare-ccac", help="Compare two v2 scenarios and emit CCAC JSON."
    )
    compare_ccac.add_argument("--baseline", required=True)
    compare_ccac.add_argument("--proposed", required=True)
    compare_ccac.add_argument("--output")
    compare_ccac.add_argument("--run-id")
    compare_ccac.add_argument("--generated-at")
    compare.add_argument(
        "--proposed",
        required=True,
        help="Path to the proposed scenario CSV file.",
    )
    compare.add_argument(
        "--workload-column",
        default=DEFAULT_WORKLOAD_COLUMN,
        help="Column name for workload identifiers.",
    )

    return parser


def _parse_non_negative_float(
    raw_value: str | None, column_name: str, row_number: int
) -> float:
    value_text = "" if raw_value is None else str(raw_value).strip()
    if value_text == "":
        raise SchemaDataError(
            f"Row {row_number}: column '{column_name}' is empty; expected a numeric value."
        )

    try:
        value = float(value_text)
    except ValueError as exc:
        raise SchemaDataError(
            f"Row {row_number}: column '{column_name}' has non-numeric value '{value_text}'."
        ) from exc

    if not math.isfinite(value) or value < 0:
        raise SchemaDataError(
            f"Row {row_number}: column '{column_name}' must be >= 0, got {value_text}."
        )

    return value


def _is_blank_row(row: dict[str, str | None]) -> bool:
    return all(value is None or str(value).strip() == "" for value in row.values())


def load_workloads(input_file: str, workload_column: str) -> List[WorkloadConfig]:
    path = Path(input_file)
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise SchemaDataError("Input CSV is empty or missing a header row.")

            required_columns = [workload_column, *REQUIRED_NUMERIC_COLUMNS]
            missing_columns = [
                column for column in required_columns if column not in reader.fieldnames
            ]
            if missing_columns:
                missing_text = ", ".join(sorted(missing_columns))
                raise SchemaDataError(f"Missing required columns: {missing_text}")

            workloads: List[WorkloadConfig] = []
            for row_number, row in enumerate(reader, start=2):
                if _is_blank_row(row):
                    continue

                workload_name = (row.get(workload_column) or "").strip()
                if not workload_name:
                    raise SchemaDataError(
                        f"Row {row_number}: column '{workload_column}' is empty."
                    )

                workload = WorkloadConfig(
                    workload=workload_name,
                    data_gb=_parse_non_negative_float(
                        row.get("data_gb"), "data_gb", row_number
                    ),
                    backup_frequency_per_month=_parse_non_negative_float(
                        row.get("backup_frequency_per_month"),
                        "backup_frequency_per_month",
                        row_number,
                    ),
                    retention_months=_parse_non_negative_float(
                        row.get("retention_months"),
                        "retention_months",
                        row_number,
                    ),
                    storage_rate_per_gb_month=_parse_non_negative_float(
                        row.get("storage_rate_per_gb_month"),
                        "storage_rate_per_gb_month",
                        row_number,
                    ),
                    restore_gb_per_month=_parse_non_negative_float(
                        row.get("restore_gb_per_month"),
                        "restore_gb_per_month",
                        row_number,
                    ),
                    restore_rate_per_gb=_parse_non_negative_float(
                        row.get("restore_rate_per_gb"),
                        "restore_rate_per_gb",
                        row_number,
                    ),
                )
                workloads.append(workload)

            if not workloads:
                raise SchemaDataError("Input CSV contains no workload rows.")
            names = [workload.workload for workload in workloads]
            duplicates = sorted({name for name in names if names.count(name) > 1})
            if duplicates:
                raise SchemaDataError(
                    f"Duplicate workload identifiers: {', '.join(duplicates)}"
                )
            return workloads
    except FileNotFoundError as exc:
        raise InputFileError(f"File not found: {input_file}") from exc
    except PermissionError as exc:
        raise InputFileError(f"File is not readable: {input_file}") from exc
    except OSError as exc:
        raise InputFileError(
            f"Could not read input file '{input_file}': {exc}"
        ) from exc


def _emit_json(payload: dict, stdout: TextIO) -> None:
    json.dump(payload, stdout, indent=2)
    stdout.write("\n")


def _yaml_scalar(value: object) -> str:
    if isinstance(value, str):
        # JSON string quoting is valid YAML and keeps output deterministic.
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return str(value)


def _yaml_lines(value: object, indent: int = 0) -> list[str]:
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            return [f"{pad}{{}}"]
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.extend(_yaml_lines(item, indent + 2))
            else:
                lines.append(f"{pad}{key}: {_yaml_scalar(item)}")
        return lines
    if isinstance(value, list):
        if not value:
            return [f"{pad}[]"]
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}-")
                lines.extend(_yaml_lines(item, indent + 2))
            else:
                lines.append(f"{pad}- {_yaml_scalar(item)}")
        return lines
    return [f"{pad}{_yaml_scalar(value)}"]


def _emit_yaml(payload: dict, stdout: TextIO) -> None:
    if yaml is not None:
        yaml_text = yaml.safe_dump(payload, sort_keys=False)
    else:
        yaml_text = "\n".join(_yaml_lines(payload))
    stdout.write(yaml_text)
    if not yaml_text.endswith("\n"):
        stdout.write("\n")


def _emit_csv(workloads: List[WorkloadCost], stdout: TextIO) -> None:
    fieldnames = [
        "workload",
        "monthly_storage_cost",
        "monthly_restore_cost",
        "total_monthly_resilience_cost",
        "cost_per_gb",
        "cost_per_backup",
    ]
    writer = csv.DictWriter(stdout, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()

    for workload in workloads:
        writer.writerow(
            {
                "workload": workload.workload,
                "monthly_storage_cost": workload.monthly_storage_cost,
                "monthly_restore_cost": workload.monthly_restore_cost,
                "total_monthly_resilience_cost": workload.total_monthly_resilience_cost,
                "cost_per_gb": workload.cost_per_gb,
                "cost_per_backup": workload.cost_per_backup,
            }
        )


def run_compare(
    baseline_file: str, proposed_file: str, workload_column: str, stdout: TextIO
) -> int:
    baseline_inputs = load_workloads(
        input_file=baseline_file, workload_column=workload_column
    )
    proposed_inputs = load_workloads(
        input_file=proposed_file, workload_column=workload_column
    )

    baseline_costs = {c.workload: calculate_workload_cost(c) for c in baseline_inputs}
    proposed_costs = {c.workload: calculate_workload_cost(c) for c in proposed_inputs}

    all_workloads = sorted(set(baseline_costs) | set(proposed_costs))
    if set(baseline_costs) != set(proposed_costs):
        missing_baseline = sorted(set(proposed_costs) - set(baseline_costs))
        missing_proposed = sorted(set(baseline_costs) - set(proposed_costs))
        details = []
        if missing_baseline:
            details.append(f"missing from baseline: {', '.join(missing_baseline)}")
        if missing_proposed:
            details.append(f"missing from proposed: {', '.join(missing_proposed)}")
        raise SchemaDataError("Scenario workload sets differ; " + "; ".join(details))

    rows = []
    for workload in all_workloads:
        b = baseline_costs.get(workload)
        p = proposed_costs.get(workload)
        b_total = b.total_monthly_resilience_cost if b else 0.0
        p_total = p.total_monthly_resilience_cost if p else 0.0
        delta = p_total - b_total
        rows.append((workload, b_total, p_total, delta))

    rows.sort(key=lambda r: abs(r[3]), reverse=True)

    col_w = max(len(r[0]) for r in rows) if rows else 10
    col_w = max(col_w, 8)
    header = f"{'Workload':<{col_w}}  {'Baseline':>12}  {'Proposed':>12}  {'Delta':>12}"
    sep = "-" * len(header)
    stdout.write(f"Scenario comparison: {baseline_file}  vs  {proposed_file}\n")
    stdout.write(f"{sep}\n{header}\n{sep}\n")
    for workload, b_total, p_total, delta in rows:
        sign = "+" if delta >= 0 else ""
        stdout.write(
            f"{workload:<{col_w}}  ${b_total:>11.2f}  ${p_total:>11.2f}  {sign}${delta:>10.2f}\n"
        )
    stdout.write(f"{sep}\n")
    total_b = sum(r[1] for r in rows)
    total_p = sum(r[2] for r in rows)
    total_d = total_p - total_b
    sign = "+" if total_d >= 0 else ""
    stdout.write(
        f"{'TOTAL':<{col_w}}  ${total_b:>11.2f}  ${total_p:>11.2f}  {sign}${total_d:>10.2f}\n"
    )
    return EXIT_SUCCESS


def run_analyze(
    input_file: str, output_format: str, workload_column: str, stdout: TextIO
) -> int:
    workload_inputs = load_workloads(
        input_file=input_file, workload_column=workload_column
    )
    workload_costs = [calculate_workload_cost(config) for config in workload_inputs]

    if output_format == "csv":
        _emit_csv(workload_costs, stdout)
        return EXIT_SUCCESS

    payload = build_report_payload(workloads=workload_costs, input_file=input_file)

    if output_format == "json":
        _emit_json(payload, stdout)
        return EXIT_SUCCESS

    if output_format == "yaml":
        _emit_yaml(payload, stdout)
        return EXIT_SUCCESS

    raise RuntimeError(f"Unsupported output format: {output_format}")


def run_ccac(args: argparse.Namespace, stdout: TextIO) -> int:
    if args.demo and args.run_id is None and args.generated_at is None:
        payload = demo_result()
    elif args.demo:
        payload = build_ccac_result(
            illustrative_scenario(),
            mode="illustrative",
            run_id=args.run_id,
            generated_at=args.generated_at,
        )
    else:
        payload = build_ccac_result(
            load_scenario(Path(args.input)),
            mode="real",
            run_id=args.run_id,
            generated_at=args.generated_at,
        )
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    else:
        stdout.write(rendered)
    return EXIT_SUCCESS


def run_compare_ccac(args: argparse.Namespace, stdout: TextIO) -> int:
    payload = build_comparison_result(
        load_scenario(Path(args.baseline)),
        load_scenario(Path(args.proposed)),
        mode="real",
        run_id=args.run_id,
        generated_at=args.generated_at,
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    else:
        stdout.write(rendered)
    return EXIT_SUCCESS


def run(
    argv: Sequence[str] | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "analyze":
            return run_analyze(
                input_file=args.input,
                output_format=args.output_format,
                workload_column=args.workload_column,
                stdout=stdout,
            )
        if args.command == "compare":
            return run_compare(
                baseline_file=args.baseline,
                proposed_file=args.proposed,
                workload_column=args.workload_column,
                stdout=stdout,
            )
        if args.command == "ccac":
            return run_ccac(args, stdout)
        if args.command == "compare-ccac":
            return run_compare_ccac(args, stdout)
        raise RuntimeError(f"Unsupported command: {args.command}")
    except InputFileError as exc:
        print(f"Input file error: {exc}", file=stderr)
        return EXIT_INPUT_FILE_ERROR
    except SchemaDataError as exc:
        print(f"Schema/data error: {exc}", file=stderr)
        return EXIT_SCHEMA_DATA_ERROR
    except ScenarioError as exc:
        print(f"Scenario error: {exc}", file=stderr)
        return EXIT_SCHEMA_DATA_ERROR
    except Exception as exc:  # pragma: no cover - hard to trigger deterministically
        print(f"Internal/runtime error: {exc}", file=stderr)
        return EXIT_INTERNAL_RUNTIME_ERROR


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(run(argv=argv))


if __name__ == "__main__":
    main()
