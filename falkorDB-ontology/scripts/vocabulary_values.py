"""Add one vocabulary node per distinct value in the KPI extract.

BQ_column is the hub. Each value DESCRIBES_COLUMN that column, and the
column is already linked to BQ_Table with HAS_COLUMN. Nulls create no node.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Set, Tuple

from fact_graph import cypher_literal
from falkor_client import graph_query, rows_as_dicts
from normalize import canonicalize_record, level_entity, named_entity, unit_entity


TABLE_NAME = "agentic_kg_usecase"

# Canonical field, node label, id prefix, physical column name.
VALUE_FIELDS: Tuple[Tuple[str, str, str, str], ...] = (
    ("source", "Source", "SOURCE", "SOURCE"),
    ("market", "Market", "MARKET", "MARKET"),
    ("metric", "Metric", "METRIC", "METRIC"),
    ("segment", "Segment", "SEGMENT", "SEGMENT"),
    ("channel", "Channel", "CHANNEL", "CHANNEL"),
    ("product_type", "Product", "PRODUCT", "PRODUCT_TYPE"),
    ("group_all", "MetricGroup", "GROUP", "GROUP_ALL"),
    ("metric_type", "MetricLevel", "LEVEL", "METRIC_TYPE"),
    ("unit_type", "Unit", "UNIT", "UNIT_TYPE"),
    ("corridor", "Corridor", "CORRIDOR", "CORRIDOR"),
)


def column_id(column_name: str) -> str:
    return f"BQ_COL:{TABLE_NAME}.{column_name}"


def load_sample_vocabulary_records() -> List[Dict[str, Any]]:
    """Distinct values from the JSON sample and the CSV sample, whichever files exist."""
    from record_io import default_csv_path, default_json_path, load_records

    records: List[Dict[str, Any]] = []
    paths = [path for path in (default_json_path(), default_csv_path()) if path.exists()]
    if not paths:
        raise ValueError("No sample_data.json or sample_data.csv file was found.")
    for path in paths:
        records.extend(load_records(path))
    return records


def add_value_nodes(ontology: Dict[str, Any], records: Sequence[Dict[str, Any]]) -> int:
    """Merge distinct extract values into an ontology already loaded from the CSV."""
    by_id = {node["id"]: node for node in ontology["nodes"]}
    edge_keys = {(edge["from_id"], edge["type"], edge["to_id"]) for edge in ontology["edges"]}
    added = 0
    for raw in records:
        canonical, _unknown = canonicalize_record(raw)
        for field, _label, _prefix, column_name in VALUE_FIELDS:
            value = canonical.get(field)
            if value is None:
                continue
            if not isinstance(value, str):
                raise ValueError(f"{field} must be text, received {value!r}.")
            entity = _entity(field, value)
            target_id = column_id(column_name)
            if target_id not in by_id:
                raise ValueError(f"Column {column_name} is not in the ontology.")
            if entity["id"] not in by_id:
                ontology["nodes"].append(entity)
                by_id[entity["id"]] = entity
                added += 1
            edge_key = (entity["id"], "DESCRIBES_COLUMN", target_id)
            if edge_key in edge_keys:
                continue
            ontology["edges"].append(
                {
                    "type": "DESCRIBES_COLUMN",
                    "from_id": entity["id"],
                    "to_id": target_id,
                    "from_label": entity["label"],
                    "to_label": "BQ_column",
                    "origin": "VOCABULARY",
                }
            )
            edge_keys.add(edge_key)
    return added


def pending_vocabulary(
    records: Sequence[Dict[str, Any]],
    existing_ids: Set[str],
    existing_edges: Set[Tuple[str, str, str]],
    timestamp: str,
) -> List[str]:
    """Cypher for value nodes and DESCRIBES_COLUMN edges that are not in the graph yet."""
    ontology = _column_stubs()
    add_value_nodes(ontology, records)
    statements: List[str] = []
    for node in ontology["nodes"]:
        if node["label"] == "BQ_column" or node["id"] in existing_ids:
            continue
        properties = dict(node["properties"])
        properties["created_at"] = timestamp
        properties["updated_at"] = timestamp
        statements.append(
            "\n".join(
                [
                    f"MERGE (n:{node['label']} {{{node['id_property']}: {cypher_literal(node['id'])}}})",
                    f"ON CREATE SET {_assignments('n', properties)}",
                ]
            )
        )
    for edge in ontology["edges"]:
        key = (edge["from_id"], edge["type"], edge["to_id"])
        if key in existing_edges:
            continue
        statements.append(
            "\n".join(
                [
                    f"MATCH (a:{edge['from_label']} {{{_id_property(edge['from_label'])}: {cypher_literal(edge['from_id'])}}})",
                    f"MATCH (b:{edge['to_label']} {{column_id: {cypher_literal(edge['to_id'])}}})",
                    f"MERGE (a)-[r:{edge['type']}]->(b)",
                    "ON CREATE SET r.origin = 'VOCABULARY'",
                ]
            )
        )
    return statements


def persist_vocabulary(client, graph: str, records: Sequence[Dict[str, Any]], timestamp: str) -> int:
    statements = pending_vocabulary(
        records,
        _existing_ids(client, graph),
        _existing_edges(client, graph),
        timestamp,
    )
    for statement in statements:
        graph_query(client, graph, statement)
    return len(statements)


def _column_stubs() -> Dict[str, Any]:
    nodes = []
    for _field, _label, _prefix, column_name in VALUE_FIELDS:
        node_id = column_id(column_name)
        nodes.append(
            {
                "label": "BQ_column",
                "id_property": "column_id",
                "id": node_id,
                "properties": {"column_id": node_id},
            }
        )
    return {"nodes": nodes, "edges": []}


def _existing_ids(client, graph: str) -> Set[str]:
    result = graph_query(
        client,
        graph,
        """
        MATCH (n)
        WHERE n:Source OR n:Market OR n:Metric OR n:Segment OR n:Channel
           OR n:Product OR n:MetricGroup OR n:MetricLevel OR n:Unit OR n:Corridor
        RETURN coalesce(
                 n.source_id, n.market_id, n.metric_id, n.segment_id, n.channel_id,
                 n.product_id, n.group_id, n.level_id, n.unit_id, n.corridor_id
               ) AS id
        """,
    )
    return {str(row["id"]) for row in rows_as_dicts(result) if row.get("id")}


def _existing_edges(client, graph: str) -> Set[Tuple[str, str, str]]:
    result = graph_query(
        client,
        graph,
        """
        MATCH (n)-[r:DESCRIBES_COLUMN]->(c:BQ_column)
        WHERE n:Source OR n:Market OR n:Metric OR n:Segment OR n:Channel
           OR n:Product OR n:MetricGroup OR n:MetricLevel OR n:Unit OR n:Corridor
        RETURN coalesce(
                 n.source_id, n.market_id, n.metric_id, n.segment_id, n.channel_id,
                 n.product_id, n.group_id, n.level_id, n.unit_id, n.corridor_id
               ) AS src,
               c.column_id AS dst
        """,
    )
    return {
        (str(row["src"]), "DESCRIBES_COLUMN", str(row["dst"]))
        for row in rows_as_dicts(result)
        if row.get("src") and row.get("dst")
    }


def _assignments(alias: str, properties: Dict[str, Any]) -> str:
    return ", ".join(f"{alias}.{key} = {cypher_literal(properties[key])}" for key in properties)


def _entity(field: str, value: str) -> Dict[str, Any]:
    if field == "metric_type":
        return level_entity(value)
    if field == "unit_type":
        entity, _reasons = unit_entity(value)
        return entity
    for candidate, label, prefix, _column in VALUE_FIELDS:
        if candidate == field:
            extra = None
            if field == "market":
                extra = {"market_type": "UNCLASSIFIED"}
            elif field == "group_all":
                extra = {"source_field": "GROUP_ALL"}
            return named_entity(label, _id_property(label), prefix, value, extra)
    raise ValueError(f"No vocabulary field {field}.")


def _id_property(label: str) -> str:
    from ontology_csv import ID_PROPERTY

    return ID_PROPERTY[label]
