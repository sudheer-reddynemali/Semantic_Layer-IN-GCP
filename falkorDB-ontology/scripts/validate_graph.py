"""Compare FalkorDB to the ontology CSV.

Expected nodes and edges come from ontology/enterprise_kpi_ontology.csv.
Retired observation labels must be absent.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from falkor_client import (
    connect,
    connection_settings,
    graph_query,
    load_env_file,
    rows_as_dicts,
    wait_until_ready,
)
from ontology_csv import (
    ID_PROPERTY,
    RETIRED_LABELS,
    default_csv_path,
    keep_schema_only,
    load_ontology,
    set_table_source_identity,
)
from vocabulary_values import add_value_nodes, load_sample_vocabulary_records
from kpi_measures import add_kpi_measures
from record_io import configured_path, load_records


Edge = Tuple[str, str, str]


def _coalesce_id(alias: str) -> str:
    parts = ", ".join(f"{alias}.{prop}" for prop in dict.fromkeys(ID_PROPERTY.values()))
    return f"coalesce({parts})"


def fetch_label_counts(client, graph: str) -> Dict[str, int]:
    result = graph_query(
        client,
        graph,
        "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS nodes ORDER BY label",
    )
    counts = {}
    for row in rows_as_dicts(result):
        counts[str(row["label"])] = int(row["nodes"])
    return counts


def fetch_edges(client, graph: str) -> Set[Edge]:
    query = (
        "MATCH (a)-[r]->(b) "
        f"RETURN {_coalesce_id('a')} AS src, type(r) AS rel, {_coalesce_id('b')} AS dst"
    )
    result = graph_query(client, graph, query)
    return {(str(row["src"]), str(row["rel"]), str(row["dst"])) for row in rows_as_dicts(result)}


def validate(
    csv_path: Optional[Path] = None,
    records_path: Optional[Path] = None,
    table_name: Optional[str] = None,
    project: Optional[str] = None,
) -> List[str]:
    root = Path(__file__).resolve().parents[1]
    load_env_file(root / ".env")
    settings = connection_settings()
    table_name = table_name or os.environ.get("BIGQUERY_TABLE_NAME")
    project = project or os.environ.get("BIGQUERY_PROJECT") or None
    path = csv_path or configured_path("ONTOLOGY_FILE", default_csv_path())
    if path is None:
        raise ValueError("No ontology file configured. Set ONTOLOGY_FILE in .env or pass --input.")
    ontology = keep_schema_only(load_ontology(path))
    set_table_source_identity(ontology, table_name, project)
    table = next(node for node in ontology["nodes"] if node["label"] == "BQ_Table")
    configured_records = records_path or configured_path("INPUT_DATA_FILE")
    records = (
        load_records(configured_records)
        if configured_records
        else load_sample_vocabulary_records()
    )
    add_value_nodes(ontology, records)
    add_kpi_measures(ontology, records)
    errors: List[str] = []

    client = connect(
        settings["host"], settings["port"], settings["username"], settings["password"]
    )
    wait_until_ready(client, attempts=5)
    graph = settings["graph"]

    actual_counts = fetch_label_counts(client, graph)
    expected_counts: Dict[str, int] = {}
    for node in ontology["nodes"]:
        expected_counts[node["label"]] = expected_counts.get(node["label"], 0) + 1
    for label, count in expected_counts.items():
        if actual_counts.get(label, 0) != count:
            errors.append(f"{label}: graph has {actual_counts.get(label, 0)}, CSV has {count}")
    for label, count in actual_counts.items():
        if label not in expected_counts:
            errors.append(f"unexpected label {label} has {count} nodes")
    for label in RETIRED_LABELS:
        if actual_counts.get(label, 0):
            errors.append(f"retired label {label} still has {actual_counts[label]} nodes")

    for label, id_property in ID_PROPERTY.items():
        if label not in {node["label"] for node in ontology["nodes"]}:
            continue
        result = graph_query(
            client,
            graph,
            f"MATCH (n:{label}) RETURN n.{id_property} AS node_id",
        )
        expected_ids = {
            node["id"] for node in ontology["nodes"] if node["label"] == label
        }
        actual_ids = {
            str(row["node_id"])
            for row in rows_as_dicts(result)
            if row.get("node_id") is not None
        }
        if actual_ids != expected_ids:
            errors.append(
                f"{label} ids differ from source-derived ontology: "
                f"unexpected={sorted(actual_ids - expected_ids)[:5]}, "
                f"missing={sorted(expected_ids - actual_ids)[:5]}"
            )

    expected_edges = {(edge["from_id"], edge["type"], edge["to_id"]) for edge in ontology["edges"]}
    actual_edges = fetch_edges(client, graph)
    missing = expected_edges - actual_edges
    extra = actual_edges - expected_edges
    if missing:
        errors.append(f"missing {len(missing)} edges, for example {sorted(missing)[:5]}")
    if extra:
        errors.append(f"unexpected {len(extra)} edges, for example {sorted(extra)[:5]}")

    columns = graph_query(
        client,
        graph,
        """
        MATCH (t:BQ_Table {table_id: 'BQ_TABLE:agentic_kg_usecase'})-[:HAS_COLUMN]->(c:BQ_column)
        RETURN count(c) AS columns
        """,
    )
    period = graph_query(
        client,
        graph,
        """
        MATCH (t:BQ_Table {table_id: 'BQ_TABLE:agentic_kg_usecase'})-[:HAS_COLUMN]->(c:BQ_column)
        WHERE c.name = 'YEAR' OR c.name = 'REPORTING_MONTH'
        RETURN c.name AS name, c.label AS label, c.format AS format
        ORDER BY c.name
        """,
    )
    column_rows = rows_as_dicts(columns)
    period_rows = rows_as_dicts(period)
    if not column_rows or int(column_rows[0]["columns"]) != 29:
        errors.append(f"HAS_COLUMN count {column_rows}")
    period_names = {row["name"] for row in period_rows}
    if period_names != {"YEAR", "REPORTING_MONTH"}:
        errors.append(f"period columns {period_rows}")
    else:
        formats = {row["name"]: row["format"] for row in period_rows}
        if formats.get("YEAR") != "YYYY" or formats.get("REPORTING_MONTH") != "MM":
            errors.append(f"period formats {formats}")

    retired = graph_query(
        client,
        graph,
        """
        MATCH (n)
        WHERE n:ReportingPeriod OR n:KPIObservation OR n:RiskProfile OR n:KPIMeasure
        RETURN count(n) AS retired
        """,
    )
    retired_rows = rows_as_dicts(retired)
    if retired_rows and int(retired_rows[0]["retired"]) != 0:
        errors.append(f"retired nodes remain: {retired_rows[0]['retired']}")

    print("label counts:")
    for label, count in sorted(actual_counts.items()):
        print(f"  {label}: {count}")
    print(f"edges: {len(actual_edges)}")
    if errors:
        print("validation failed:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("validation passed")
    return errors


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate FalkorDB against the ontology CSV.")
    parser.add_argument("--input", type=Path, default=None, help="Ontology CSV path.")
    parser.add_argument(
        "--records",
        type=Path,
        default=None,
        help="CSV or JSON source for expected vocabulary and measure definitions.",
    )
    parser.add_argument("--table-name", default=None, help="Expected BQ_Table.name.")
    parser.add_argument("--project", default=None, help="Expected BQ_Table.project.")
    args = parser.parse_args(argv)
    errors = validate(args.input, args.records, args.table_name, args.project)
    return 1 if errors else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
