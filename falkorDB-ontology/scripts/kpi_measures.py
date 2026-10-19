"""One BQ_KPIMeasure per distinct metric in the extract.

The three Revenue measures stay as declared in the ontology CSV. Every other
metric becomes a query definition: filter SOURCE and METRIC, read YTD_ACTUAL,
and aggregate with none so a score is not summed. ON_TABLE and USES_COLUMN
give the agent the table and columns.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Sequence, Set

from fact_graph import cypher_literal
from falkor_client import graph_query, rows_as_dicts
from normalize import canonicalize_record, normalize_token
from vocabulary_values import column_id


TABLE_ID = "BQ_TABLE:agentic_kg_usecase"
VALUE_COLUMN = "YTD_ACTUAL"


def add_kpi_measures(ontology: Dict[str, Any], records: Sequence[Dict[str, Any]]) -> int:
    by_id = {node["id"]: node for node in ontology["nodes"]}
    if TABLE_ID not in by_id:
        raise ValueError("BQ_Table is not in the ontology.")
    for name in (VALUE_COLUMN, "SOURCE", "METRIC"):
        if column_id(name) not in by_id:
            raise ValueError(f"Column {name} is not in the ontology.")
    edge_keys = {(edge["from_id"], edge["type"], edge["to_id"]) for edge in ontology["edges"]}
    covered = _metrics_already_defined(ontology)
    added = 0
    for metric, sources in _metrics(records).items():
        if metric in covered:
            continue
        measure_id = "BQMEASURE:" + normalize_token(metric).lower()
        if measure_id in by_id:
            continue
        filters: Dict[str, str] = {}
        if len(sources) == 1:
            filters["SOURCE"] = next(iter(sources))
        filters["METRIC"] = metric
        node = {
            "label": "BQ_KPIMeasure",
            "id_property": "measure_id",
            "id": measure_id,
            "properties": {
                "measure_id": measure_id,
                "name": f"{metric} YTD Actual",
                "value_column": VALUE_COLUMN,
                "aggregation": "none",
                "filters": json.dumps(filters, separators=(",", ":"), ensure_ascii=False),
                "status": "ACTIVE",
            },
        }
        ontology["nodes"].append(node)
        by_id[measure_id] = node
        added += 1
        _edge(ontology, edge_keys, measure_id, "ON_TABLE", "BQ_Table", TABLE_ID)
        for column_name in [VALUE_COLUMN, *filters.keys()]:
            _edge(
                ontology,
                edge_keys,
                measure_id,
                "USES_COLUMN",
                "BQ_column",
                column_id(column_name),
            )
    return added


def persist_kpi_measures(client, graph: str, records: Sequence[Dict[str, Any]], timestamp: str) -> int:
    existing = _existing_measure_ids(client, graph)
    ontology = _stubs()
    add_kpi_measures(ontology, records)
    statements: List[str] = []
    for node in ontology["nodes"]:
        if node["label"] != "BQ_KPIMeasure" or node["id"] in existing:
            continue
        properties = dict(node["properties"])
        properties["created_at"] = timestamp
        properties["updated_at"] = timestamp
        statements.append(
            "\n".join(
                [
                    f"MERGE (n:BQ_KPIMeasure {{measure_id: {cypher_literal(node['id'])}}})",
                    f"ON CREATE SET {_assignments('n', properties)}",
                ]
            )
        )
    for edge in ontology["edges"]:
        if edge["from_id"] in existing:
            continue
        target_property = "table_id" if edge["to_label"] == "BQ_Table" else "column_id"
        statements.append(
            "\n".join(
                [
                    f"MATCH (a:BQ_KPIMeasure {{measure_id: {cypher_literal(edge['from_id'])}}})",
                    f"MATCH (b:{edge['to_label']} {{{target_property}: {cypher_literal(edge['to_id'])}}})",
                    f"MERGE (a)-[r:{edge['type']}]->(b)",
                    "ON CREATE SET r.origin = 'BIGQUERY'",
                ]
            )
        )
    for statement in statements:
        graph_query(client, graph, statement)
    return len(statements)


def _metrics(records: Sequence[Dict[str, Any]]) -> Dict[str, Set[str]]:
    found: Dict[str, Set[str]] = {}
    for raw in records:
        canonical, _unknown = canonicalize_record(raw)
        metric = canonical.get("metric")
        if not isinstance(metric, str) or not metric:
            continue
        sources = found.setdefault(metric, set())
        source = canonical.get("source")
        if isinstance(source, str) and source:
            sources.add(source)
    return found


def _metrics_already_defined(ontology: Dict[str, Any]) -> Set[str]:
    covered = set()
    for node in ontology["nodes"]:
        if node["label"] != "BQ_KPIMeasure":
            continue
        raw_filters = node["properties"].get("filters") or "{}"
        parsed = json.loads(raw_filters) if isinstance(raw_filters, str) else raw_filters
        metric = parsed.get("METRIC")
        if isinstance(metric, str) and metric:
            covered.add(metric)
    return covered


def _edge(
    ontology: Dict[str, Any],
    edge_keys: Set[tuple],
    measure_id: str,
    relationship: str,
    target_label: str,
    target_id: str,
) -> None:
    key = (measure_id, relationship, target_id)
    if key in edge_keys:
        return
    ontology["edges"].append(
        {
            "type": relationship,
            "from_id": measure_id,
            "to_id": target_id,
            "from_label": "BQ_KPIMeasure",
            "to_label": target_label,
            "origin": "BIGQUERY",
        }
    )
    edge_keys.add(key)


def _stubs() -> Dict[str, Any]:
    nodes = [
        {
            "label": "BQ_Table",
            "id_property": "table_id",
            "id": TABLE_ID,
            "properties": {"table_id": TABLE_ID},
        }
    ]
    for name in (VALUE_COLUMN, "SOURCE", "METRIC"):
        node_id = column_id(name)
        nodes.append(
            {
                "label": "BQ_column",
                "id_property": "column_id",
                "id": node_id,
                "properties": {"column_id": node_id},
            }
        )
    return {"nodes": nodes, "edges": []}


def _existing_measure_ids(client, graph: str) -> Set[str]:
    result = graph_query(
        client,
        graph,
        "MATCH (m:BQ_KPIMeasure) RETURN m.measure_id AS measure_id",
    )
    return {str(row["measure_id"]) for row in rows_as_dicts(result) if row.get("measure_id")}


def _assignments(alias: str, properties: Dict[str, Any]) -> str:
    return ", ".join(f"{alias}.{key} = {cypher_literal(properties[key])}" for key in properties)
