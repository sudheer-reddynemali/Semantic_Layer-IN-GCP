"""Load the query-time KPI ontology into FalkorDB.

The source is ontology/enterprise_kpi_ontology.csv.
Nodes are the physical table, its columns, measure definitions, and the
vocabulary terms the CSV samples. Numbers stay in BigQuery.

Use --reset to delete existing graphs and load this model again.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from falkor_client import (
    connect,
    connection_settings,
    execute_redis_command,
    graph_delete,
    graph_query,
    is_already_exists,
    load_env_file,
    rows_as_dicts,
    wait_for_status,
    wait_until_ready,
)
from ontology_csv import (
    INDEXES,
    RETIRED_LABELS,
    SOURCE_DERIVED_LABELS,
    UNIQUE_CONSTRAINTS,
    default_csv_path,
    keep_schema_only,
    load_ontology,
    set_table_source_identity,
)
from vocabulary_values import add_value_nodes, load_sample_vocabulary_records
from kpi_measures import add_kpi_measures
from record_io import configured_path, load_records


TIMESTAMP_TOKEN = "{{INGESTION_TIMESTAMP}}"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cypher_literal(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return "'" + escaped + "'"
    raise TypeError(f"Cannot render {type(value).__name__} into Cypher.")


def assignment_list(alias: str, properties: Dict[str, Any]) -> str:
    return ", ".join(
        f"{alias}.{key} = {cypher_literal(properties[key])}" for key in properties
    )


def render_node(alias: str, node: Dict[str, Any], timestamp: str) -> str:
    create_props = dict(node["properties"])
    create_props["created_at"] = timestamp
    create_props["updated_at"] = timestamp
    match_props = dict(node["properties"])
    match_props["updated_at"] = timestamp
    return "\n".join(
        [
            f"MERGE ({alias}:{node['label']} {{{node['id_property']}: {cypher_literal(node['id'])}}})",
            f"ON CREATE SET {assignment_list(alias, create_props)}",
            f"ON MATCH SET {assignment_list(alias, match_props)}",
        ]
    )


def render_edge(alias: str, source_alias: str, edge: Dict[str, Any], target_alias: str) -> str:
    return "\n".join(
        [
            f"MATCH ({source_alias}:{edge['from_label']} {{{_id_prop(edge['from_label'])}: {cypher_literal(edge['from_id'])}}})",
            f"MATCH ({target_alias}:{edge['to_label']} {{{_id_prop(edge['to_label'])}: {cypher_literal(edge['to_id'])}}})",
            f"MERGE ({source_alias})-[{alias}:{edge['type']}]->({target_alias})",
            f"SET {alias}.origin = {cypher_literal(edge['origin'])}",
        ]
    )


def _id_prop(label: str) -> str:
    from ontology_csv import ID_PROPERTY

    return ID_PROPERTY[label]


def render_indexes() -> str:
    lines = [
        "// Identity and lookup indexes for query-time schema retrieval.",
        "// FalkorDB unique constraints require the matching index to exist first.",
        "",
    ]
    for label, prop, reason in INDEXES:
        lines.append(f"// {label}.{prop}: {reason}")
        lines.append(f"CREATE INDEX FOR (n:{label}) ON (n.{prop});")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_constraints(graph: str) -> str:
    lines = [
        "# Redis commands for FalkorDB UNIQUE constraints. These are not Cypher statements.",
        "# Create the indexes in 04_create_indexes.cypher before running these commands.",
        "",
    ]
    for label, prop in UNIQUE_CONSTRAINTS:
        lines.append(
            f"GRAPH.CONSTRAINT CREATE {graph} UNIQUE NODE {label} PROPERTIES 1 {prop}"
        )
    return "\n".join(lines) + "\n"


def render_validation_queries() -> str:
    return """// Query-time ontology checks. These should show the schema graph only.
// Numbers are not stored here. ReportingPeriod, KPIObservation, RiskProfile,
// and KPIMeasure are retired and should not appear.

MATCH (n)
RETURN labels(n)[0] AS label, count(*) AS nodes
ORDER BY label;

MATCH ()-[r]->()
RETURN type(r) AS relationship, r.origin AS origin, count(*) AS edges
ORDER BY relationship, origin;

MATCH (t:BQ_Table {name: 'agentic_kg_usecase'})-[:HAS_COLUMN]->(c:BQ_column)
RETURN t.name AS table_name, count(c) AS columns
ORDER BY table_name;

MATCH (m:BQ_KPIMeasure {name: 'Revenue YTD Actual'})
OPTIONAL MATCH (m)-[:ON_TABLE]->(t:BQ_Table)
OPTIONAL MATCH (m)-[:USES_COLUMN]->(c:BQ_column)
RETURN m.name AS measure, m.value_column AS value_column, m.aggregation AS aggregation,
       m.filters AS filters, t.name AS table_name, collect(c.name) AS used_columns;

MATCH (n)
WHERE n:ReportingPeriod OR n:KPIObservation OR n:RiskProfile OR n:KPIMeasure
RETURN labels(n) AS labels, count(*) AS nodes;
"""


def write_artifacts(root: Path, ontology: Dict[str, Any], graph: str) -> None:
    cypher_dir = root / "cypher"
    cypher_dir.mkdir(parents=True, exist_ok=True)
    node_script = "\n\n".join(
        render_node(f"n{index}", node, TIMESTAMP_TOKEN)
        for index, node in enumerate(ontology["nodes"])
    )
    edge_script = "\n\n".join(
        render_edge(f"r{index}", f"a{index}", edge, f"b{index}")
        for index, edge in enumerate(ontology["edges"])
    )
    (cypher_dir / "01_create_constraints.cypher").write_text(
        render_constraints(graph), encoding="utf-8"
    )
    (cypher_dir / "02_create_reference_nodes.cypher").write_text(
        "\n".join(
            [
                "// Generated by scripts/load_sample_data.py from the ontology CSV.",
                "// Vocabulary terms and measure definitions. Not monthly facts.",
                "",
                node_script,
                "",
            ]
        ),
        encoding="utf-8",
    )
    (cypher_dir / "03_load_sample_data.cypher").write_text(
        "\n".join(
            [
                "// Generated by scripts/load_sample_data.py from the ontology CSV.",
                "// {{INGESTION_TIMESTAMP}} is ingestion time, not a reporting period.",
                "// Edges: HAS_COLUMN, ON_TABLE, USES_COLUMN, READS_COLUMN,",
                "// FILTERS_COLUMN, DEFINED_ON, ALIGNS_WITH, DESCRIBES_COLUMN.",
                "",
                edge_script,
                "",
            ]
        ),
        encoding="utf-8",
    )
    (cypher_dir / "04_create_indexes.cypher").write_text(render_indexes(), encoding="utf-8")
    (cypher_dir / "05_validation_queries.cypher").write_text(
        render_validation_queries(), encoding="utf-8"
    )


def create_indexes(client, graph: str) -> None:
    for label, prop, _reason in INDEXES:
        query = f"CREATE INDEX FOR (n:{label}) ON (n.{prop})"
        try:
            graph_query(client, graph, query)
        except RuntimeError as exc:
            if is_already_exists(exc):
                continue
            raise
    label_count = len({label for label, _prop, _reason in INDEXES})
    wait_for_status(client, graph, "db.indexes", expected_count=label_count)


def create_constraints(client, graph: str) -> None:
    for label, prop in UNIQUE_CONSTRAINTS:
        execute_redis_command(
            client,
            "GRAPH.CONSTRAINT",
            "CREATE",
            graph,
            "UNIQUE",
            "NODE",
            label,
            "PROPERTIES",
            1,
            prop,
        )
    wait_for_status(client, graph, "db.constraints", expected_count=len(UNIQUE_CONSTRAINTS))


def list_graphs(client) -> List[str]:
    listed = client.execute_command("GRAPH.LIST")
    if not listed:
        return []
    if isinstance(listed, (str, bytes)):
        return [listed.decode() if isinstance(listed, bytes) else listed]
    names = []
    for item in listed:
        if isinstance(item, bytes):
            names.append(item.decode())
        else:
            names.append(str(item))
    return names


def delete_all_graphs(client, configured_graph: str) -> List[str]:
    names = list_graphs(client)
    if configured_graph not in names:
        names.append(configured_graph)
    deleted = []
    for name in names:
        graph_delete(client, name)
        deleted.append(name)
    return deleted


def load_graph(client, graph: str, ontology: Dict[str, Any], timestamp: str) -> None:
    for label in RETIRED_LABELS:
        graph_query(client, graph, f"MATCH (n:{label}) DETACH DELETE n")
    reconcile_source_entities(client, graph, ontology)
    for index, node in enumerate(ontology["nodes"]):
        graph_query(client, graph, render_node(f"n{index}", node, timestamp))
    for index, edge in enumerate(ontology["edges"]):
        graph_query(client, graph, render_edge(f"r{index}", f"a{index}", edge, f"b{index}"))


def reconcile_source_entities(client, graph: str, ontology: Dict[str, Any]) -> None:
    expected_by_label: Dict[str, set[str]] = {label: set() for label in SOURCE_DERIVED_LABELS}
    for node in ontology["nodes"]:
        if node["label"] in expected_by_label:
            expected_by_label[node["label"]].add(node["id"])

    from ontology_csv import ID_PROPERTY

    for label, expected_ids in expected_by_label.items():
        id_property = ID_PROPERTY[label]
        result = graph_query(
            client,
            graph,
            f"MATCH (n:{label}) RETURN n.{id_property} AS node_id",
        )
        current_ids = {
            str(row["node_id"])
            for row in rows_as_dicts(result)
            if row.get("node_id") is not None
        }
        for stale_id in sorted(current_ids - expected_ids):
            graph_query(
                client,
                graph,
                f"MATCH (n:{label} {{{id_property}: {cypher_literal(stale_id)}}}) "
                "DETACH DELETE n",
            )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Load the enterprise KPI ontology into FalkorDB.")
    parser.add_argument("--write-cypher", action="store_true", help="Write Cypher artifacts and exit.")
    parser.add_argument("--reset", action="store_true", help="Delete every FalkorDB graph, then load this one.")
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Ontology CSV. Defaults to ONTOLOGY_FILE in .env, or ontology/enterprise_kpi_ontology.csv.",
    )
    parser.add_argument(
        "--records",
        type=Path,
        default=None,
        help="CSV or JSON source for vocabulary and measure definitions. "
        "Defaults to INPUT_DATA_FILE in .env or repository sample records.",
    )
    parser.add_argument("--table-name", default=None, help="Override BQ_Table.name.")
    parser.add_argument("--project", default=None, help="Override BQ_Table.project.")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    load_env_file(root / ".env")
    settings = connection_settings()
    csv_path = args.input or configured_path("ONTOLOGY_FILE", default_csv_path())
    if csv_path is None:
        raise ValueError("No ontology file configured. Set ONTOLOGY_FILE in .env or pass --input.")
    records_path = args.records or configured_path("INPUT_DATA_FILE")
    records = load_records(records_path) if records_path else load_sample_vocabulary_records()
    ontology = load_ontology(csv_path)
    ontology = keep_schema_only(ontology)
    set_table_source_identity(
        ontology,
        args.table_name or os.environ.get("BIGQUERY_TABLE_NAME"),
        args.project or os.environ.get("BIGQUERY_PROJECT") or None,
    )
    added = add_value_nodes(ontology, records)
    measures = add_kpi_measures(ontology, records)
    write_artifacts(root, ontology, settings["graph"])
    print(
        f"wrote Cypher artifacts for {len(ontology['nodes'])} nodes "
        f"and {len(ontology['edges'])} edges from {csv_path.name}"
    )
    record_source = records_path.name if records_path else "sample_data.json and sample_data.csv"
    print(f"added {added} vocabulary values from {record_source}")
    print(f"added {measures} KPI measures for metrics that were not already defined")
    if args.write_cypher:
        return 0

    client = connect(
        settings["host"], settings["port"], settings["username"], settings["password"]
    )
    wait_until_ready(client)
    if args.reset:
        deleted = delete_all_graphs(client, settings["graph"])
        print("deleted graphs: " + ", ".join(deleted))

    create_indexes(client, settings["graph"])
    create_constraints(client, settings["graph"])
    timestamp = utc_now()
    load_graph(client, settings["graph"], ontology, timestamp)
    print(
        f"loaded {len(ontology['nodes'])} nodes and {len(ontology['edges'])} edges "
        f"into {settings['graph']} at {timestamp}"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
