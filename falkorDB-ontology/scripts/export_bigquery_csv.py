"""Export a bounded BigQuery batch to the canonical ingestion CSV format."""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import google.auth.exceptions
from google.api_core.exceptions import GoogleAPICallError
from google.cloud import bigquery

from falkor_client import load_env_file
from normalize import CANONICAL_FIELDS, canonicalize_field_name, project_root
from record_io import write_csv_records


DEFAULT_PROJECT = "gcp-fs-looker-agentic"
DEFAULT_DATASET = "kg_demo_usecase"
DEFAULT_TABLE = "usecase_abc"
DEFAULT_BATCH_SIZE = 100
DEFAULT_OUTPUT = "data/bigquery_pilot.csv"
BIGQUERY_FIELD_ALIASES = {
    "TARGET_MEET": "meet_target",
    "MTD_ACT": "mtd_actual",
    "YTD_ACTL": "ytd_actual",
    "PY_MTD_ACT": "py_mtd_actual",
    "PY_YTD_ACTL": "py_ytd_actual",
    "PM_ACTL": "pm_actual",
}


def _positive_int(value: str, label: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an integer; received {value!r}.") from exc
    if result < 1:
        raise ValueError(f"{label} must be greater than zero.")
    return result


def _canonicalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    canonical: Dict[str, Any] = {}
    for source_name, value in row.items():
        target_name = BIGQUERY_FIELD_ALIASES.get(source_name)
        target_name = target_name or canonicalize_field_name(source_name)
        if target_name is None:
            raise ValueError(f"BigQuery returned an unmapped column: {source_name}")
        if target_name in canonical:
            raise ValueError(f"Multiple BigQuery columns map to {target_name}.")
        if isinstance(value, str) and value.strip() == "NA":
            value = None
        if isinstance(value, float):
            value = Decimal(str(value))
            if not value.is_finite():
                raise ValueError(f"BigQuery column {source_name} contains a non-finite number.")
        canonical[target_name] = value

    missing = [field for field in CANONICAL_FIELDS if field not in canonical]
    if missing:
        raise ValueError("BigQuery row is missing columns: " + ", ".join(missing))
    return canonical


def main(argv: Optional[Sequence[str]] = None) -> int:
    root = project_root()
    load_env_file(root / ".env")
    configured_size = _positive_int(
        os.environ.get("BIGQUERY_BATCH_SIZE", str(DEFAULT_BATCH_SIZE)),
        "BIGQUERY_BATCH_SIZE",
    )

    parser = argparse.ArgumentParser(
        description="Export a bounded BigQuery batch to the canonical CSV format."
    )
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument(
        "--limit",
        type=lambda value: _positive_int(value, "--limit"),
        default=configured_size,
        help=f"maximum rows to export (default: BIGQUERY_BATCH_SIZE={configured_size})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / DEFAULT_OUTPUT,
        help=f"destination CSV (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args(argv)

    table_id = f"{args.project}.{args.dataset}.{args.table}"
    client: Optional[bigquery.Client] = None
    try:
        client = bigquery.Client(project=args.project)
        table = client.get_table(table_id)
        records = [
            _canonicalize_row(dict(row))
            for row in client.list_rows(table, max_results=args.limit)
        ]
        if not records:
            raise ValueError(f"BigQuery returned no rows from {table_id}.")
        write_csv_records(args.output, records)
        print(f"BigQuery table: {table.full_table_id}")
        print(f"Rows exported: {len(records)} (limit: {args.limit})")
        print(f"Canonical CSV: {args.output}")
        return 0
    except google.auth.exceptions.DefaultCredentialsError as exc:
        print(f"ERROR: Application Default Credentials are unavailable: {exc}", file=sys.stderr)
        return 1
    except GoogleAPICallError as exc:
        print(f"ERROR: BigQuery export failed for {table_id}: {exc}", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
