"""Read the enterprise KPI ontology CSV into nodes and edges.

The CSV is the source of truth. Sample nodes whose origin is NOT_CREATED
or FUTURE are placeholders, not graph data. Cell values are not loaded.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from normalize import normalize_token, project_root


SKIP_ORIGINS = {"NOT_CREATED", "FUTURE"}

ID_PROPERTY = {
    "BQ_Table": "table_id",
    "BQ_column": "column_id",
    "BQ_KPIMeasure": "measure_id",
    "LookMLKPIMeasure": "measure_id",
    "Metric": "metric_id",
    "Source": "source_id",
    "Market": "market_id",
    "Segment": "segment_id",
    "Channel": "channel_id",
    "Product": "product_id",
    "MetricGroup": "group_id",
    "MetricLevel": "level_id",
    "Unit": "unit_id",
    "Corridor": "corridor_id",
}

RETIRED_LABELS = ("ReportingPeriod", "KPIObservation", "RiskProfile", "KPIMeasure")

INDEXES = [
    ("BQ_Table", "table_id", "Identity lookup for the physical table."),
    ("BQ_Table", "name", "Find agentic_kg_usecase by physical table name."),
    ("BQ_column", "column_id", "Identity lookup for a physical column."),
    ("BQ_column", "name", "Find a column by its BigQuery name."),
    ("BQ_column", "label", "Match a question to a column label such as Year."),
    ("BQ_KPIMeasure", "measure_id", "Identity lookup for a BigQuery measure definition."),
    ("BQ_KPIMeasure", "name", "Match a question to a BigQuery measure name."),
    ("LookMLKPIMeasure", "measure_id", "Identity lookup for a LookML measure definition."),
    ("LookMLKPIMeasure", "name", "Match a LookML measure token."),
    ("LookMLKPIMeasure", "label", "Match a question to a LookML measure label."),
    ("Metric", "metric_id", "Identity lookup for a metric term."),
    ("Metric", "name", "Match a metric word such as Revenue."),
    ("Source", "source_id", "Identity lookup for a source term."),
    ("Source", "name", "Match a source code."),
    ("Market", "market_id", "Identity lookup for a market term."),
    ("Market", "name", "Match a market code such as SGH."),
    ("Segment", "segment_id", "Identity lookup for a segment term."),
    ("Segment", "name", "Match a segment name."),
    ("Channel", "channel_id", "Identity lookup for a channel term."),
    ("Channel", "name", "Match a channel name."),
    ("Product", "product_id", "Identity lookup for a product term."),
    ("Product", "name", "Match a product name."),
    ("MetricGroup", "group_id", "Identity lookup for a group term."),
    ("MetricGroup", "name", "Match a GROUP_ALL term."),
    ("MetricLevel", "level_id", "Identity lookup for a metric tier."),
    ("Unit", "unit_id", "Identity lookup for a unit term."),
]

UNIQUE_CONSTRAINTS = [
    ("BQ_Table", "table_id"),
    ("BQ_column", "column_id"),
    ("BQ_KPIMeasure", "measure_id"),
    ("LookMLKPIMeasure", "measure_id"),
    ("Metric", "metric_id"),
    ("Source", "source_id"),
    ("Market", "market_id"),
    ("Segment", "segment_id"),
    ("Channel", "channel_id"),
    ("Product", "product_id"),
    ("MetricGroup", "group_id"),
    ("MetricLevel", "level_id"),
    ("Unit", "unit_id"),
]

LOOKML_PROVENANCE = '{"platform":"LOOKML","kind":"measure"}'

VOCABULARY_LABELS = (
    "Metric",
    "Source",
    "Market",
    "Segment",
    "Channel",
    "Product",
    "MetricGroup",
    "MetricLevel",
    "Unit",
    "Corridor",
)

SOURCE_DERIVED_LABELS = (
    "BQ_KPIMeasure",
    "LookMLKPIMeasure",
    *VOCABULARY_LABELS,
)


def default_csv_path() -> Path:
    return project_root() / "ontology" / "enterprise_kpi_ontology.csv"


def load_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _take_json(text: str) -> Tuple[str, str]:
    body = text.lstrip()
    if not body.startswith("{"):
        raise ValueError(f"Expected a JSON object, found: {body[:80]!r}")
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(body):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                blob = body[: index + 1]
                json.loads(blob)
                return blob, body[index + 1 :]
    raise ValueError(f"Unclosed JSON object: {body[:80]!r}")


def _before(text: str, marker: str, label: str) -> Tuple[str, str]:
    index = text.find(marker)
    if index < 0:
        raise ValueError(f"{label} is missing {marker!r} in: {text[:120]!r}")
    return text[:index].strip(), text[index + len(marker) :]


def parse_column_reading(reading: str) -> Dict[str, str]:
    matched = re.match(
        r"label (?P<label>.*?)\. name (?P<name>\S+)\. type (?P<type>\S+)\. "
        r"mode (?P<mode>\S+)\. format (?P<format>\S+)\. enum (?P<enum>.*?)\. metadata ",
        reading,
    )
    if not matched:
        raise ValueError(f"BQ_column reading did not match: {reading[:160]!r}")
    rest = reading[matched.end() :]
    metadata, rest = _take_json(rest)
    _, rest = _before(rest, "description ", "BQ_column")
    description, rest = _before(rest, " table_details ", "BQ_column description")
    table_details, rest = _take_json(rest)
    _, rest = _before(rest.lstrip("."), "provenance ", "BQ_column")
    provenance, _rest = _take_json(rest)
    enum = matched.group("enum").strip()
    if enum == "(open)":
        enum = ""
    return {
        "label": matched.group("label").strip(),
        "name": matched.group("name").strip(),
        "type": matched.group("type").strip(),
        "mode": matched.group("mode").strip(),
        "format": matched.group("format").strip(),
        "enum": enum,
        "metadata": metadata,
        "description": description,
        "table_details": table_details,
        "provenance": provenance,
        "status": "ACTIVE",
    }


def parse_lookml_reading(reading: str) -> Dict[str, str]:
    matched = re.match(
        r"One node\. name (?P<name>.*?)\. type (?P<type>.*?)\. sql (?P<sql>.*?)\. "
        r"sql_column (?P<sql_column>\S+)\. label (?P<label>.*?)\. description ",
        reading,
    )
    if not matched:
        raise ValueError(f"LookML reading did not match: {reading[:160]!r}")
    rest = reading[matched.end() :]
    description, rest = _before(rest, " value_format_name ", "LookML description")
    value_format, rest = _before(rest, ". filters ", "LookML format")
    filters, _rest = _take_json(rest)
    return {
        "name": matched.group("name").strip(),
        "type": matched.group("type").strip(),
        "sql": matched.group("sql").strip(),
        "sql_column": matched.group("sql_column").strip(),
        "label": matched.group("label").strip(),
        "description": description,
        "value_format_name": value_format.strip(),
        "filters": filters,
        "provenance": LOOKML_PROVENANCE,
        "status": "ACTIVE",
    }


def parse_bigquery_measure_reading(reading: str) -> Dict[str, str]:
    matched = re.match(
        r"One node\. name (?P<name>.*?)\. value_column (?P<value_column>\S+)\. "
        r"aggregation (?P<aggregation>\S+)\. filters ",
        reading,
    )
    if not matched:
        raise ValueError(f"BigQuery measure reading did not match: {reading[:160]!r}")
    filters, _rest = _take_json(reading[matched.end() :])
    return {
        "name": matched.group("name").strip(),
        "value_column": matched.group("value_column").strip(),
        "aggregation": matched.group("aggregation").strip(),
        "filters": filters,
        "status": "ACTIVE",
    }


def _table_properties(rows: List[Dict[str, str]], graph_id: str) -> Dict[str, str]:
    properties: Dict[str, str] = {"table_id": graph_id, "status": "ACTIVE"}
    for row in rows:
        if row["section"] != "ATTRIBUTE" or row["entity"] != "BQ_Table":
            continue
        attribute = row["attribute"]
        if attribute in {"created_at", "updated_at", "table_id"}:
            continue
        properties[attribute] = row["example"]
    required = ("name", "platform", "project", "use_case", "description", "metadata", "provenance")
    missing = [name for name in required if name not in properties]
    if missing:
        raise ValueError(f"BQ_Table attributes missing from the CSV: {missing}")
    return properties


def _vocabulary_properties(row: Dict[str, str]) -> Dict[str, Any]:
    label = row["entity"]
    graph_id = row["graph_id"]
    example = row["example"]
    reading = row["reading"]
    token = graph_id.split(":", 1)[1]
    properties: Dict[str, Any] = {"status": "ACTIVE"}
    if label == "Metric":
        properties.update(
            {"metric_id": graph_id, "name": example, "normalized_name": normalize_token(example)}
        )
    elif label == "Source":
        properties.update(
            {"source_id": graph_id, "name": example, "normalized_name": normalize_token(example)}
        )
    elif label == "Market":
        properties.update(
            {
                "market_id": graph_id,
                "name": example,
                "normalized_name": normalize_token(example),
                "market_type": "UNCLASSIFIED",
            }
        )
    elif label == "Segment":
        properties.update(
            {"segment_id": graph_id, "name": example, "normalized_name": normalize_token(example)}
        )
    elif label == "Channel":
        properties.update(
            {"channel_id": graph_id, "name": example, "normalized_name": normalize_token(example)}
        )
    elif label == "Product":
        properties.update(
            {"product_id": graph_id, "name": example, "normalized_name": normalize_token(example)}
        )
    elif label == "MetricGroup":
        properties.update(
            {
                "group_id": graph_id,
                "name": example,
                "normalized_name": normalize_token(example),
                "source_field": "GROUP_ALL",
            }
        )
    elif label == "MetricLevel":
        rank_match = re.search(r"rank of [A-Z]\d+ is (\d+)", reading)
        if rank_match is None:
            raise ValueError(f"MetricLevel rank missing from: {reading}")
        properties.update(
            {
                "level_id": graph_id,
                "code": example,
                "name": example,
                "rank": int(rank_match.group(1)),
            }
        )
    elif label == "Unit":
        symbol = re.search(r"source_symbol is (.+?)\.", reading)
        inferred = re.search(r"currency_inferred is (true|false)", reading)
        if symbol is None or inferred is None:
            raise ValueError(f"Unit symbol missing from: {reading}")
        properties.update(
            {
                "unit_id": graph_id,
                "code": token,
                "name": example,
                "source_symbol": symbol.group(1),
                "currency_inferred": inferred.group(1) == "true",
            }
        )
    elif label == "Corridor":
        raise ValueError("A Corridor vocabulary node needs a real name. This sample has none.")
    else:
        raise ValueError(f"No vocabulary mapping for {label}")
    return properties


def _node_from_row(row: Dict[str, str], rows: List[Dict[str, str]]) -> Dict[str, Any]:
    label = row["entity"]
    graph_id = row["graph_id"]
    if label not in ID_PROPERTY:
        raise ValueError(f"SAMPLE_NODE uses an unknown entity {label}")
    if label == "BQ_Table":
        properties: Dict[str, Any] = _table_properties(rows, graph_id)
    elif label == "BQ_column":
        properties = parse_column_reading(row["reading"])
        properties["column_id"] = graph_id
    elif label == "LookMLKPIMeasure":
        properties = parse_lookml_reading(row["reading"])
        properties["measure_id"] = graph_id
    elif label == "BQ_KPIMeasure":
        properties = parse_bigquery_measure_reading(row["reading"])
        properties["measure_id"] = graph_id
    elif label in VOCABULARY_LABELS:
        properties = _vocabulary_properties(row)
    else:
        raise ValueError(f"Do not load {label}. It is not part of the query-time model.")
    if properties.get(ID_PROPERTY[label]) != graph_id:
        raise ValueError(f"{label} id {properties.get(ID_PROPERTY[label])} != {graph_id}")
    return {
        "label": label,
        "id_property": ID_PROPERTY[label],
        "id": graph_id,
        "properties": properties,
    }


def load_ontology(path: Path) -> Dict[str, Any]:
    rows = load_rows(path)
    nodes = []
    seen = set()
    for row in rows:
        if row["section"] != "SAMPLE_NODE":
            continue
        if row["origin"] in SKIP_ORIGINS:
            continue
        if row["entity"] in RETIRED_LABELS:
            raise ValueError(f"Refusing to load retired entity {row['entity']}")
        node = _node_from_row(row, rows)
        if node["id"] in seen:
            raise ValueError(f"Duplicate graph id {node['id']}")
        seen.add(node["id"])
        nodes.append(node)

    by_id = {node["id"]: node for node in nodes}
    edges = []
    for row in rows:
        if row["section"] != "SAMPLE_EDGE":
            continue
        if row["origin"] in SKIP_ORIGINS:
            continue
        source_id = row["graph_id"]
        target_id = row["to_graph_id"]
        if source_id not in by_id or target_id not in by_id:
            raise ValueError(
                f"Edge {row['relationship']} {source_id} -> {target_id} is missing an endpoint"
            )
        if row["from_entity"] in RETIRED_LABELS or row["to_entity"] in RETIRED_LABELS:
            raise ValueError(f"Refusing retired edge {row['relationship']}")
        edges.append(
            {
                "type": row["relationship"],
                "from_id": source_id,
                "to_id": target_id,
                "from_label": by_id[source_id]["label"],
                "to_label": by_id[target_id]["label"],
                "origin": row["origin"],
            }
        )

    _check_shape(nodes, edges)
    return {"nodes": nodes, "edges": edges, "source": str(path)}


def set_table_source_identity(
    ontology: Dict[str, Any],
    table_name: str | None = None,
    project: str | None = None,
) -> None:
    table_nodes = [node for node in ontology["nodes"] if node["label"] == "BQ_Table"]
    if len(table_nodes) != 1:
        raise ValueError(f"Expected one BQ_Table node, found {len(table_nodes)}.")
    properties = table_nodes[0]["properties"]
    if table_name is not None:
        if not table_name.strip():
            raise ValueError("BigQuery table name cannot be blank.")
        properties["name"] = table_name
    if project is not None:
        if not project.strip():
            raise ValueError("BigQuery project cannot be blank.")
        properties["project"] = project


def keep_schema_only(ontology: Dict[str, Any]) -> Dict[str, Any]:
    """Keep table/column schema from the ontology, not its illustrative sample entities."""
    schema_nodes = [
        node for node in ontology["nodes"] if node["label"] in {"BQ_Table", "BQ_column"}
    ]
    schema_ids = {node["id"] for node in schema_nodes}
    schema_edges = [
        edge
        for edge in ontology["edges"]
        if edge["from_id"] in schema_ids and edge["to_id"] in schema_ids
    ]
    return {
        **ontology,
        "nodes": schema_nodes,
        "edges": schema_edges,
    }


def _check_shape(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> None:
    labels = {}
    for node in nodes:
        labels[node["label"]] = labels.get(node["label"], 0) + 1
    if labels.get("BQ_Table") != 1:
        raise ValueError(f"Expected one BQ_Table, found {labels.get('BQ_Table')}")
    if labels.get("BQ_column") != 29:
        raise ValueError(f"Expected 29 BQ_column nodes, found {labels.get('BQ_column')}")
    if labels.get("BQ_KPIMeasure") != 3 or labels.get("LookMLKPIMeasure") != 3:
        raise ValueError(f"Expected 3 BigQuery and 3 LookML measures, found {labels}")
    for retired in RETIRED_LABELS:
        if labels.get(retired):
            raise ValueError(f"Retired label {retired} is present")

    has_column = [edge for edge in edges if edge["type"] == "HAS_COLUMN"]
    if len(has_column) != 29:
        raise ValueError(f"Expected 29 HAS_COLUMN edges, found {len(has_column)}")

    for measure_id, value_column in (
        ("BQMEASURE:revenue_ytd_actual", "YTD_ACTUAL"),
        ("BQMEASURE:revenue_ytd_plan", "YTD_PLAN"),
        ("BQMEASURE:revenue_fy_plan", "FY_PLAN"),
    ):
        used = {
            edge["to_id"].rsplit(".", 1)[-1]
            for edge in edges
            if edge["type"] == "USES_COLUMN" and edge["from_id"] == measure_id
        }
        expected = {value_column, "SOURCE", "METRIC"}
        if used != expected:
            raise ValueError(f"{measure_id} USES_COLUMN {used} != {expected}")
        on_table = [
            edge
            for edge in edges
            if edge["type"] == "ON_TABLE" and edge["from_id"] == measure_id
        ]
        if len(on_table) != 1 or on_table[0]["to_id"] != "BQ_TABLE:agentic_kg_usecase":
            raise ValueError(f"{measure_id} is not ON_TABLE the physical table")


def column_roles(node: Dict[str, Any]) -> List[str]:
    metadata = json.loads(node["properties"]["metadata"])
    return list(metadata["column_role"])
