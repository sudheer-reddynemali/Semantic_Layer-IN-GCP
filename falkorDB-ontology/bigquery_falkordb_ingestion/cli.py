"""Command-line entry point for direct BigQuery ingestion."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import bigquery
import google.auth.exceptions
import redis

from .graph import (
    connect as connect_falkordb,
    ensure_identity_indexes_and_constraints,
    load_env_file,
    upsert_schema,
)
from .ingest import process_batches, replay_failures, selected_source_columns
from .kpi_measures import load_config
from .ontology import check_config_columns, load_schema

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
DEFAULT_CONFIG = PACKAGE_ROOT / "config.json"
DEFAULT_ONTOLOGY = PACKAGE_ROOT / "ontology" / "enterprise_kpi_ontology.csv"
DEFAULT_FAILED_FILE = PACKAGE_ROOT / "failed_records" / "failed_rows.jsonl"


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _nonnegative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stream BigQuery rows into idempotent FalkorDB ontology upserts."
    )
    parser.add_argument("--project", default=None, help="BigQuery GCP project.")
    parser.add_argument("--dataset", default=None, help="BigQuery dataset.")
    parser.add_argument("--table", default=None, help="BigQuery table.")
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=None,
        help="maximum source rows to process; default is all rows",
    )
    parser.add_argument(
        "--batch-size",
        type=_positive_int,
        default=None,
        help="canonical batch size (default: BIGQUERY_BATCH_SIZE or config value)",
    )
    parser.add_argument(
        "--retry-limit",
        type=_nonnegative_int,
        default=None,
        help="retries after the initial row attempt (default: BIGQUERY_RETRY_LIMIT or config value)",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--ontology", type=Path, default=DEFAULT_ONTOLOGY)
    parser.add_argument(
        "--replay-failures",
        nargs="?",
        const=DEFAULT_FAILED_FILE,
        default=None,
        type=Path,
        help="replay the default local failure file or the given JSONL path",
    )
    args = parser.parse_args(argv)

    local_env = PACKAGE_ROOT / ".env"
    root_env = PROJECT_ROOT / ".env"
    load_env_file(local_env)
    load_env_file(root_env)

    try:
        config = load_config(args.config)
        bq_options = config["bigquery"]
        project = args.project or os.environ.get("BIGQUERY_PROJECT") or bq_options["project"]
        dataset = args.dataset or os.environ.get("BIGQUERY_DATASET") or bq_options["dataset"]
        table_name = (
            args.table
            or os.environ.get("BIGQUERY_TABLE")
            or os.environ.get("BIGQUERY_TABLE_NAME")
            or bq_options["table"]
        )
        batch_size = args.batch_size or _configured_positive_int(
            "BIGQUERY_BATCH_SIZE", config["batch_size"]
        )
        retry_limit = (
            args.retry_limit
            if args.retry_limit is not None
            else _configured_nonnegative_int("BIGQUERY_RETRY_LIMIT", config["retry_limit"])
        )
        retry_base = float(config["retry_base_seconds"])
        if retry_base < 0:
            raise ValueError("retry_base_seconds cannot be negative.")
        graph_name = os.environ.get("FALKORDB_GRAPH", "enterprise_kpi")
        failure_file = args.replay_failures or DEFAULT_FAILED_FILE

        schema = load_schema(args.ontology, table_name, project)
        check_config_columns(config, schema)
        if args.replay_failures is not None:
            falkor = connect_falkordb()
            try:
                ensure_identity_indexes_and_constraints(falkor, graph_name, schema, config)
                upsert_schema(falkor, graph_name, schema)
                result = replay_failures(
                    failure_file,
                    client=falkor,
                    graph=graph_name,
                    schema=schema,
                    config=config,
                    retry_limit=retry_limit,
                    retry_base_seconds=retry_base,
                )
                print(
                    f"Replay complete: {result['succeeded']}/{result['replayed']} succeeded; "
                    f"{result['failed']} remain in {failure_file}."
                )
                return 1 if result["failed"] else 0
            finally:
                falkor.close()

        table_id = f"{project}.{dataset}.{table_name}"
        bq_client = bigquery.Client(project=project)
        try:
            table = bq_client.get_table(table_id)
            total_rows = table.num_rows
            if args.limit is not None:
                total_rows = (
                    min(args.limit, total_rows)
                    if total_rows is not None
                    else args.limit
                )
            selected_names = selected_source_columns(config)
            source_fields = {field.name.upper(): field for field in table.schema}
            mapped_names = {
                field.upper()
                for field in (
                    *selected_names,
                    *(measure["bigquery_column"] for measure in config["kpi_definitions"]),
                )
            }
            missing = sorted(mapped_names - source_fields.keys())
            if missing:
                raise ValueError(
                    "BigQuery source table is missing configured source columns: "
                    + ", ".join(missing)
                )
            selected_fields = [source_fields[name.upper()] for name in selected_names]
            rows = bq_client.list_rows(
                table,
                selected_fields=selected_fields,
                max_results=args.limit,
            )
            total_label = str(total_rows) if total_rows is not None else "unknown"
            print(
                f"Starting direct ingestion from {table.full_table_id}: "
                f"{total_label} rows expected, batch size {batch_size}, "
                f"retry limit {retry_limit}.",
                flush=True,
            )
            falkor = connect_falkordb()
            try:
                ensure_identity_indexes_and_constraints(falkor, graph_name, schema, config)
                upsert_schema(falkor, graph_name, schema)
                print("FalkorDB schema is ready; processing source rows.", flush=True)
                result = process_batches(
                    rows,
                    client=falkor,
                    graph=graph_name,
                    schema=schema,
                    config=config,
                    batch_size=batch_size,
                    retry_limit=retry_limit,
                    retry_base_seconds=retry_base,
                    failed_file=DEFAULT_FAILED_FILE,
                    source_table=table_id,
                    progress_callback=lambda progress: _print_progress(
                        progress, total_rows
                    ),
                )
            finally:
                falkor.close()
        finally:
            bq_client.close()
        if result["rows"]:
            print()
        else:
            print("No source rows were returned.")
        print(
            f"BigQuery table: {table.full_table_id}\n"
            f"Rows processed: {result['rows']} in {result['batches']} batches "
            f"(batch size {batch_size}; limit {args.limit or 'all'})\n"
            f"Upserts succeeded: {result['succeeded']}; failed after retries: {result['failed']}\n"
            f"Graph: {graph_name}"
        )
        if result["failed"]:
            print(f"Failed rows saved to: {DEFAULT_FAILED_FILE}", file=sys.stderr)
            return 1
        return 0
    except google.auth.exceptions.DefaultCredentialsError as exc:
        print(
            "ERROR: Application Default Credentials are unavailable. "
            "Run `gcloud auth application-default login` and retry. "
            f"Details: {exc}",
            file=sys.stderr,
        )
        return 1
    except (
        argparse.ArgumentTypeError,
        GoogleAPICallError,
        OSError,
        redis.RedisError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _configured_positive_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    return _positive_int(value)


def _configured_nonnegative_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    return _nonnegative_int(value)


def _print_progress(progress: dict[str, int], total_rows: int | None) -> None:
    processed = progress["rows"]
    succeeded = progress["succeeded"]
    failed = progress["failed"]
    if total_rows is None:
        total_label = "unknown"
        percentage_label = "n/a"
        pending_label = "unknown"
    else:
        total_label = str(total_rows)
        percentage = processed / total_rows * 100 if total_rows else 100.0
        percentage_label = f"{percentage:.1f}%"
        pending_label = str(max(total_rows - processed, 0))
    print(
        f"\rProgress: {processed}/{total_label} ({percentage_label}) | "
        f"succeeded: {succeeded} | failed: {failed} | pending: {pending_label}",
        end="",
        flush=True,
    )


if __name__ == "__main__":
    sys.exit(main())
