"""Read the local ontology CSV into the table and column schema graph."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from .kpi_measures import IDENTIFIER

ID_PROPERTIES = {
    "BQ_Table": "table_id",
    "BQ_column": "column_id",
}
TABLE_ID = "BQ_TABLE:agentic_kg_usecase"


def load_schema(path: Path, table_name: str, project: str) -> dict[str, Any]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    sample_nodes = [
        row
        for row in rows
        if row["section"] == "SAMPLE_NODE" and row["entity"] in ID_PROPERTIES
        and row["origin"] not in {"NOT_CREATED", "FUTURE"}
    ]
    if not sample_nodes:
        raise ValueError(f"No table/column schema nodes found in {path}.")

    nodes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    for row in sample_nodes:
        label = row["entity"]
        graph_id = row["graph_id"]
        if not graph_id or graph_id in node_ids:
            raise ValueError(f"Missing or duplicate schema graph id {graph_id!r}.")
        id_property = ID_PROPERTIES[label]
        props: dict[str, Any] = {id_property: graph_id, "status": "ACTIVE"}
        if label == "BQ_Table":
            for attribute in rows:
                if attribute["section"] != "ATTRIBUTE" or attribute["graph_id"] != graph_id:
                    continue
                name = attribute["attribute"]
                if name in {"created_at", "updated_at", id_property}:
                    continue
                props[name] = attribute["example"]
            props["name"] = table_name
            props["project"] = project
        else:
            props.update(_parse_column_reading(row["reading"]))
        nodes.append(
            {
                "label": label,
                "id_property": id_property,
                "id": graph_id,
                "properties": props,
            }
        )
        node_ids.add(graph_id)

    if sum(node["label"] == "BQ_Table" for node in nodes) != 1:
        raise ValueError("Ontology must define exactly one BQ_Table.")
    columns = {node["properties"].get("name"): node for node in nodes if node["label"] == "BQ_column"}
    if not columns:
        raise ValueError("Ontology must define at least one BQ_column.")

    edges: list[dict[str, str]] = []
    for row in rows:
        if row["section"] != "SAMPLE_EDGE" or row["origin"] in {"NOT_CREATED", "FUTURE"}:
            continue
        if row["graph_id"] not in node_ids or row["to_graph_id"] not in node_ids:
            continue
        if row["relationship"] != "HAS_COLUMN":
            continue
        edges.append(
            {
                "type": row["relationship"],
                "from_id": row["graph_id"],
                "to_id": row["to_graph_id"],
                "from_label": row["from_entity"],
                "to_label": row["to_entity"],
                "origin": row["origin"],
            }
        )
    if len(edges) != len(columns):
        raise ValueError(f"Ontology must link every BQ_column with HAS_COLUMN; found {len(edges)} links.")
    return {"nodes": nodes, "edges": edges, "columns": columns}


def _parse_column_reading(reading: str) -> dict[str, Any]:
    matched = re.match(
        r"label (?P<label>.*?)\. name (?P<name>\S+)\. type (?P<type>\S+)\. "
        r"mode (?P<mode>\S+)\. format (?P<format>\S+)\. enum (?P<enum>.*?)\. metadata ",
        reading,
    )
    if not matched:
        raise ValueError(f"BQ_column reading did not match ontology format: {reading[:160]!r}")
    metadata, rest = _take_json(reading[matched.end() :])
    _, rest = _before(rest, "description ", "BQ_column metadata")
    description, rest = _before(rest, " table_details ", "BQ_column description")
    table_details, rest = _take_json(rest)
    _, rest = _before(
        rest.lstrip(), "provenance ", "BQ_column table_details"
    )
    provenance, _ = _take_json(rest)
    enum = matched.group("enum").strip()
    return {
        "label": matched.group("label").strip(),
        "name": matched.group("name").strip(),
        "type": matched.group("type").strip(),
        "mode": matched.group("mode").strip(),
        "format": matched.group("format").strip(),
        "enum": "" if enum == "(open)" else enum,
        "metadata": metadata,
        "description": description,
        "table_details": table_details,
        "provenance": provenance,
        "status": "ACTIVE",
    }


def _take_json(text: str) -> tuple[str, str]:
    body = text.lstrip()
    if not body.startswith("{"):
        raise ValueError(f"Expected JSON object in ontology reading: {body[:80]!r}")
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
                value = body[: index + 1]
                json.loads(value)
                return value, body[index + 1 :]
    raise ValueError(f"Unclosed JSON object in ontology reading: {body[:80]!r}")


def _before(text: str, marker: str, context: str) -> tuple[str, str]:
    position = text.find(marker)
    if position < 0:
        raise ValueError(f"{context} is missing {marker!r} in ontology reading.")
    return text[:position].strip(), text[position + len(marker) :]


def check_config_columns(config: dict[str, Any], schema: dict[str, Any]) -> None:
    available = set(schema["columns"])
    requested = {
        mapping["falkordb_column"] for mapping in config["vocabulary_mappings"]
    }
    requested.update(
        measure["falkordb_column"] for measure in config["kpi_definitions"]
    )
    requested.update(
        column
        for measure in config["kpi_definitions"]
        for column in measure.get("filters", {})
    )
    missing = sorted(requested - available)
    if missing:
        raise ValueError("Ontology is missing configured BQ_column nodes: " + ", ".join(missing))
    for column in requested:
        if not IDENTIFIER.fullmatch(column):
            raise ValueError(f"Invalid ontology column name in config: {column!r}.")
