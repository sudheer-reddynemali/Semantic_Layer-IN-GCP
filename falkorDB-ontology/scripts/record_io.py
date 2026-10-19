"""Read and write KPI records as JSON or CSV.

Both formats become the same list of source rows. Canonical names, nulls,
and numeric literals are normalized later by normalize.py so a CSV export of
sample_data.json round-trips onto the same observation ids.
"""

from __future__ import annotations

import csv
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from normalize import CANONICAL_FIELDS, canonicalize_field_name, exact_number, project_root


CSV_COLUMNS = [
    "SOURCE",
    "MARKET",
    "METRIC",
    "METRIC_TYPE",
    "SEGMENT",
    "GROUP_ALL",
    "MEET_TARGET",
    "CHANNEL",
    "UNIT_TYPE",
    "VS_YE_TARGET",
    "SQ_APPETITE",
    "SQ_TOLERANCE",
    "SQ_BREACH_CODE",
    "PRODUCT_TYPE",
    "CORRIDOR",
    "YEAR",
    "REPORTING_MONTH",
    "MTD_ACTUAL",
    "MTD_PLAN",
    "YTD_ACTUAL",
    "YTD_PLAN",
    "PY_MTD_ACTUAL",
    "PY_YTD_ACTUAL",
    "FY_FORECAST",
    "FY_PLAN",
    "MOM",
    "PM_ACTUAL",
    "VS_PLAN",
    "VS_PY",
]

_COLUMN_TO_CANONICAL = {name: canonicalize_field_name(name) for name in CSV_COLUMNS}


def default_json_path() -> Path:
    return project_root() / "data" / "sample_data.json"


def default_csv_path() -> Path:
    return project_root() / "data" / "sample_data.csv"


def configured_path(setting: str, default: Optional[Path] = None) -> Optional[Path]:
    configured = os.environ.get(setting)
    if not configured:
        return default
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = project_root() / path
    return path


def load_records(path: Path) -> List[Dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return load_json_records(path)
    if suffix == ".csv":
        return load_csv_records(path)
    raise ValueError(f"Unsupported input {path.name}. Use a .json or .csv file.")


def load_json_records(path: Path) -> List[Dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    records = raw["records"] if isinstance(raw, dict) else raw
    if not isinstance(records, list):
        raise ValueError(f"{path.name} must contain a records array.")
    if not records:
        raise ValueError(f"{path.name} has no records.")
    return records


def load_csv_records(path: Path) -> List[Dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{path.name} has no header row.")
        _require_columns(list(reader.fieldnames), path.name)
        records = []
        for row in reader:
            parsed: Dict[str, Any] = {}
            for key, value in row.items():
                if key is None:
                    continue
                parsed[key] = _parse_cell(value)
            if not any(value is not None for value in parsed.values()):
                continue
            records.append(parsed)
    if not records:
        raise ValueError(f"{path.name} has no records.")
    return records


def write_csv_records(path: Path, records: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for record in records:
            writer.writerow(_csv_row(record))


def _require_columns(fieldnames: Sequence[str], source_name: str) -> None:
    seen = []
    blanks = 0
    for field in fieldnames:
        if field is None or not str(field).strip():
            blanks += 1
            continue
        canonical = canonicalize_field_name(str(field))
        if canonical is None:
            continue
        if canonical in seen:
            raise ValueError(f"{source_name} repeats column {field}.")
        seen.append(canonical)
    missing = [name for name in CANONICAL_FIELDS if name not in seen]
    if missing:
        labels = [name.upper() for name in missing]
        raise ValueError(f"{source_name} is missing columns: {', '.join(labels)}")
    if blanks:
        raise ValueError(f"{source_name} has an empty column header.")


def _parse_cell(value: Optional[str]) -> Any:
    if value is None:
        return None
    text = value.strip()
    if text == "":
        return None
    if _is_int(text):
        return int(text)
    if _is_decimal(text):
        return Decimal(text)
    return text


def _is_int(text: str) -> bool:
    if text.startswith("-"):
        text = text[1:]
    return text.isdigit() and text != ""


def _is_decimal(text: str) -> bool:
    if text.startswith("-"):
        text = text[1:]
    whole, dot, fraction = text.partition(".")
    return bool(dot) and whole.isdigit() and fraction.isdigit() and whole != ""


def _csv_row(record: Dict[str, Any]) -> Dict[str, str]:
    canonical, unknown = _row_values(record)
    if unknown:
        raise ValueError(f"Cannot export unmapped fields: {', '.join(sorted(unknown))}")
    row = {}
    for column, name in _COLUMN_TO_CANONICAL.items():
        row[column] = _format_cell(canonical[name])
    return row


def _row_values(record: Dict[str, Any]) -> tuple:
    from normalize import canonicalize_record

    return canonicalize_record(dict(record))


def _format_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        raise TypeError("Boolean source values are not part of this extract.")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        return exact_number(value) or ""
    raise TypeError(f"Cannot write {type(value).__name__} into the CSV.")
