"""Persist KPI records into the observation ontology.

JSON and CSV both become observation plans. The business key is the
observation id from ontology/identifiers.md. A repeated load writes a node
only when that key is new or its source hash changed.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from falkor_client import (
    execute_redis_command,
    graph_delete,
    graph_query,
    is_already_exists,
    rows_as_dicts,
    wait_for_status,
)
from normalize import (
    INDEXES,
    UNIQUE_CONSTRAINTS,
    apply_runtime_config,
    build_plans,
    exact_number,
    expected_graph,
)


EntityKey = Tuple[str, str]
ObservationState = Dict[str, Optional[str]]

PROVENANCE_FIELDS = (
    "provenance_platform",
    "source_table",
    "source_field_mapping",
    "data_version",
)

EXCLUDED_HASH_FIELDS = {
    "created_at",
    "updated_at",
    "loaded_at",
    "ingestion_timestamp",
    "valid_from",
    "valid_to",
    "content_hash",
}

# Observation edges whose target can change without changing the observation id.
REPLACEABLE_EDGES = {
    "BELONGS_TO_GROUP": "group",
    "HAS_LEVEL": "level",
    "HAS_UNIT": "unit",
    "HAS_RISK_PROFILE": "risk",
}

CATALOG_LABELS = {"BQ_Table", "BQ_column", "BQ_KPIMeasure", "LookMLKPIMeasure"}


def prepare_plans(records: Sequence[Dict[str, Any]], config: Dict[str, str]) -> Tuple[List[Dict[str, Any]], int]:
    built = build_plans(list(records))
    plans = _dedupe_plans(built)
    for plan in plans:
        apply_runtime_config(plan, config)
    return plans, len(built) - len(plans)


def plan_ingestion(
    plans: Sequence[Dict[str, Any]],
    existing_observations: Dict[str, ObservationState],
    dimension_hashes: Dict[EntityKey, str],
    timestamp: str,
) -> Dict[str, Any]:
    created: List[Dict[str, Any]] = []
    updated: List[Dict[str, Any]] = []
    unchanged: List[Dict[str, Any]] = []
    for plan in plans:
        action = _observation_action(plan, existing_observations.get(plan["observation_id"]))
        if action == "create":
            created.append(plan)
        elif action == "update":
            updated.append(plan)
        else:
            unchanged.append(plan)

    statements: List[str] = []
    entity_creates = 0
    entity_updates = 0
    for key, entity in _desired_entities(plans).items():
        desired_hash = content_hash(entity["properties"])
        current = dimension_hashes.get(key)
        if current == desired_hash:
            continue
        statements.append(_render_entity(entity, timestamp, desired_hash))
        if current is None:
            entity_creates += 1
        else:
            entity_updates += 1

    written_edges = set()
    for plan in created:
        statements.append(_render_observation(plan, timestamp))
        statements.extend(_render_edges(plan, "create", written_edges))
    for plan in updated:
        statements.append(_render_observation(plan, timestamp))
        statements.extend(_render_edges(plan, "update", written_edges))

    return {
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "entity_creates": entity_creates,
        "entity_updates": entity_updates,
        "statements": statements,
    }


def content_hash(properties: Dict[str, Any]) -> str:
    payload = {
        key: _hash_value(properties[key])
        for key in sorted(properties)
        if key not in EXCLUDED_HASH_FIELDS
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def observation_state(plan: Dict[str, Any]) -> ObservationState:
    properties = plan["observation_properties"]
    state: ObservationState = {"source_record_hash": plan["source_record_hash"]}
    for field in PROVENANCE_FIELDS:
        value = properties.get(field)
        state[field] = None if value is None else str(value)
    return state


def relationship_keys(plans: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    seen = set()
    for plan in plans:
        for edge in _iter_edges(plan):
            key = (edge["from_id"], edge["type"], edge["to_id"])
            if key in seen:
                continue
            seen.add(key)
            counts[edge["type"]] = counts.get(edge["type"], 0) + 1
    return counts


def ensure_fact_schema(client, graph: str) -> None:
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


def fetch_observation_states(client, graph: str) -> Dict[str, ObservationState]:
    result = graph_query(
        client,
        graph,
        """
        MATCH (o:KPIObservation)
        RETURN o.observation_id AS observation_id,
               o.source_record_hash AS source_record_hash,
               o.provenance_platform AS provenance_platform,
               o.source_table AS source_table,
               o.source_field_mapping AS source_field_mapping,
               o.data_version AS data_version
        """,
    )
    states: Dict[str, ObservationState] = {}
    for row in rows_as_dicts(result):
        observation_id = row.get("observation_id")
        if not observation_id:
            continue
        states[str(observation_id)] = {
            "source_record_hash": _text_or_none(row.get("source_record_hash")),
            "provenance_platform": _text_or_none(row.get("provenance_platform")),
            "source_table": _text_or_none(row.get("source_table")),
            "source_field_mapping": _text_or_none(row.get("source_field_mapping")),
            "data_version": _text_or_none(row.get("data_version")),
        }
    return states


def fetch_dimension_hashes(client, graph: str) -> Dict[EntityKey, str]:
    result = graph_query(
        client,
        graph,
        """
        MATCH (n)
        WHERE n.content_hash IS NOT NULL
          AND NOT n:KPIObservation
        RETURN labels(n)[0] AS label,
               coalesce(
                 n.source_id, n.market_id, n.metric_id, n.segment_id, n.channel_id,
                 n.product_id, n.group_id, n.level_id, n.unit_id, n.period_id,
                 n.corridor_id, n.risk_profile_id
               ) AS id,
               n.content_hash AS content_hash
        """,
    )
    found: Dict[EntityKey, str] = {}
    for row in rows_as_dicts(result):
        label = row.get("label")
        node_id = row.get("id")
        digest = row.get("content_hash")
        if label and node_id and digest:
            found[(str(label), str(node_id))] = str(digest)
    return found


def apply_statements(client, graph: str, statements: Sequence[str]) -> None:
    for statement in statements:
        graph_query(client, graph, statement)


def wipe_graph(client, graph: str) -> None:
    graph_delete(client, graph)


def compare_graph(client, graph: str, plans: Sequence[Dict[str, Any]]) -> List[str]:
    expected = expected_graph(list(plans))
    errors: List[str] = []
    actual_counts = _label_counts(client, graph)
    for label, count in expected["node_counts"].items():
        actual = actual_counts.get(label, 0)
        if actual != count:
            errors.append(f"{label}: graph has {actual}, input has {count}")
    unexpected = sorted(set(actual_counts) - set(expected["node_counts"]))
    if unexpected:
        catalog = [label for label in unexpected if label in CATALOG_LABELS]
        others = [label for label in unexpected if label not in CATALOG_LABELS]
        if catalog:
            errors.append(
                "query-time catalog labels are in this graph ("
                + ", ".join(catalog)
                + "). Wipe the graph before verifying a record-only load."
            )
        if others:
            errors.append("unexpected labels: " + ", ".join(others))

    actual_edges = _relationship_counts(client, graph)
    expected_edges = relationship_keys(plans)
    for rel_type, count in sorted(expected["relationship_counts"].items()):
        actual = actual_edges.get(rel_type, 0)
        planned = expected_edges.get(rel_type, 0)
        if planned != count:
            errors.append(f"{rel_type}: planner has {planned}, expected_graph has {count}")
        if actual != count:
            errors.append(f"{rel_type}: graph has {actual}, input has {count}")

    duplicate_ids = graph_query(
        client,
        graph,
        """
        MATCH (o:KPIObservation)
        WITH o.observation_id AS id, count(*) AS copies
        WHERE copies > 1
        RETURN id, copies
        ORDER BY id
        """,
    )
    duplicates = rows_as_dicts(duplicate_ids)
    if duplicates:
        errors.append(f"duplicate observation ids: {duplicates[:5]}")

    missing_hash = graph_query(
        client,
        graph,
        """
        MATCH (o:KPIObservation)
        WHERE o.source_record_hash IS NULL
        RETURN count(o) AS missing
        """,
    )
    missing_rows = rows_as_dicts(missing_hash)
    if missing_rows and int(missing_rows[0]["missing"]) != 0:
        errors.append(f"observations missing source_record_hash: {missing_rows[0]['missing']}")
    return errors


def _dedupe_plans(plans: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    last_index: Dict[str, int] = {}
    for index, plan in enumerate(plans):
        last_index[plan["observation_id"]] = index
    return [plan for index, plan in enumerate(plans) if last_index[plan["observation_id"]] == index]


def _observation_action(plan: Dict[str, Any], existing: Optional[ObservationState]) -> str:
    if existing is None:
        return "create"
    desired = observation_state(plan)
    if all(existing.get(field) == desired[field] for field in desired):
        return "unchanged"
    return "update"


def _desired_entities(plans: Iterable[Dict[str, Any]]) -> Dict[EntityKey, Dict[str, Any]]:
    found: Dict[EntityKey, Dict[str, Any]] = {}
    for plan in plans:
        for entity in plan["entities"].values():
            if entity is None:
                continue
            found[(entity["label"], entity["id"])] = entity
    return found


def _render_entity(entity: Dict[str, Any], timestamp: str, digest: str) -> str:
    create_props = dict(entity["properties"])
    create_props["content_hash"] = digest
    create_props["created_at"] = timestamp
    create_props["updated_at"] = timestamp
    match_props = dict(entity["properties"])
    match_props["content_hash"] = digest
    match_props["updated_at"] = timestamp
    return _render_merge(entity["label"], entity["id_property"], entity["id"], create_props, match_props)


def _render_observation(plan: Dict[str, Any], timestamp: str) -> str:
    business = dict(plan["observation_properties"])
    create_props = dict(business)
    create_props["created_at"] = timestamp
    create_props["updated_at"] = timestamp
    create_props["valid_from"] = timestamp
    create_props["ingestion_timestamp"] = timestamp
    create_props["loaded_at"] = timestamp
    match_props = dict(business)
    match_props["updated_at"] = timestamp
    match_props["ingestion_timestamp"] = timestamp
    match_props["loaded_at"] = timestamp
    return _render_merge("KPIObservation", "observation_id", plan["observation_id"], create_props, match_props)


def _render_edges(plan: Dict[str, Any], action: str, written: set) -> List[str]:
    statements: List[str] = []
    edges = list(_iter_edges(plan))
    if action == "update":
        statements.extend(_retarget_edges(plan, edges))
    for edge in edges:
        key = (edge["from_id"], edge["type"], edge["to_id"])
        if key in written:
            continue
        written.add(key)
        statements.append(
            "\n".join(
                [
                    f"MATCH (a:{edge['from_label']} {{{edge['from_property']}: {cypher_literal(edge['from_id'])}}})",
                    f"MATCH (b:{edge['to_label']} {{{edge['to_property']}: {cypher_literal(edge['to_id'])}}})",
                    f"MERGE (a)-[r:{edge['type']}]->(b)",
                    f"ON CREATE SET r.origin = {cypher_literal(edge['origin'])}",
                ]
            )
        )
    return statements


def _retarget_edges(plan: Dict[str, Any], edges: Sequence[Dict[str, Any]]) -> List[str]:
    statements = []
    observation_id = cypher_literal(plan["observation_id"])
    by_type = {edge["type"]: edge for edge in edges if edge["from_label"] == "KPIObservation"}
    for rel_type, entity_key in REPLACEABLE_EDGES.items():
        edge = by_type.get(rel_type)
        if edge is None:
            statements.append(
                f"MATCH (o:KPIObservation {{observation_id: {observation_id}}})-[r:{rel_type}]->() DELETE r"
            )
            continue
        statements.append(
            "\n".join(
                [
                    f"MATCH (o:KPIObservation {{observation_id: {observation_id}}})-[r:{rel_type}]->(n)",
                    f"WHERE n.{edge['to_property']} <> {cypher_literal(edge['to_id'])}",
                    "DELETE r",
                ]
            )
        )
    if plan["entities"].get("risk") is None:
        risk_id = "RISK:" + plan["observation_id"].removeprefix("OBS:")
        statements.append(
            f"MATCH (n:RiskProfile {{risk_profile_id: {cypher_literal(risk_id)}}}) DETACH DELETE n"
        )
    return statements


def _iter_edges(plan: Dict[str, Any]) -> Iterable[Dict[str, str]]:
    entities = plan["entities"]
    observation = {
        "label": "KPIObservation",
        "id_property": "observation_id",
        "id": plan["observation_id"],
    }
    fact_edges = [
        ("MEASURES", "metric", "SOURCE_FACT"),
        ("FOR_MARKET", "market", "SOURCE_FACT"),
        ("FOR_SEGMENT", "segment", "SOURCE_FACT"),
        ("THROUGH_CHANNEL", "channel", "SOURCE_FACT"),
        ("FOR_PRODUCT", "product", "SOURCE_FACT"),
        ("FOR_CORRIDOR", "corridor", "SOURCE_FACT"),
        ("FROM_SOURCE", "source", "SOURCE_FACT"),
        ("FOR_PERIOD", "period", "SOURCE_FACT"),
        ("BELONGS_TO_GROUP", "group", "SOURCE_FACT"),
        ("HAS_LEVEL", "level", "SOURCE_FACT"),
        ("HAS_UNIT", "unit", "SOURCE_FACT"),
        ("HAS_RISK_PROFILE", "risk", "SOURCE_FACT"),
    ]
    for rel_type, key, origin in fact_edges:
        yield from _edge(observation, rel_type, entities.get(key), origin)
    metric = entities.get("metric")
    projections = [
        ("DEFINED_BY_SOURCE", "source", "SOURCE_PROJECTION"),
        ("HAS_LEVEL", "level", "SOURCE_PROJECTION"),
        ("USES_UNIT", "unit", "SOURCE_PROJECTION"),
        ("GROUPED_UNDER", "group", "SOURCE_PROJECTION"),
        ("OBSERVED_IN", "market", "DERIVED"),
    ]
    for rel_type, key, origin in projections:
        yield from _edge(metric, rel_type, entities.get(key), origin)
    yield from _edge(metric, "HAS_OBSERVATION", observation, "DERIVED")


def _edge(source: Optional[Dict[str, Any]], rel_type: str, target: Optional[Dict[str, Any]], origin: str) -> Iterable[Dict[str, str]]:
    if source is None or target is None:
        return
    yield {
        "type": rel_type,
        "origin": origin,
        "from_label": source["label"],
        "from_property": source["id_property"],
        "from_id": source["id"],
        "to_label": target["label"],
        "to_property": target["id_property"],
        "to_id": target["id"],
    }


def _render_merge(
    label: str,
    id_property: str,
    node_id: str,
    create_props: Dict[str, Any],
    match_props: Dict[str, Any],
) -> str:
    return "\n".join(
        [
            f"MERGE (n:{label} {{{id_property}: {cypher_literal(node_id)}}})",
            f"ON CREATE SET {_assignment_list('n', create_props)}",
            f"ON MATCH SET {_assignment_list('n', match_props)}",
        ]
    )


def _assignment_list(alias: str, properties: Dict[str, Any]) -> str:
    return ", ".join(f"{alias}.{key} = {cypher_literal(properties[key])}" for key in properties)


def cypher_literal(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, Decimal):
        rendered = exact_number(value)
        if rendered is None:
            return "null"
        if "." not in rendered:
            return rendered
        return rendered
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return "'" + escaped + "'"
    raise TypeError(f"Cannot render {type(value).__name__} into Cypher.")


def _hash_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return exact_number(value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"Cannot hash {type(value).__name__}.")


def _text_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _label_counts(client, graph: str) -> Dict[str, int]:
    result = graph_query(
        client,
        graph,
        "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS nodes ORDER BY label",
    )
    counts = {}
    for row in rows_as_dicts(result):
        counts[str(row["label"])] = int(row["nodes"])
    return counts


def _relationship_counts(client, graph: str) -> Dict[str, int]:
    result = graph_query(
        client,
        graph,
        "MATCH ()-[r]->() RETURN type(r) AS relationship, count(*) AS edges",
    )
    counts = {}
    for row in rows_as_dicts(result):
        counts[str(row["relationship"])] = int(row["edges"])
    return counts
