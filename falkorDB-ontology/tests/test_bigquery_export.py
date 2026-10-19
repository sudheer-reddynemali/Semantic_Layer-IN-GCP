"""BigQuery column mapping tests for the pilot CSV exporter."""

from __future__ import annotations

import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from export_bigquery_csv import _canonicalize_row  # noqa: E402
from record_io import CSV_COLUMNS, load_csv_records, write_csv_records  # noqa: E402


class BigQueryExportTests(unittest.TestCase):
    def test_bigquery_aliases_round_trip_to_canonical_csv(self):
        source = {column: "sample" for column in CSV_COLUMNS}
        aliases = {
            "MEET_TARGET": "TARGET_MEET",
            "MTD_ACTUAL": "MTD_ACT",
            "YTD_ACTUAL": "YTD_ACTL",
            "PY_MTD_ACTUAL": "PY_MTD_ACT",
            "PY_YTD_ACTUAL": "PY_YTD_ACTL",
            "PM_ACTUAL": "PM_ACTL",
        }
        for canonical_name, bigquery_name in aliases.items():
            source[bigquery_name] = source.pop(canonical_name)
        source["MTD_ACT"] = 12.5
        source["YEAR"] = 2024
        source["CORRIDOR"] = "NA"

        record = _canonicalize_row(source)
        self.assertEqual(record["meet_target"], "sample")
        self.assertEqual(record["mtd_actual"], Decimal("12.5"))
        self.assertEqual(record["year"], 2024)
        self.assertIsNone(record["corridor"])

        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "pilot.csv"
            write_csv_records(csv_path, [record])
            loaded = load_csv_records(csv_path)

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["MEET_TARGET"], "sample")
        self.assertEqual(loaded[0]["MTD_ACTUAL"], Decimal("12.5"))
        self.assertIsNone(loaded[0]["CORRIDOR"])

    def test_unmapped_bigquery_column_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unmapped column"):
            _canonicalize_row({"NOT_A_SOURCE_COLUMN": "value"})


if __name__ == "__main__":
    unittest.main()
