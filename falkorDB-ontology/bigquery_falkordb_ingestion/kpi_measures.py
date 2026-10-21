"""Configuration loading and validation for extensible KPI definitions."""

from __future__ import annotations

import json
import math
import re
from string import Formatter
from pathlib import Path
from typing import Any

CANONICAL_FIELDS = {
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
}

LABEL_ID_PROPERTIES = {
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

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ALLOWED_AGGREGATIONS = {"sum", "avg", "min", "max", "count", "none"}


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        config = json.load(handle)
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    if not isinstance(config, dict):
        raise ValueError("Ingestion config must be a JSON object.")
    bigquery = config.get("bigquery")
    if not isinstance(bigquery, dict) or any(
        not isinstance(bigquery.get(field), str) or not bigquery[field]
        for field in ("project", "dataset", "table")
    ):
        raise ValueError("Config bigquery settings must include project, dataset, and table.")
    mappings = config.get("canonical_field_mappings")
    vocabularies = config.get("vocabulary_mappings")
    measures = config.get("kpi_definitions")
    if (
        not isinstance(mappings, dict)
        or not isinstance(vocabularies, list)
        or not isinstance(measures, list)
    ):
        raise ValueError("Config must define canonical_field_mappings, vocabulary_mappings, and kpi_definitions.")
    required_fields = config.get("required_fields", [])
    if not isinstance(required_fields, list) or any(
        not isinstance(field, str) or field not in CANONICAL_FIELDS
        for field in required_fields
    ):
        raise ValueError("required_fields must contain only canonical field names.")
    if (
        isinstance(config.get("batch_size"), bool)
        or not isinstance(config.get("batch_size"), int)
        or config["batch_size"] < 1
    ):
        raise ValueError("batch_size must be a positive integer.")
    if (
        isinstance(config.get("retry_limit"), bool)
        or not isinstance(config.get("retry_limit"), int)
        or config["retry_limit"] < 0
    ):
        raise ValueError("retry_limit must be a non-negative integer.")
    retry_base = config.get("retry_base_seconds")
    if (
        isinstance(retry_base, bool)
        or not isinstance(retry_base, (int, float))
        or not math.isfinite(retry_base)
        or retry_base < 0
    ):
        raise ValueError("retry_base_seconds must be a non-negative number.")

    for source, target in mappings.items():
        if not isinstance(source, str):
            raise ValueError("BigQuery source field names must be text.")
        _identifier(source, "BigQuery source field")
        if not isinstance(target, str):
            raise ValueError(f"Canonical mapping for {source} must be text.")
        if target not in CANONICAL_FIELDS:
            raise ValueError(f"Unknown canonical field {target!r} for {source}.")

    fields_seen: set[str] = set()
    for mapping in vocabularies:
        if not isinstance(mapping, dict):
            raise ValueError("Each vocabulary mapping must be a JSON object.")
        for key in ("bigquery_column", "canonical_field", "label", "id_property", "id_prefix", "falkordb_column"):
            if not isinstance(mapping.get(key), str) or not mapping[key]:
                raise ValueError(f"Vocabulary mapping is missing {key}.")
        source_field = mapping["bigquery_column"]
        _identifier(source_field, "Vocabulary BigQuery column")
        _identifier(mapping["falkordb_column"], "Vocabulary FalkorDB column")
        _identifier(mapping["id_prefix"], "Vocabulary identifier prefix")
        if (
            not isinstance(mapping["canonical_field"], str)
            or mapping["canonical_field"] not in CANONICAL_FIELDS
        ):
            raise ValueError(f"Unknown canonical vocabulary field {mapping['canonical_field']!r}.")
        if _canonical_for_source(mapping["bigquery_column"], mappings) != mapping["canonical_field"]:
            raise ValueError(
                f"Canonical mapping for {mapping['bigquery_column']} must resolve to "
                f"{mapping['canonical_field']}."
            )
        if mapping["label"] not in LABEL_ID_PROPERTIES:
            raise ValueError(f"Unsupported vocabulary label {mapping['label']!r}.")
        if mapping["id_property"] != LABEL_ID_PROPERTIES[mapping["label"]]:
            raise ValueError(f"Incorrect id property for {mapping['label']}.")
        fields_seen.add(source_field)

    if not fields_seen:
        raise ValueError("At least one vocabulary mapping is required.")

    ids_seen: set[str] = set()
    for measure in measures:
        if not isinstance(measure, dict):
            raise ValueError("Each KPI definition must be a JSON object.")
        for key in (
            "key",
            "bigquery_column",
            "canonical_field",
            "falkordb_column",
            "name_template",
            "measure_id_template",
            "aggregation",
        ):
            if not isinstance(measure.get(key), str) or not measure[key]:
                raise ValueError(f"KPI definition is missing {key}.")
        _identifier(measure["bigquery_column"], "KPI BigQuery column")
        _identifier(measure["falkordb_column"], "KPI FalkorDB column")
        _identifier(measure["key"], "KPI key")
        if (
            not isinstance(measure["canonical_field"], str)
            or measure["canonical_field"] not in CANONICAL_FIELDS
        ):
            raise ValueError(f"Unknown canonical KPI field {measure['canonical_field']!r}.")
        if _canonical_for_source(measure["bigquery_column"], mappings) != measure["canonical_field"]:
            raise ValueError(
                f"Canonical mapping for {measure['bigquery_column']} must resolve to "
                f"{measure['canonical_field']}."
            )
        if measure["aggregation"] not in ALLOWED_AGGREGATIONS:
            raise ValueError(
                f"Unsupported aggregation {measure['aggregation']!r} in KPI {measure['key']}."
            )
        if not isinstance(measure.get("filters", {}), dict):
            raise ValueError(f"KPI filters must be an object for {measure['key']}.")
        for column, canonical_field in measure.get("filters", {}).items():
            _identifier(column, "KPI filter column")
            if (
                not isinstance(canonical_field, str)
                or canonical_field not in CANONICAL_FIELDS
            ):
                raise ValueError(
                    f"Unknown canonical filter field {canonical_field!r} for KPI {measure['key']}."
                )
        for template_name in ("name_template", "measure_id_template"):
            fields = {
                field_name
                for _, field_name, _, _ in Formatter().parse(
                    measure[template_name]
                )
                if field_name
            }
            if not fields.issubset({"metric", "kpi"}):
                raise ValueError(
                    f"Unsupported placeholder in KPI {measure['key']} {template_name}."
                )
        if measure["key"] in ids_seen:
            raise ValueError(f"Duplicate KPI definition key {measure['key']!r}.")
        ids_seen.add(measure["key"])
    sample_measure_ids = [
        measure["measure_id_template"].format(
            metric="SAMPLE_METRIC",
            kpi=measure["key"].lower(),
        )
        for measure in measures
    ]
    if any("{metric}" not in measure["measure_id_template"] for measure in measures):
        raise ValueError("Each measure_id_template must include {metric}.")
    if len(sample_measure_ids) != len(set(sample_measure_ids)):
        raise ValueError("KPI measure_id_template values produce duplicate IDs.")
    unit_values = config.get("unit_values", {})
    if not isinstance(unit_values, dict):
        raise ValueError("unit_values must be a JSON object.")
    for symbol, properties in unit_values.items():
        if not isinstance(symbol, str) or not isinstance(properties, dict):
            raise ValueError("Each unit_values entry must map a text symbol to an object.")
        if any(
            not isinstance(properties.get(key), str) or not properties[key]
            for key in ("id", "code", "name", "source_symbol")
        ):
            raise ValueError(f"Unit mapping for {symbol!r} must define id, code, name, and source_symbol.")


def _identifier(value: str, description: str) -> None:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid {description}: {value!r}.")


def _canonical_for_source(source: str, mappings: dict[str, str]) -> str | None:
    by_upper = {name.upper(): canonical for name, canonical in mappings.items()}
    explicit = by_upper.get(source.upper())
    if explicit is not None:
        return explicit
    normalized = re.sub(r"[^a-z0-9]+", "_", source.lower()).strip("_")
    return normalized if normalized in CANONICAL_FIELDS else None
