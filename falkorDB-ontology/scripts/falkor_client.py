"""Minimal FalkorDB client over the Redis protocol.

RESP2 is pinned because graph replies are arrays of columns, rows, and
statistics. Authentication is optional and is read from the environment.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence

import redis


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def connection_settings() -> Dict[str, Any]:
    return {
        "host": os.environ.get("FALKORDB_HOST", "localhost"),
        "port": int(os.environ.get("FALKORDB_PORT", "6379")),
        "username": os.environ.get("FALKORDB_USERNAME") or None,
        "password": os.environ.get("FALKORDB_PASSWORD") or None,
        "graph": os.environ.get("FALKORDB_GRAPH", "enterprise_kpi"),
        "source_table": os.environ.get("SOURCE_TABLE", "KPI_MONTHLY_SNAPSHOT"),
        "provenance_platform": os.environ.get("PROVENANCE_PLATFORM", "BIGQUERY"),
        "data_version": os.environ.get("DATA_VERSION", "1.0.0"),
        "source_field_mapping": os.environ.get(
            "SOURCE_FIELD_MAPPING", "MAP:KPI_MONTHLY_SNAPSHOT:1.0.0"
        ),
    }


def connect(
    host: str,
    port: int,
    username: str | None = None,
    password: str | None = None,
) -> redis.Redis:
    client = redis.Redis(
        host=host,
        port=port,
        username=username,
        password=password,
        decode_responses=True,
        protocol=2,
        socket_connect_timeout=5,
        socket_timeout=60,
    )
    return client


def wait_until_ready(client: redis.Redis, attempts: int = 30, delay_seconds: float = 1.0) -> None:
    last_error = None
    for _ in range(attempts):
        try:
            if client.ping():
                return
        except redis.RedisError as exc:
            last_error = exc
        time.sleep(delay_seconds)
    raise RuntimeError(f"FalkorDB did not respond to PING. Last error: {last_error}")


def graph_query(client: redis.Redis, graph: str, query: str) -> Dict[str, Any]:
    try:
        raw = client.execute_command("GRAPH.QUERY", graph, query)
    except redis.ResponseError as exc:
        raise RuntimeError(f"FalkorDB query failed: {exc}\n---\n{query}") from exc
    return parse_result(raw)


def graph_delete(client: redis.Redis, graph: str) -> None:
    try:
        client.execute_command("GRAPH.DELETE", graph)
    except redis.ResponseError as exc:
        message = str(exc).lower()
        if "invalid graph" in message or "empty key" in message or "does not exist" in message:
            return
        raise


def parse_result(raw: Any) -> Dict[str, Any]:
    """Accept the GRAPH.QUERY array shape and a bare statistics list."""
    if raw is None:
        return {"columns": [], "rows": [], "stats": []}
    if isinstance(raw, (str, int, float)):
        return {"columns": [], "rows": [], "stats": [str(raw)]}
    if not isinstance(raw, (list, tuple)):
        return {"columns": [], "rows": [], "stats": [str(raw)]}

    stats: List[str] = []
    columns: List[str] = []
    rows: List[List[Any]] = []

    if len(raw) == 3 and isinstance(raw[0], list) and isinstance(raw[2], list):
        columns = [str(column) for column in raw[0]]
        body = raw[1] if isinstance(raw[1], list) else []
        stats = [str(item) for item in raw[2]]
        if columns:
            rows = [_normalize_row(row, len(columns)) for row in body]
        elif body and all(isinstance(item, str) for item in body):
            stats = [str(item) for item in body] + stats
        return {"columns": columns, "rows": rows, "stats": stats}

    if raw and all(isinstance(item, str) for item in raw):
        return {"columns": [], "rows": [], "stats": [str(item) for item in raw]}

    return {"columns": [], "rows": [], "stats": [str(raw)]}


def _normalize_row(row: Any, width: int) -> List[Any]:
    if isinstance(row, list):
        values = list(row)
    else:
        values = [row]
    if len(values) < width:
        values.extend([None] * (width - len(values)))
    return values[:width]


def rows_as_dicts(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    columns = result["columns"]
    return [dict(zip(columns, row)) for row in result["rows"]]


def is_already_exists(error: Exception) -> bool:
    message = str(error).lower()
    markers = (
        "already indexed",
        "already exists",
        "equivalent index",
        "index already",
        "constraint already",
        "an index already",
    )
    return any(marker in message for marker in markers)


def execute_redis_command(client: redis.Redis, *parts: str) -> Any:
    try:
        return client.execute_command(*parts)
    except redis.ResponseError as exc:
        if is_already_exists(exc):
            return f"EXISTS {exc}"
        raise RuntimeError(f"Redis command failed: {exc}\nCommand: {' '.join(parts)}") from exc


def wait_for_status(
    client: redis.Redis,
    graph: str,
    procedure: str,
    timeout_seconds: float = 30.0,
    expected_count: int = 1,
) -> List[Dict[str, Any]]:
    deadline = time.time() + timeout_seconds
    last_rows: List[Dict[str, Any]] = []
    query = f"CALL {procedure}() YIELD status RETURN status"
    while time.time() < deadline:
        result = graph_query(client, graph, query)
        last_rows = rows_as_dicts(result)
        statuses = [str(row.get("status")) for row in last_rows]
        if any(status == "FAILED" for status in statuses):
            raise RuntimeError(f"{procedure} reported FAILED: {last_rows}")
        if len(statuses) >= expected_count and all(status == "OPERATIONAL" for status in statuses):
            return last_rows
        time.sleep(0.4)
    raise RuntimeError(f"{procedure} did not become OPERATIONAL: {last_rows}")
