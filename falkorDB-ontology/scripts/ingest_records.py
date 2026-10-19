"""Load KPI records from JSON or CSV into FalkorDB.

The command never deletes a graph. Deleting the configured graph requires
--wipe and --confirm-wipe together, and that invocation does not ingest.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from falkor_client import connect, connection_settings, load_env_file, wait_until_ready
from fact_graph import (
    apply_statements,
    ensure_fact_schema,
    fetch_dimension_hashes,
    fetch_observation_states,
    plan_ingestion,
    prepare_plans,
    wipe_graph,
)
from load_sample_data import utc_now
from record_io import configured_path, default_json_path, load_records
from vocabulary_values import persist_vocabulary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest KPI JSON or CSV into the observation ontology.")
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="JSON or CSV records. Defaults to INPUT_DATA_FILE in .env, or data/sample_data.json.",
    )
    parser.add_argument("--wipe", action="store_true", help="Delete only the configured FalkorDB graph.")
    parser.add_argument(
        "--confirm-wipe",
        action="store_true",
        help="Required with --wipe. Without it, the graph is not deleted.",
    )
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    load_env_file(root / ".env")
    settings = connection_settings()

    if args.wipe:
        if args.input is not None:
            print(
                "ERROR: --wipe does not ingest. Run the wipe, then run ingestion as a separate command.",
                file=sys.stderr,
            )
            return 2
        return _wipe(settings, confirmed=args.confirm_wipe)

    if args.confirm_wipe:
        print("Ignoring --confirm-wipe because --wipe was not set. No graph was deleted.")

    source = args.input or configured_path("INPUT_DATA_FILE", default_json_path())
    if source is None:
        raise ValueError("No input file configured. Set INPUT_DATA_FILE in .env or pass --input.")
    records = load_records(source)
    config = {
        "provenance_platform": settings["provenance_platform"],
        "source_table": settings["source_table"],
        "source_field_mapping": settings["source_field_mapping"],
        "data_version": settings["data_version"],
    }
    plans, collapsed = prepare_plans(records, config)
    client = connect(
        settings["host"], settings["port"], settings["username"], settings["password"]
    )
    wait_until_ready(client)
    graph = settings["graph"]
    ensure_fact_schema(client, graph)
    diff = plan_ingestion(
        plans,
        fetch_observation_states(client, graph),
        fetch_dimension_hashes(client, graph),
        utc_now(),
    )
    apply_statements(client, graph, diff["statements"])
    vocabulary_writes = persist_vocabulary(client, graph, records, utc_now())
    print(
        f"input {source.name}: {len(records)} rows, {len(plans)} observation keys"
        + (f", {collapsed} duplicate keys collapsed" if collapsed else "")
    )
    print(
        f"graph {graph}: created {len(diff['created'])}, "
        f"updated {len(diff['updated'])}, unchanged {len(diff['unchanged'])}"
    )
    print(
        f"entity nodes: created {diff['entity_creates']}, updated {diff['entity_updates']}, "
        f"writes {len(diff['statements'])}"
    )
    print(f"vocabulary column links written: {vocabulary_writes}")
    return 0


def _wipe(settings: dict, confirmed: bool) -> int:
    graph = settings["graph"]
    host = settings["host"]
    port = settings["port"]
    print("=" * 72)
    print("WARNING: this deletes one FalkorDB graph and cannot be undone.")
    print(f"Target graph : {graph}")
    print(f"FalkorDB     : {host}:{port}")
    print("Only this graph is deleted. Other graphs on the server are left in place.")
    print("This does not remove the Docker volume or any other database.")
    print("Back up first, then confirm the name with GRAPH.LIST:")
    print("  docker exec falkordb-ontology redis-cli GRAPH.LIST")
    print("  docker exec falkordb-ontology redis-cli SAVE")
    print("  docker cp falkordb-ontology:/var/lib/falkordb/data/dump.rdb ./enterprise_kpi-backup.rdb")
    print("=" * 72)
    if not confirmed:
        print("Refusing to delete the graph. Re-run with --wipe --confirm-wipe after the backup.")
        return 2
    client = connect(host, port, settings["username"], settings["password"])
    wait_until_ready(client)
    wipe_graph(client, graph)
    print(f"Deleted graph {graph}. Other graphs were not deleted.")
    print("Run ingest_records.py next. This command does not load records.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
