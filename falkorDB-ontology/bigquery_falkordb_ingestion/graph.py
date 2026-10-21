"""FalkorDB access and idempotent ontology graph writes."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

import redis

ID_PROPERTIES = {
    "BQ_Table": "table_id",
    "BQ_column": "column_id",
    "BQ_KPIMeasure": "measure_id",
    "Source": "source_id",
    "Market": "market_id",
    "Metric": "metric_id",
    "MetricLevel": "level_id",
    "Segment": "segment_id",
    "MetricGroup": "group_id",
    "Channel": "channel_id",
    "Unit": "unit_id",
    "Product": "product_id",
    "Corridor": "corridor_id",
}


def load_env_file(path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def connect() -> redis.Redis:
    client = redis.Redis(
        host=os.environ.get("FALKORDB_HOST", "localhost"),
        port=int(os.environ.get("FALKORDB_PORT", "6379")),
        username=os.environ.get("FALKORDB_USERNAME") or None,
        password=os.environ.get("FALKORDB_PASSWORD") or None,
        decode_responses=True,
        protocol=2,
        socket_connect_timeout=5,
        socket_timeout=60,
    )
    deadline = time.monotonic() + 30
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if client.ping():
                return client
        except redis.RedisError as exc:
            last_error = exc
        time.sleep(1)
    client.close()
    raise RuntimeError(f"FalkorDB did not respond to PING. Last error: {last_error}")


def graph_query(client: redis.Redis, graph: str, query: str) -> dict[str, Any]:
    try:
        raw = client.execute_command("GRAPH.QUERY", graph, query)
    except redis.ResponseError as exc:
        raise RuntimeError(f"FalkorDB query failed: {exc}") from exc
    return _parse_result(raw)


def cypher_literal(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not (float("-inf") < value < float("inf")):
            raise ValueError("Cypher numeric values must be finite.")
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    raise TypeError(f"Cannot render {type(value).__name__} into Cypher.")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_identity_indexes_and_constraints(
    client: redis.Redis,
    graph: str,
    schema: dict[str, Any],
    config: dict[str, Any],
) -> None:
    identities = {
        (node["label"], node["id_property"])
        for node in schema["nodes"]
    }
    identities.update(
        (mapping["label"], mapping["id_property"])
        for mapping in config["vocabulary_mappings"]
    )
    identities.add(("BQ_KPIMeasure", "measure_id"))

    for label, prop in sorted(identities):
        query = f"CREATE INDEX FOR (n:{label}) ON (n.{prop})"
        try:
            graph_query(client, graph, query)
        except RuntimeError as exc:
            if not _already_exists(exc):
                raise
    _wait_for_status(client, graph, "db.indexes", len(identities))

    for label, prop in sorted(identities):
        try:
            client.execute_command(
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
        except redis.ResponseError as exc:
            if not _already_exists(exc):
                raise RuntimeError(f"Could not create {label}.{prop} uniqueness constraint: {exc}") from exc
    _wait_for_status(client, graph, "db.constraints", len(identities))


def upsert_schema(client: redis.Redis, graph: str, schema: dict[str, Any]) -> None:
    timestamp = utc_now()
    for index, node in enumerate(schema["nodes"]):
        graph_query(
            client,
            graph,
            render_node(f"n{index}", node, timestamp, update_on_match=True),
        )
    for index, edge in enumerate(schema["edges"]):
        graph_query(client, graph, render_edge(f"r{index}", f"a{index}", edge, f"b{index}"))


def render_node(
    alias: str,
    node: dict[str, Any],
    timestamp: str,
    *,
    update_on_match: bool = False,
) -> str:
    props = dict(node["properties"])
    props["created_at"] = timestamp
    props["updated_at"] = timestamp
    create = ", ".join(
        f"{alias}.{key} = {cypher_literal(value)}" for key, value in props.items()
    )
    lines = [
        f"MERGE ({alias}:{node['label']} {{{node['id_property']}: {cypher_literal(node['id'])}}})",
        f"ON CREATE SET {create}",
    ]
    if update_on_match:
        updates = dict(node["properties"])
        updates["updated_at"] = timestamp
        match = ", ".join(
            f"{alias}.{key} = {cypher_literal(value)}" for key, value in updates.items()
        )
        lines.append(f"ON MATCH SET {match}")
    else:
        lines.append(f"ON MATCH SET {alias}.updated_at = {cypher_literal(timestamp)}")
    return "\n".join(lines)


def render_edge(alias: str, source_alias: str, edge: dict[str, str], target_alias: str) -> str:
    source_prop = _id_property(edge["from_label"])
    target_prop = _id_property(edge["to_label"])
    return "\n".join(
        [
            f"MATCH ({source_alias}:{edge['from_label']} {{{source_prop}: {cypher_literal(edge['from_id'])}}})",
            f"MATCH ({target_alias}:{edge['to_label']} {{{target_prop}: {cypher_literal(edge['to_id'])}}})",
            f"MERGE ({source_alias})-[{alias}:{edge['type']}]->({target_alias})",
            f"ON CREATE SET {alias}.origin = {cypher_literal(edge['origin'])}",
        ]
    )


def _wait_for_status(
    client: redis.Redis,
    graph: str,
    procedure: str,
    expected_count: int,
    timeout_seconds: float = 30,
) -> None:
    query = f"CALL {procedure}() YIELD status RETURN status"
    deadline = time.monotonic() + timeout_seconds
    last_status: list[str] = []
    while time.monotonic() < deadline:
        result = graph_query(client, graph, query)
        last_status = [
            str(row[0])
            for row in result["rows"]
            if row and row[0] is not None
        ]
        if "FAILED" in last_status:
            raise RuntimeError(f"{procedure} reported FAILED: {last_status}")
        if len(last_status) >= expected_count and all(
            status == "OPERATIONAL" for status in last_status
        ):
            return
        time.sleep(0.4)
    raise RuntimeError(f"{procedure} did not become OPERATIONAL: {last_status}")


def _parse_result(raw: Any) -> dict[str, Any]:
    if isinstance(raw, (list, tuple)) and len(raw) == 3:
        columns = [str(column) for column in raw[0]] if isinstance(raw[0], list) else []
        body = raw[1] if isinstance(raw[1], list) else []
        rows = []
        for row in body:
            values = list(row) if isinstance(row, (list, tuple)) else [row]
            if columns:
                rows.append(values[: len(columns)])
        return {"columns": columns, "rows": rows}
    return {"columns": [], "rows": []}


def _id_property(label: str) -> str:
    try:
        return ID_PROPERTIES[label]
    except KeyError as exc:
        raise ValueError(f"No identity property configured for {label}.") from exc


def _already_exists(error: Exception) -> bool:
    text = str(error).lower()
    return any(
        marker in text
        for marker in (
            "already indexed",
            "already exists",
            "equivalent index",
            "index already",
            "constraint already",
            "an index already",
        )
    )
