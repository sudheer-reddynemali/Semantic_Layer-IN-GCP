"""Tests for binding the ontology table node to its BigQuery source."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ontology_csv import load_ontology, set_table_source_identity  # noqa: E402


class TableSourceIdentityTests(unittest.TestCase):
    def test_source_override_updates_name_and_project_without_changing_graph_ids(self):
        ontology_path = ROOT / "ontology" / "enterprise_kpi_ontology.csv"
        ontology = load_ontology(ontology_path)
        table = next(node for node in ontology["nodes"] if node["label"] == "BQ_Table")
        original_id = table["id"]

        set_table_source_identity(
            ontology,
            table_name="usecase_abc",
            project="gcp-fs-looker-agentic",
        )

        self.assertEqual(table["id"], original_id)
        self.assertEqual(table["properties"]["name"], "usecase_abc")
        self.assertEqual(table["properties"]["project"], "gcp-fs-looker-agentic")

    def test_blank_source_values_are_rejected(self):
        ontology = load_ontology(ROOT / "ontology" / "enterprise_kpi_ontology.csv")
        with self.assertRaisesRegex(ValueError, "table name cannot be blank"):
            set_table_source_identity(ontology, table_name=" ")


if __name__ == "__main__":
    unittest.main()
