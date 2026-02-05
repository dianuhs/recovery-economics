from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import List, Sequence, TextIO

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - depends on runtime environment
    yaml = None

from .model import (
    DEFAULT_WORKLOAD_COLUMN,
    REQUIRED_NUMERIC_COLUMNS,
    WorkloadConfig,
    WorkloadCost,
    build_report_payload,
    calculate_workload_cost,
)

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

    return parser


def _parse_non_negative_float(raw_value: str | None, column_name: str, row_number: int) -> float:
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

    if value < 0:
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
                    data_gb=_parse_non_negative_float(row.get("data_gb"), "data_gb", row_number),
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

            return workloads
    except FileNotFoundError as exc:
        raise InputFileError(f"File not found: {input_file}") from exc
    except PermissionError as exc:
        raise InputFileError(f"File is not readable: {input_file}") from exc
    except OSError as exc:
        raise InputFileError(f"Could not read input file '{input_file}': {exc}") from exc


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
            }
        )


def run_analyze(input_file: str, output_format: str, workload_column: str, stdout: TextIO) -> int:
    workload_inputs = load_workloads(input_file=input_file, workload_column=workload_column)
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


def run(argv: Sequence[str] | None = None, stdout: TextIO = sys.stdout, stderr: TextIO = sys.stderr) -> int:
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
        raise RuntimeError(f"Unsupported command: {args.command}")
    except InputFileError as exc:
        print(f"Input file error: {exc}", file=stderr)
        return EXIT_INPUT_FILE_ERROR
    except SchemaDataError as exc:
        print(f"Schema/data error: {exc}", file=stderr)
        return EXIT_SCHEMA_DATA_ERROR
    except Exception as exc:  # pragma: no cover - hard to trigger deterministically
        print(f"Internal/runtime error: {exc}", file=stderr)
        return EXIT_INTERNAL_RUNTIME_ERROR


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(run(argv=argv))


if __name__ == "__main__":
    main()
