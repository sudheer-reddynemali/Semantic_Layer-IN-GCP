"""JSON and CSV record ingestion: same keys, no duplicate writes, incremental diffs."""

from __future__ import annotations

import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fact_graph import (  # noqa: E402
    content_hash,
    observation_state,
    plan_ingestion,
    prepare_plans,
    relationship_keys,
)
from normalize import CANONICAL_FIELDS, expected_graph  # noqa: E402
from record_io import CSV_COLUMNS, load_records, write_csv_records  # noqa: E402


CONFIG = {
    "provenance_platform": "BIGQUERY",
    "source_table": "KPI_MONTHLY_SNAPSHOT",
    "source_field_mapping": "MAP:KPI_MONTHLY_SNAPSHOT:1.0.0",
    "data_version": "1.0.0",
}


def _record(index: int, **changes):
    row = {field: None for field in CANONICAL_FIELDS}
    row.update(
        {
            "source": "CCO_CLCM",
            "market": f"M{index}",
            "metric": "Active Customers",
            "metric_type": "L1",
            "segment": "Total",
            "channel": "Digital",
            "unit_type": "#",
            "year": 2025,
            "reporting_month": 202508,
            "mtd_actual": index,
            "ytd_actual": index,
        }
    )
    row.update(changes)
    return row


def _state_from(plans):
    observations = {plan["observation_id"]: observation_state(plan) for plan in plans}
    dimensions = {}
    for plan in plans:
        for entity in plan["entities"].values():
            if entity is None:
                continue
            dimensions[(entity["label"], entity["id"])] = content_hash(entity["properties"])
    return observations, dimensions


class RecordFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.json_path = ROOT / "data" / "sample_data.json"
        cls.csv_path = ROOT / "data" / "sample_data.csv"
        cls.json_records = load_records(cls.json_path)
        cls.csv_records = load_records(cls.csv_path)

    def test_csv_has_the_twenty_nine_columns_and_nine_rows(self):
        text = self.csv_path.read_text(encoding="utf-8")
        header = text.splitlines()[0]
        self.assertEqual(header, ",".join(CSV_COLUMNS))
        self.assertEqual(len(self.csv_records), 9)
        self.assertEqual(len(self.json_records), 9)

    def test_json_and_csv_build_the_same_graph_plan(self):
        json_plans, json_dupes = prepare_plans(self.json_records, CONFIG)
        csv_plans, csv_dupes = prepare_plans(self.csv_records, CONFIG)
        self.assertEqual(json_dupes, 0)
        self.assertEqual(csv_dupes, 0)
        self.assertEqual(
            [plan["observation_id"] for plan in json_plans],
            [plan["observation_id"] for plan in csv_plans],
        )
        self.assertEqual(
            [plan["source_record_hash"] for plan in json_plans],
            [plan["source_record_hash"] for plan in csv_plans],
        )
        self.assertEqual(expected_graph(json_plans), expected_graph(csv_plans))
        self.assertEqual(relationship_keys(json_plans), relationship_keys(csv_plans))
        expected = expected_graph(json_plans)["relationship_counts"]
        for rel_type, count in expected.items():
            self.assertEqual(relationship_keys(json_plans).get(rel_type, 0), count)

    def test_nulls_and_exact_numbers_survive_the_csv(self):
        india = next(row for row in self.csv_records if row["MARKET"] == "INDIA")
        self.assertIsNone(india["CORRIDOR"])
        self.assertIsNone(india["PRODUCT_TYPE"])
        self.assertIsNone(india["GROUP_ALL"])
        self.assertEqual(india["MTD_ACTUAL"], 3327893)
        self.assertEqual(india["YEAR"], 2025)
        first = self.csv_records[0]
        self.assertEqual(first["MTD_ACTUAL"], Decimal("11.5"))
        self.assertEqual(first["CHANNEL"], "Mobile")
        self.assertIsNone(first["CORRIDOR"])

    def test_header_aliases_match_json_identity(self):
        raw = {
            "SOURCE": "CCO_CLCM",
            "MARKET": "TOP 9 MARKETS",
            "METRIC": "Active Customers",
            "YEAR": 2025,
            "REPORTING_MONTH": 202508,
        }
        alias_plans, _dupes = prepare_plans([raw], CONFIG)
        canonical_plans, _dupes = prepare_plans(
            [
                {
                    "source": "CCO_CLCM",
                    "market": "TOP 9 MARKETS",
                    "metric": "Active Customers",
                    "year": 2025,
                    "reporting_month": 202508,
                }
            ],
            CONFIG,
        )
        self.assertEqual(alias_plans[0]["observation_id"], canonical_plans[0]["observation_id"])
        self.assertEqual(alias_plans[0]["source_record_hash"], canonical_plans[0]["source_record_hash"])
        self.assertIn("TOP_9_MARKETS", alias_plans[0]["observation_id"])


class IncrementalIngestionTests(unittest.TestCase):
    def test_same_input_twice_writes_nothing_the_second_time(self):
        records = [_record(index) for index in range(100)]
        plans, collapsed = prepare_plans(records, CONFIG)
        self.assertEqual(collapsed, 0)
        self.assertEqual(len(plans), 100)
        first = plan_ingestion(plans, {}, {}, "2026-10-13T00:00:00Z")
        self.assertEqual(len(first["created"]), 100)
        self.assertEqual(first["updated"], [])
        self.assertEqual(first["unchanged"], [])
        self.assertGreater(len(first["statements"]), 0)
        observations, dimensions = _state_from(plans)
        second = plan_ingestion(plans, observations, dimensions, "2026-10-13T01:00:00Z")
        self.assertEqual(second["statements"], [])
        self.assertEqual(len(second["unchanged"]), 100)
        self.assertEqual(second["created"], [])
        self.assertEqual(second["updated"], [])
        self.assertEqual(second["entity_creates"], 0)
        self.assertEqual(second["entity_updates"], 0)

    def test_two_appended_records_create_only_those_observations(self):
        original = [_record(index) for index in range(100)]
        added = [_record(100), _record(101)]
        original_plans, _dupes = prepare_plans(original, CONFIG)
        combined, _dupes = prepare_plans(original + added, CONFIG)
        observations, dimensions = _state_from(original_plans)
        diff = plan_ingestion(combined, observations, dimensions, "2026-10-13T02:00:00Z")
        self.assertEqual(len(diff["created"]), 2)
        self.assertEqual(len(diff["unchanged"]), 100)
        self.assertEqual(diff["updated"], [])
        script = "\n".join(diff["statements"])
        for plan in diff["created"]:
            merge = f"MERGE (n:KPIObservation {{observation_id: '{plan['observation_id']}'}}"
            self.assertEqual(script.count(merge), 1)
        for plan in original_plans:
            self.assertNotIn(plan["observation_id"], script)

    def test_a_changed_measure_updates_the_same_observation(self):
        original = [_record(1, mtd_actual=10, ytd_actual=20)]
        changed = [_record(1, mtd_actual=11, ytd_actual=20)]
        before, _dupes = prepare_plans(original, CONFIG)
        after, _dupes = prepare_plans(changed, CONFIG)
        self.assertEqual(before[0]["observation_id"], after[0]["observation_id"])
        self.assertNotEqual(before[0]["source_record_hash"], after[0]["source_record_hash"])
        observations, dimensions = _state_from(before)
        diff = plan_ingestion(after, observations, dimensions, "2026-10-13T03:00:00Z")
        self.assertEqual(len(diff["updated"]), 1)
        self.assertEqual(diff["created"], [])
        statement = next(item for item in diff["statements"] if "KPIObservation" in item)
        create_line = next(line for line in statement.splitlines() if line.startswith("ON CREATE"))
        match_line = next(line for line in statement.splitlines() if line.startswith("ON MATCH"))
        self.assertIn("n.created_at", create_line)
        self.assertIn("n.valid_from", create_line)
        self.assertNotIn("n.created_at", match_line)
        self.assertNotIn("n.valid_from", match_line)
        self.assertIn("n.updated_at", match_line)
        self.assertIn("n.mtd_actual = 11", match_line)
        self.assertEqual(statement.count("MERGE (n:KPIObservation"), 1)

    def test_row_order_is_not_the_business_key(self):
        records = [_record(index) for index in range(10)]
        forward, _dupes = prepare_plans(records, CONFIG)
        backward, _dupes = prepare_plans(list(reversed(records)), CONFIG)
        observations, dimensions = _state_from(forward)
        diff = plan_ingestion(backward, observations, dimensions, "2026-10-13T04:00:00Z")
        self.assertEqual(diff["statements"], [])
        self.assertEqual(len(diff["unchanged"]), 10)

    def test_duplicate_business_keys_collapse_to_the_last_row(self):
        first = _record(7, mtd_actual=1)
        second = _record(7, mtd_actual=2)
        plans, collapsed = prepare_plans([first, second], CONFIG)
        self.assertEqual(collapsed, 1)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["observation_properties"]["mtd_actual"], 2)
        diff = plan_ingestion(plans, {}, {}, "2026-10-13T05:00:00Z")
        self.assertEqual(len(diff["created"]), 1)
        script = "\n".join(diff["statements"])
        self.assertEqual(script.count("MERGE (n:KPIObservation"), 1)

    def test_csv_round_trip_matches_the_incremental_key(self):
        records = [_record(3, mtd_actual=Decimal("1.50"), corridor=None, channel=None)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rows.csv"
            write_csv_records(path, records)
            loaded = load_records(path)
        original, _dupes = prepare_plans(records, CONFIG)
        restored, _dupes = prepare_plans(loaded, CONFIG)
        self.assertEqual(original[0]["source_record_hash"], restored[0]["source_record_hash"])
        self.assertIsNone(restored[0]["entities"]["channel"])
        self.assertIsNone(restored[0]["entities"]["corridor"])


class WipeCommandTests(unittest.TestCase):
    def test_wipe_without_confirmation_does_not_delete(self):
        from ingest_records import main

        self.assertEqual(main(["--wipe"]), 2)

    def test_wipe_cannot_be_combined_with_ingestion(self):
        from ingest_records import main

        source = ROOT / "data" / "sample_data.json"
        self.assertEqual(main(["--wipe", "--confirm-wipe", "--input", str(source)]), 2)


if __name__ == "__main__":
    unittest.main()
