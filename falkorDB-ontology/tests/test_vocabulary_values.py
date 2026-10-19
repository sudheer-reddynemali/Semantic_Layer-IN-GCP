"""Distinct extract values become vocabulary nodes on the matching column."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kpi_measures import add_kpi_measures  # noqa: E402
from ontology_csv import default_csv_path, load_ontology  # noqa: E402
from record_io import default_csv_path as records_csv  # noqa: E402
from record_io import load_records  # noqa: E402
from vocabulary_values import add_value_nodes  # noqa: E402


class VocabularyValueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ontology = load_ontology(default_csv_path())
        cls.added = add_value_nodes(cls.ontology, load_records(records_csv()))
        cls.by_id = {node["id"]: node for node in cls.ontology["nodes"]}
        cls.edges = {(edge["from_id"], edge["type"], edge["to_id"]) for edge in cls.ontology["edges"]}

    def test_sample_sources_describe_the_source_column(self):
        source_column = "BQ_COL:agentic_kg_usecase.SOURCE"
        for name, node_id in (
            ("CCO_CX", "SOURCE:CCO_CX"),
            ("CCO_Digital", "SOURCE:CCO_DIGITAL"),
            ("CCO_CLCM", "SOURCE:CCO_CLCM"),
            ("CCO_Revenue", "SOURCE:CCO_REVENUE"),
        ):
            self.assertEqual(self.by_id[node_id]["properties"]["name"], name)
            self.assertIn((node_id, "DESCRIBES_COLUMN", source_column), self.edges)

    def test_display_names_and_existing_examples_are_kept(self):
        self.assertEqual(self.by_id["MARKET:TOP_9_MARKETS"]["properties"]["name"], "TOP 9 MARKETS")
        self.assertEqual(self.by_id["MARKET:SGH"]["properties"]["name"], "SGH")
        self.assertEqual(self.by_id["LEVEL:L1"]["properties"]["rank"], 1)
        self.assertEqual(self.by_id["LEVEL:L2"]["properties"]["rank"], 2)
        self.assertEqual(self.by_id["UNIT:COUNT"]["id"], "UNIT:COUNT")
        self.assertIn("UNIT:PERCENT", self.by_id)
        self.assertIn("UNIT:CURRENCY", self.by_id)
        self.assertNotIn("CORRIDOR:", " ".join(self.by_id))
        self.assertGreater(self.added, 0)

    def test_a_new_market_is_linked_and_an_existing_one_is_left_alone(self):
        from vocabulary_values import pending_vocabulary

        statements = pending_vocabulary(
            [{"market": "HONG KONG", "source": "CCO_CX"}],
            {"SOURCE:CCO_CX"},
            {("SOURCE:CCO_CX", "DESCRIBES_COLUMN", "BQ_COL:agentic_kg_usecase.SOURCE")},
            "2026-10-13T00:00:00Z",
        )
        script = "\n".join(statements)
        self.assertIn("MARKET:HONG_KONG", script)
        self.assertIn("BQ_COL:agentic_kg_usecase.MARKET", script)
        self.assertNotIn("SOURCE:CCO_CX", script)


class KpiMeasureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ontology = load_ontology(default_csv_path())
        add_value_nodes(cls.ontology, load_records(records_csv()))
        cls.added = add_kpi_measures(cls.ontology, load_records(records_csv()))
        cls.by_id = {node["id"]: node for node in cls.ontology["nodes"]}

    def test_each_sample_metric_gets_a_query_definition(self):
        self.assertEqual(self.added, 8)
        measure = self.by_id["BQMEASURE:active_customers"]
        self.assertEqual(measure["properties"]["name"], "Active Customers YTD Actual")
        self.assertEqual(measure["properties"]["value_column"], "YTD_ACTUAL")
        self.assertEqual(measure["properties"]["aggregation"], "none")
        self.assertEqual(
            measure["properties"]["filters"],
            '{"SOURCE":"CCO_CLCM","METRIC":"Active Customers"}',
        )
        edges = {(edge["from_id"], edge["type"], edge["to_id"]) for edge in self.ontology["edges"]}
        self.assertIn(
            ("BQMEASURE:active_customers", "ON_TABLE", "BQ_TABLE:agentic_kg_usecase"),
            edges,
        )
        self.assertIn(
            ("BQMEASURE:active_customers", "USES_COLUMN", "BQ_COL:agentic_kg_usecase.YTD_ACTUAL"),
            edges,
        )
        self.assertEqual(self.by_id["BQMEASURE:revenue_ytd_actual"]["properties"]["aggregation"], "sum")
        self.assertNotIn("BQMEASURE:revenue", self.by_id)


if __name__ == "__main__":
    unittest.main()
