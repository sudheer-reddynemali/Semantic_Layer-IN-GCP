"""Read and display a bounded sample from the configured BigQuery table."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional, Sequence

import google.auth.exceptions
from google.api_core.exceptions import GoogleAPICallError
from google.cloud import bigquery


DEFAULT_PROJECT = "gcp-fs-looker-agentic"
DEFAULT_DATASET = "kg_demo_usecase"
DEFAULT_TABLE = "usecase_abc"
DEFAULT_LIMIT = 5


def positive_int(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if result < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read a sample from BigQuery without exporting or modifying data."
    )
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument(
        "--limit",
        type=positive_int,
        default=DEFAULT_LIMIT,
        help=f"maximum rows to display (default: {DEFAULT_LIMIT})",
    )
    args = parser.parse_args(argv)

    table_id = f"{args.project}.{args.dataset}.{args.table}"
    client: Optional[bigquery.Client] = None
    try:
        client = bigquery.Client(project=args.project)
        table = client.get_table(table_id)
        rows = list(client.list_rows(table, max_results=args.limit))

        print(f"BigQuery read succeeded: {table.full_table_id}")
        print(f"Rows in table (metadata): {table.num_rows}")
        print(f"Rows retrieved: {len(rows)} (limit: {args.limit})")
        print("Columns: " + ", ".join(field.name for field in table.schema))
        for row in rows:
            print(json.dumps(dict(row), default=str, ensure_ascii=False))
        return 0
    except google.auth.exceptions.DefaultCredentialsError as exc:
        print(
            "ERROR: Application Default Credentials are unavailable. "
            "Run `gcloud auth application-default login` and retry. "
            f"Details: {exc}",
            file=sys.stderr,
        )
        return 1
    except GoogleAPICallError as exc:
        print(f"ERROR: BigQuery read failed for {table_id}: {exc}", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    sys.exit(main())
