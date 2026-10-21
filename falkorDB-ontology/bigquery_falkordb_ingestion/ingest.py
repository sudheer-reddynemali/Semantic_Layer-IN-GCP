"""Canonical batch processing and idempotent source-row upserts."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .graph import cypher_literal, graph_query, utc_now
from .kpi_measures import CANONICAL_FIELDS


def selected_source_columns(config: dict[str, Any]) -> list[str]:
    return list(
        dict.fromkeys(mapping["bigquery_column"] for mapping in config["vocabulary_mappings"])
    )


def canonicalize_row(raw: Mapping[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        str(source).upper(): target
        for source, target in config["canonical_field_mappings"].items()
    }
    canonical: dict[str, Any] = {}
    for source, value in raw.items():
        field = aliases.get(str(source).upper()) or _canonical_field(str(source))
        if field is None:
            raise ValueError(f"BigQuery returned an unmapped selected column: {source}.")
        if field in canonical:
            raise ValueError(f"Multiple BigQuery columns map to canonical field {field}.")
        if isinstance(value, str):
            value = value.strip()
            if not value or value.upper() == "NA":
                value = None
        canonical[field] = value
    for field in config.get("required_fields", []):
        if canonical.get(field) is None:
            raise ValueError(f"Required canonical field {field} is null or missing.")
    return canonical


def process_batches(
    rows: Iterable[Mapping[str, Any]],
    *,
    client: Any,
    graph: str,
    schema: dict[str, Any],
    config: dict[str, Any],
    batch_size: int,
    retry_limit: int,
    retry_base_seconds: float,
    failed_file: Path,
    source_table: str = "",
    progress_callback: Callable[[dict[str, int]], None] | None = None,
) -> dict[str, int]:
    if batch_size < 1:
        raise ValueError("batch_size must be greater than zero.")
    if retry_limit < 0:
        raise ValueError("retry_limit cannot be negative.")
    if retry_base_seconds < 0:
        raise ValueError("retry_base_seconds cannot be negative.")

    totals = {"batches": 0, "rows": 0, "succeeded": 0, "failed": 0}
    for batch in _batches(rows, batch_size):
        totals["batches"] += 1
        for raw in batch:
            totals["rows"] += 1
            row_number = totals["rows"]
            canonical: dict[str, Any] | None = None
            last_error: Exception | None = None
            for attempt in range(1, retry_limit + 2):
                try:
                    canonical = canonicalize_row(raw, config)
                    upsert_record(client, graph, schema, config, canonical)
                    totals["succeeded"] += 1
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt <= retry_limit:
                        time.sleep(retry_base_seconds * (2 ** (attempt - 1)))
            if last_error is not None:
                _append_failure(
                    failed_file,
                    {
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                        "source_table": source_table,
                        "row_number": row_number,
                        "attempts": retry_limit + 1,
                        "source_record": dict(raw),
                        "canonical_record": canonical,
                        "error": f"{type(last_error).__name__}: {last_error}",
                    },
                )
                totals["failed"] += 1
            if progress_callback is not None:
                progress_callback(dict(totals))
    return totals


def upsert_record(
    client: Any,
    graph: str,
    schema: dict[str, Any],
    config: dict[str, Any],
    record: dict[str, Any],
) -> None:
    queries: list[str] = []
    timestamp = utc_now()
    column_lookup = schema["columns"]

    for index, mapping in enumerate(config["vocabulary_mappings"]):
        value = record.get(mapping["canonical_field"])
        if value is None:
            continue
        if not isinstance(value, str):
            raise TypeError(
                f"Vocabulary field {mapping['canonical_field']} must be text, received {type(value).__name__}."
            )
        node = _vocabulary_node(mapping, value, config)
        alias = f"v{index}"
        queries.append(_render_merge_node(alias, node, timestamp))
        column = mapping["falkordb_column"]
        _append_relationship(
            queries,
            alias,
            column_lookup[column],
            "DESCRIBES_COLUMN",
            "VOCABULARY",
            f"vocab_edge_{index}",
        )

    metric = record.get("metric")
    if isinstance(metric, str) and metric:
        table = next(node for node in schema["nodes"] if node["label"] == "BQ_Table")
        for index, definition in enumerate(config["kpi_definitions"]):
            measure = _measure_node(definition, metric, record)
            alias = f"m{index}"
            queries.append(_render_merge_node(alias, measure, timestamp, update_on_match=True))
            _append_relationship(
                queries,
                alias,
                table,
                "ON_TABLE",
                "BIGQUERY",
                f"measure_table_{index}",
            )
            value_column = definition["falkordb_column"]
            _append_relationship(
                queries,
                alias,
                column_lookup[value_column],
                "USES_COLUMN",
                "BIGQUERY",
                f"measure_value_{index}",
            )
            for filter_index, column in enumerate(measure["filter_columns"]):
                _append_relationship(
                    queries,
                    alias,
                    column_lookup[column],
                    "USES_COLUMN",
                    "BIGQUERY",
                    f"measure_filter_{index}_{filter_index}",
                )
    if queries:
        graph_query(client, graph, "\nWITH *\n".join(queries))


def replay_failures(
    failure_file: Path,
    *,
    client: Any,
    graph: str,
    schema: dict[str, Any],
    config: dict[str, Any],
    retry_limit: int,
    retry_base_seconds: float,
) -> dict[str, int]:
    if not failure_file.exists():
        raise FileNotFoundError(f"No failed-record file exists at {failure_file}.")
    entries = [
        json.loads(line)
        for line in failure_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    remaining: list[dict[str, Any]] = []
    succeeded = 0
    for entry in entries:
        raw = entry.get("canonical_record") or entry.get("source_record")
        if not isinstance(raw, dict):
            raise ValueError("Failed-record entry has no replayable source_record.")
        error: Exception | None = None
        for attempt in range(1, retry_limit + 2):
            try:
                canonical = canonicalize_row(raw, config)
                upsert_record(client, graph, schema, config, canonical)
                succeeded += 1
                error = None
                break
            except Exception as exc:
                error = exc
                if attempt <= retry_limit:
                    time.sleep(retry_base_seconds * (2 ** (attempt - 1)))
        if error is not None:
            entry["error"] = f"{type(error).__name__}: {error}"
            entry["attempts"] = retry_limit + 1
            entry["last_replayed_at"] = datetime.now(timezone.utc).isoformat()
            remaining.append(entry)
    _replace_failures(failure_file, remaining)
    return {"replayed": len(entries), "succeeded": succeeded, "failed": len(remaining)}


def _vocabulary_node(
    mapping: dict[str, str],
    value: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    label = mapping["label"]
    if label == "Unit":
        unit = config.get("unit_values", {}).get(value)
        if unit:
            graph_id = unit["id"]
            properties = {
                **{key: item for key, item in unit.items() if key != "id"},
                "unit_id": graph_id,
                "status": "ACTIVE",
            }
        else:
            token = _normalize_token(value)
            graph_id = f"UNIT:SOURCE_{token}"
            properties = {
                "unit_id": graph_id,
                "code": f"SOURCE_{token}",
                "name": value,
                "source_symbol": value,
                "status": "ACTIVE",
            }
        return {
            "label": label,
            "id_property": mapping["id_property"],
            "id": graph_id,
            "properties": properties,
        }

    token = _normalize_token(value)
    graph_id = f"{mapping['id_prefix']}:{token}"
    properties: dict[str, Any] = {
        mapping["id_property"]: graph_id,
        "name": value,
        "normalized_name": token,
        "status": "ACTIVE",
    }
    if label == "Market":
        properties["market_type"] = "UNCLASSIFIED"
    elif label == "MetricGroup":
        properties["source_field"] = "GROUP_ALL"
    elif label == "MetricLevel":
        properties["code"] = value
        match = re.fullmatch(r"L(\d+)", token)
        properties["rank"] = int(match.group(1)) if match else None
    return {
        "label": label,
        "id_property": mapping["id_property"],
        "id": graph_id,
        "properties": properties,
    }


def _measure_node(
    definition: dict[str, Any],
    metric: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    metric_token = _normalize_token(metric).lower()
    kpi_token = _normalize_token(definition["key"]).lower()
    measure_id = definition["measure_id_template"].format(
        metric=metric_token,
        kpi=kpi_token,
    )
    name = definition["name_template"].format(metric=metric, kpi=definition["key"])
    filters: dict[str, str] = {}
    filter_columns: list[str] = []
    for column, canonical_field in definition.get("filters", {}).items():
        value = record.get(canonical_field)
        if value is None:
            continue
        if not isinstance(value, str):
            raise TypeError(f"KPI filter {column} must be text.")
        filters[column] = value
        filter_columns.append(column)
    return {
        "label": "BQ_KPIMeasure",
        "id_property": "measure_id",
        "id": measure_id,
        "properties": {
            "measure_id": measure_id,
            "name": name,
            "value_column": definition["falkordb_column"],
            "aggregation": definition["aggregation"],
            "filters": json.dumps(filters, separators=(",", ":"), ensure_ascii=False),
            "status": "ACTIVE",
        },
        "filter_columns": filter_columns,
    }


def _render_merge_node(
    alias: str,
    node: dict[str, Any],
    timestamp: str,
    *,
    update_on_match: bool = False,
) -> str:
    properties = dict(node["properties"])
    properties["created_at"] = timestamp
    properties["updated_at"] = timestamp
    create_assignments = ", ".join(
        f"{alias}.{key} = {cypher_literal(value)}"
        for key, value in properties.items()
    )
    lines = [
        f"MERGE ({alias}:{node['label']} {{{node['id_property']}: {cypher_literal(node['id'])}}})",
        f"ON CREATE SET {create_assignments}",
    ]
    if update_on_match:
        updates = dict(node["properties"])
        updates["updated_at"] = timestamp
        lines.append(
            "ON MATCH SET "
            + ", ".join(
                f"{alias}.{key} = {cypher_literal(value)}"
                for key, value in updates.items()
            )
        )
    else:
        lines.append(f"ON MATCH SET {alias}.updated_at = {cypher_literal(timestamp)}")
    return "\n".join(lines)


def _append_relationship(
    queries: list[str],
    source_alias: str,
    target: dict[str, Any],
    relationship: str,
    origin: str,
    alias: str,
) -> None:
    target_label = target["label"]
    target_prop = target["id_property"]
    queries.append(
        "\n".join(
            [
                f"MATCH ({source_alias})",
                f"MATCH (target_{alias}:{target_label} {{{target_prop}: {cypher_literal(target['id'])}}})",
                f"MERGE ({source_alias})-[edge_{alias}:{relationship}]->(target_{alias})",
                f"ON CREATE SET edge_{alias}.origin = {cypher_literal(origin)}",
            ]
        )
    )


def _append_failure(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def _replace_failures(path: Path, remaining: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for entry in remaining:
            handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    temporary.replace(path)


def _batches(
    rows: Iterable[Mapping[str, Any]],
    batch_size: int,
) -> Iterator[list[Mapping[str, Any]]]:
    batch: list[Mapping[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) == batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def _canonical_field(source: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", "_", source.strip().lower()).strip("_")
    return normalized if normalized in CANONICAL_FIELDS else None


def _normalize_token(value: str) -> str:
    token = re.sub(r"[^A-Z0-9]+", "_", value.strip().upper())
    token = re.sub(r"_+", "_", token).strip("_")
    if not token:
        raise ValueError(f"Cannot build an identifier token from {value!r}.")
    return token
