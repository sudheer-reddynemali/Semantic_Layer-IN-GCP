"""Only source-derived business entities are added to the schema ontology."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kpi_measures import add_kpi_measures  # noqa: E402
from normalize import CANONICAL_FIELDS  # noqa: E402
from ontology_csv import keep_schema_only, load_ontology  # noqa: E402
from vocabulary_values import add_value_nodes  # noqa: E402


class SourceDerivedOntologyTests(unittest.TestCase):
    def test_sample_metrics_and_terms_are_not_added_without_source_rows(self):
        ontology = keep_schema_only(
            load_ontology(ROOT / "ontology" / "enterprise_kpi_ontology.csv")
        )
        record = {field: None for field in CANONICAL_FIELDS}
        record.update(
            {
                "source": "ABC_CLM",
                "market": "USA",
                "metric": "Active Customers",
                "metric_type": "L1",
                "segment": "Retail",
                "channel": "Digital",
                "product_type": "Cards",
                "unit_type": "#",
            }
        )

        add_value_nodes(ontology, [record])
        add_kpi_measures(ontology, [record])

        metrics = {
            node["properties"]["name"]
            for node in ontology["nodes"]
            if node["label"] == "Metric"
        }
        measure_names = {
            node["properties"]["name"]
            for node in ontology["nodes"]
            if node["label"] == "BQ_KPIMeasure"
        }
        lookml_measures = [
            node for node in ontology["nodes"] if node["label"] == "LookMLKPIMeasure"
        ]
        self.assertEqual(metrics, {"Active Customers"})
        self.assertEqual(measure_names, {"Active Customers YTD Actual"})
        self.assertEqual(lookml_measures, [])
        self.assertNotIn("Revenue", metrics)
        self.assertFalse(
            any(node["label"] in {"KPIObservation", "ReportingPeriod", "RiskProfile"}
                for node in ontology["nodes"])
        )


if __name__ == "__main__":
    unittest.main()
