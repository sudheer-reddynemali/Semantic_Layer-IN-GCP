"""Canonical field names, deterministic identifiers, and observation plans.

Display values stay as supplied. Normalization is used only to build stable ids.
Null dimensions are omitted as entities. The token UNSPECIFIED appears only
inside the observation key so a null slot cannot collide with a real value.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


CANONICAL_FIELDS = [
    "source",
    "market",
    "metric",
    "metric_type",
    "segment",
    "group_all",
    "meet_target",
    "channel",
    "unit_type",
    "vs_ye_target",
    "sq_appetite",
    "sq_tolerance",
    "sq_breach_code",
    "product_type",
    "corridor",
    "year",
    "reporting_month",
    "mtd_actual",
    "mtd_plan",
    "ytd_actual",
    "ytd_plan",
    "py_mtd_actual",
    "py_ytd_actual",
    "fy_forecast",
    "fy_plan",
    "mom",
    "pm_actual",
    "vs_plan",
    "vs_py",
]

MEASURE_FIELDS = [
    "mtd_actual",
    "mtd_plan",
    "ytd_actual",
    "ytd_plan",
    "py_mtd_actual",
    "py_ytd_actual",
    "fy_forecast",
    "fy_plan",
    "mom",
    "pm_actual",
    "vs_plan",
    "vs_py",
    "vs_ye_target",
    "meet_target",
]

# Fixed position of each slot in the observation id, after the OBS: prefix.
IDENTITY_SLOTS = [
    "source",
    "market",
    "metric",
    "segment",
    "channel",
    "product",
    "corridor",
    "year",
    "reporting_month",
]

NULL_DIMENSION_TOKEN = "UNSPECIFIED"
ID_SCHEME = "OBS_V1"

# Semantic reading of the three unit symbols present in the extract.
# "$" is a currency symbol only. No ISO currency code is assigned.
UNIT_CATALOG = {
    "#": {
        "unit_id": "UNIT:COUNT",
        "code": "COUNT",
        "name": "Count",
        "source_symbol": "#",
    },
    "%": {
        "unit_id": "UNIT:PERCENT",
        "code": "PERCENT",
        "name": "Percent",
        "source_symbol": "%",
    },
    "$": {
        "unit_id": "UNIT:CURRENCY",
        "code": "CURRENCY",
        "name": "Currency",
        "source_symbol": "$",
        "currency_inferred": False,
    },
}

ENTITY_STATUS = "ACTIVE"
MARKET_TYPE = "UNCLASSIFIED"
RISK_STATUS = "REPORTED"
GROUP_SOURCE_FIELD = "GROUP_ALL"

INDEXES = [
    ("Source", "source_id", "Identity lookup. Required by the UNIQUE constraint."),
    ("Source", "name", "Find a business domain by the source code, for example CCO_CLCM."),
    ("Market", "market_id", "Identity lookup. Required by the UNIQUE constraint."),
    ("Market", "name", "Find a market by the reported name, including TOP 9 MARKETS."),
    ("Segment", "segment_id", "Identity lookup. Required by the UNIQUE constraint."),
    ("Segment", "name", "Find observations for a customer segment."),
    ("Channel", "channel_id", "Identity lookup. Required by the UNIQUE constraint."),
    ("Channel", "name", "Find observations for Digital, Mobile, or Branch."),
    ("Product", "product_id", "Identity lookup. Required by the UNIQUE constraint."),
    ("Product", "name", "Find observations for a reported product type."),
    ("Metric", "metric_id", "Identity lookup. Required by the UNIQUE constraint."),
    ("Metric", "name", "Exact KPI lookup by the business metric name."),
    ("MetricGroup", "group_id", "Identity lookup. Required by the UNIQUE constraint."),
    ("MetricGroup", "name", "Find metrics reported under a GROUP_ALL value."),
    ("MetricLevel", "level_id", "Identity lookup. Required by the UNIQUE constraint."),
    ("Unit", "unit_id", "Identity lookup. Required by the UNIQUE constraint."),
    ("ReportingPeriod", "period_id", "Find a reporting month, for example PERIOD:2025-08."),
    ("KPIObservation", "observation_id", "Identity lookup. Required by the UNIQUE constraint."),
    ("KPIObservation", "source_record_hash", "Provenance lookup of a source-row fingerprint."),
    ("RiskProfile", "risk_profile_id", "Identity lookup. Required by the UNIQUE constraint."),
    ("Corridor", "corridor_id", "Identity lookup for the source corridor dimension when it is populated."),
]

UNIQUE_CONSTRAINTS = [
    ("Source", "source_id"),
    ("Market", "market_id"),
    ("Segment", "segment_id"),
    ("Channel", "channel_id"),
    ("Product", "product_id"),
    ("Metric", "metric_id"),
    ("MetricGroup", "group_id"),
    ("MetricLevel", "level_id"),
    ("Unit", "unit_id"),
    ("ReportingPeriod", "period_id"),
    ("KPIObservation", "observation_id"),
    ("RiskProfile", "risk_profile_id"),
    ("Corridor", "corridor_id"),
]


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def collapse_field_name(raw: str) -> str:
    text = raw.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


_CANONICAL_LOOKUP = {collapse_field_name(name): name for name in CANONICAL_FIELDS}


def canonicalize_field_name(raw: str) -> Optional[str]:
    return _CANONICAL_LOOKUP.get(collapse_field_name(raw))


def clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return None if stripped == "" else stripped
    if isinstance(value, bool):
        raise TypeError("Boolean source values are not part of this extract.")
    if isinstance(value, float):
        raise TypeError("Parse fractional source values as Decimal so the literal is preserved.")
    if isinstance(value, (int, Decimal)):
        return value
    raise TypeError(f"Unsupported source value type: {type(value).__name__}")


def canonicalize_record(raw: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    canonical = {field: None for field in CANONICAL_FIELDS}
    unknown: Dict[str, Any] = {}
    for key, value in raw.items():
        name = canonicalize_field_name(str(key))
        if name is None:
            unknown[str(key)] = value
            continue
        canonical[name] = clean_value(value)
    return canonical, unknown


def normalize_token(value: str) -> str:
    text = value.strip().upper()
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        raise ValueError(f"Cannot build an identifier token from {value!r}.")
    return text


def exact_number(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("Boolean values are not numeric measures.")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"Cannot canonicalize number of type {type(value).__name__}.")


def as_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return int(value)
    raise ValueError(f"{field} must be an integer.")


def canonical_payload(record: Dict[str, Any]) -> str:
    payload = {}
    for field in CANONICAL_FIELDS:
        value = record.get(field)
        if value is None or isinstance(value, str):
            payload[field] = value
        else:
            payload[field] = exact_number(value)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def source_record_hash(record: Dict[str, Any]) -> str:
    return hashlib.sha256(canonical_payload(record).encode("utf-8")).hexdigest()


def dimension_token(value: Optional[str]) -> str:
    if value is None:
        return NULL_DIMENSION_TOKEN
    return normalize_token(value)


def parse_period(year_value: Any, reporting_month_value: Any) -> Dict[str, Any]:
    year = as_int(year_value, "year")
    reporting_month = as_int(reporting_month_value, "reporting_month")
    text = str(reporting_month)
    reasons = []
    if len(text) != 6 or not text.isdigit():
        raise ValueError(f"reporting_month must be YYYYMM, received {reporting_month_value!r}.")
    month = int(text[4:6])
    prefix_year = int(text[0:4])
    if month < 1 or month > 12:
        raise ValueError(f"reporting_month has an invalid month: {reporting_month}.")
    if prefix_year != year:
        reasons.append(
            f"YEAR {year} does not match the year prefix of REPORTING_MONTH {reporting_month}."
        )
    return {
        "year": year,
        "month": month,
        "source_year": year,
        "source_reporting_month": reporting_month,
        "period_id": f"PERIOD:{year:04d}-{month:02d}",
        "name": f"{year:04d}-{month:02d}",
        "period_type": "MONTH",
        "quality_reasons": reasons,
    }


def named_entity(label: str, id_property: str, prefix: str, name: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    token = normalize_token(name)
    properties = {
        "name": name,
        "normalized_name": token,
        "status": ENTITY_STATUS,
    }
    if extra:
        properties.update(extra)
    return {
        "label": label,
        "id_property": id_property,
        "id": f"{prefix}:{token}",
        "properties": properties,
    }


def unit_entity(symbol: str) -> Tuple[Dict[str, Any], List[str]]:
    reasons: List[str] = []
    if symbol in UNIT_CATALOG:
        spec = dict(UNIT_CATALOG[symbol])
    else:
        token = normalize_token(symbol)
        spec = {
            "unit_id": f"UNIT:SOURCE_{token}",
            "code": f"SOURCE_{token}",
            "name": symbol,
            "source_symbol": symbol,
        }
        reasons.append(f"UNIT_TYPE {symbol!r} has no semantic unit mapping.")
    unit_id = spec.pop("unit_id")
    properties = dict(spec)
    properties["status"] = ENTITY_STATUS
    return (
        {
            "label": "Unit",
            "id_property": "unit_id",
            "id": unit_id,
            "properties": properties,
        },
        reasons,
    )


def level_entity(metric_type: str) -> Dict[str, Any]:
    code = metric_type.strip()
    token = normalize_token(code)
    match = re.fullmatch(r"L(\d+)", token)
    rank = int(match.group(1)) if match else None
    return {
        "label": "MetricLevel",
        "id_property": "level_id",
        "id": f"LEVEL:{token}",
        "properties": {
            "code": code,
            "name": code,
            "rank": rank,
            "status": ENTITY_STATUS,
        },
    }


def status_for(value: Any) -> str:
    return "SPECIFIED" if value is not None else "UNSPECIFIED"


def build_plan(record: Dict[str, Any], unknown: Optional[Dict[str, Any]] = None, row_number: Optional[int] = None) -> Dict[str, Any]:
    unknown = unknown or {}
    reasons: List[str] = []
    prefix = f"row {row_number}: " if row_number is not None else ""

    for field in ("source", "market", "metric", "year", "reporting_month"):
        if record.get(field) is None:
            raise ValueError(f"{prefix}{field} is required to build an observation.")

    period = parse_period(record["year"], record["reporting_month"])
    reasons.extend(period.pop("quality_reasons"))

    source = named_entity("Source", "source_id", "SOURCE", record["source"])
    market = named_entity(
        "Market",
        "market_id",
        "MARKET",
        record["market"],
        {"market_type": MARKET_TYPE},
    )
    metric = named_entity(
        "Metric",
        "metric_id",
        "METRIC",
        record["metric"],
        {
            "metric_type": record.get("metric_type"),
            "unit_type": record.get("unit_type"),
        },
    )

    segment = named_entity("Segment", "segment_id", "SEGMENT", record["segment"]) if record.get("segment") else None
    channel = named_entity("Channel", "channel_id", "CHANNEL", record["channel"]) if record.get("channel") else None
    product = named_entity("Product", "product_id", "PRODUCT", record["product_type"]) if record.get("product_type") else None
    group = (
        named_entity(
            "MetricGroup",
            "group_id",
            "GROUP",
            record["group_all"],
            {"source_field": GROUP_SOURCE_FIELD},
        )
        if record.get("group_all")
        else None
    )
    corridor = named_entity("Corridor", "corridor_id", "CORRIDOR", record["corridor"]) if record.get("corridor") else None
    level = level_entity(record["metric_type"]) if record.get("metric_type") else None
    unit = None
    if record.get("unit_type"):
        unit, unit_reasons = unit_entity(record["unit_type"])
        reasons.extend(unit_reasons)
    else:
        reasons.append("UNIT_TYPE is null.")

    if record.get("metric_type") is None:
        reasons.append("METRIC_TYPE is null.")

    period_entity = {
        "label": "ReportingPeriod",
        "id_property": "period_id",
        "id": period["period_id"],
        "properties": {
            "name": period["name"],
            "year": period["year"],
            "month": period["month"],
            "source_reporting_month": period["source_reporting_month"],
            "source_year": period["source_year"],
            "period_type": period["period_type"],
        },
    }

    identity_parts = [
        dimension_token(record["source"]),
        dimension_token(record["market"]),
        dimension_token(record["metric"]),
        dimension_token(record.get("segment")),
        dimension_token(record.get("channel")),
        dimension_token(record.get("product_type")),
        dimension_token(record.get("corridor")),
        str(period["source_year"]),
        str(period["source_reporting_month"]),
    ]
    identity_key = "|".join(identity_parts)
    observation_id = f"OBS:{identity_key}"

    risk = None
    risk_values = {
        "appetite": record.get("sq_appetite"),
        "tolerance": record.get("sq_tolerance"),
        "breach_code": record.get("sq_breach_code"),
    }
    if any(value is not None for value in risk_values.values()):
        risk = {
            "label": "RiskProfile",
            "id_property": "risk_profile_id",
            "id": f"RISK:{identity_key}",
            "properties": {
                "appetite": risk_values["appetite"],
                "tolerance": risk_values["tolerance"],
                "breach_code": risk_values["breach_code"],
                "effective_period": period["period_id"],
                "status": RISK_STATUS,
                "observation_id": observation_id,
            },
        }

    if unknown:
        reasons.append("Unmapped source fields: " + ", ".join(sorted(unknown)))

    exact = canonical_payload(record)
    observation_properties = {
        "id_scheme": ID_SCHEME,
        "source_system": record["source"],
        "provenance_platform": None,  # filled by the loader from configuration
        "source_table": None,
        "source_record_hash": source_record_hash(record),
        "source_row_exact": exact,
        "source_field_mapping": None,
        "data_version": None,
        "data_quality_status": "VALID" if not reasons else "REVIEW",
        "data_quality_reason": None if not reasons else "; ".join(reasons),
        "segment_status": status_for(record.get("segment")),
        "channel_status": status_for(record.get("channel")),
        "product_status": status_for(record.get("product_type")),
        "group_status": status_for(record.get("group_all")),
        "corridor_status": status_for(record.get("corridor")),
        "valid_to": None,
    }
    for field in MEASURE_FIELDS:
        observation_properties[field] = record.get(field)
    if unknown:
        observation_properties["unmapped_fields_json"] = json.dumps(unknown, sort_keys=True, default=str)

    return {
        "row_number": row_number,
        "observation_id": observation_id,
        "source_record_hash": observation_properties["source_record_hash"],
        "source_row_exact": exact,
        "entities": {
            "source": source,
            "market": market,
            "metric": metric,
            "segment": segment,
            "channel": channel,
            "product": product,
            "group": group,
            "level": level,
            "unit": unit,
            "period": period_entity,
            "corridor": corridor,
            "risk": risk,
        },
        "observation_properties": observation_properties,
        "quality": observation_properties["data_quality_status"],
    }


def load_sample_records(path: Path) -> List[Dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    records = raw["records"] if isinstance(raw, dict) else raw
    if not isinstance(records, list):
        raise ValueError("sample_data.json must contain a records array.")
    return records


def build_plans(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    plans = []
    for index, raw in enumerate(records, start=1):
        canonical, unknown = canonicalize_record(raw)
        plans.append(build_plan(canonical, unknown, row_number=index))
    return plans


def apply_runtime_config(plan: Dict[str, Any], config: Dict[str, str]) -> None:
    properties = plan["observation_properties"]
    properties["provenance_platform"] = config["provenance_platform"]
    properties["source_table"] = config["source_table"]
    properties["source_field_mapping"] = config["source_field_mapping"]
    properties["data_version"] = config["data_version"]


def distinct_entities(plans: List[Dict[str, Any]], entity_key: str) -> List[Dict[str, Any]]:
    found = {}
    for plan in plans:
        entity = plan["entities"].get(entity_key)
        if entity is None:
            continue
        found[entity["id"]] = entity
    return [found[key] for key in sorted(found)]


def expected_graph(plans: List[Dict[str, Any]]) -> Dict[str, Any]:
    def ids(entity_key: str) -> set:
        return {entity["id"] for entity in distinct_entities(plans, entity_key)}

    def pair_count(left_key: str, right_key: str) -> int:
        pairs = set()
        for plan in plans:
            left = plan["entities"].get(left_key)
            right = plan["entities"].get(right_key)
            if left is not None and right is not None:
                pairs.add((left["id"], right["id"]))
        return len(pairs)

    observation_ids = [plan["observation_id"] for plan in plans]
    node_counts = {
        "Source": len(ids("source")),
        "Market": len(ids("market")),
        "Metric": len(ids("metric")),
        "Segment": len(ids("segment")),
        "Channel": len(ids("channel")),
        "Product": len(ids("product")),
        "MetricGroup": len(ids("group")),
        "MetricLevel": len(ids("level")),
        "Unit": len(ids("unit")),
        "ReportingPeriod": len(ids("period")),
        "Corridor": len(ids("corridor")),
        "KPIObservation": len(set(observation_ids)),
        "RiskProfile": len(ids("risk")),
    }
    relationship_counts = {
        "MEASURES": len(plans),
        "FOR_MARKET": len(plans),
        "FOR_SEGMENT": sum(1 for plan in plans if plan["entities"]["segment"]),
        "THROUGH_CHANNEL": sum(1 for plan in plans if plan["entities"]["channel"]),
        "FOR_PRODUCT": sum(1 for plan in plans if plan["entities"]["product"]),
        "FROM_SOURCE": len(plans),
        "FOR_PERIOD": len(plans),
        "BELONGS_TO_GROUP": sum(1 for plan in plans if plan["entities"]["group"]),
        "HAS_LEVEL": len(plans) + pair_count("metric", "level"),
        "HAS_UNIT": len(plans) if all(plan["entities"]["unit"] for plan in plans) else sum(1 for plan in plans if plan["entities"]["unit"]),
        "HAS_RISK_PROFILE": sum(1 for plan in plans if plan["entities"]["risk"]),
        "FOR_CORRIDOR": sum(1 for plan in plans if plan["entities"]["corridor"]),
        "DEFINED_BY_SOURCE": pair_count("metric", "source"),
        "USES_UNIT": pair_count("metric", "unit"),
        "GROUPED_UNDER": pair_count("metric", "group"),
        "HAS_OBSERVATION": len(plans),
        "OBSERVED_IN": pair_count("metric", "market"),
    }
    # HAS_LEVEL above counts observation edges plus metric edges.
    # HAS_UNIT above counts observation edges only. Metric unit edges are USES_UNIT.
    return {
        "records": len(plans),
        "unique_observation_ids": len(set(observation_ids)),
        "node_counts": node_counts,
        "relationship_counts": relationship_counts,
        "node_total": sum(node_counts.values()),
        "relationship_total": sum(relationship_counts.values()),
    }
