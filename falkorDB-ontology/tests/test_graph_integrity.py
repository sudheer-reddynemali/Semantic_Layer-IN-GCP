"""Ontology unit checks, plus a live FalkorDB integrity check when the server is up."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from normalize import (  # noqa: E402
    build_plans,
    canonicalize_field_name,
    canonicalize_record,
    expected_graph,
    load_sample_records,
)


class NormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = load_sample_records(ROOT / "data" / "sample_data.json")
        cls.plans = build_plans(cls.records)

    def test_field_aliases_collapse_to_canonical_names(self):
        aliases = {
            "METRIC TYPE": "metric_type",
            "METRIC_TYPE": "metric_type",
            "GROUP ALL": "group_all",
            "GROUP_ALL": "group_all",
            "UNIT TYPE": "unit_type",
            "UNIT _TYPE": "unit_type",
            "UNIT_TYPE": "unit_type",
            "PRODUCT TYPE": "product_type",
            "PRODUCT_TYPE": "product_type",
            "REPORTING MONTH": "reporting_month",
            "REPORTING_MONTH": "reporting_month",
            "VS PY": "vs_py",
            "VS_PY": "vs_py",
            "PY YTD ACTUAL": "py_ytd_actual",
            "PY_YTD_ACTUAL": "py_ytd_actual",
        }
        for raw, canonical in aliases.items():
            self.assertEqual(canonicalize_field_name(raw), canonical)

    def test_alias_record_preserves_business_value(self):
        canonical, unknown = canonicalize_record(
            {"MARKET": "TOP 9 MARKETS", "UNIT _TYPE": "#", "GROUP ALL": None}
        )
        self.assertEqual(unknown, {})
        self.assertEqual(canonical["market"], "TOP 9 MARKETS")
        self.assertEqual(canonical["unit_type"], "#")
        self.assertIsNone(canonical["group_all"])

    def test_sample_has_nine_unique_observations(self):
        summary = expected_graph(self.plans)
        self.assertEqual(summary["records"], 9)
        self.assertEqual(summary["unique_observation_ids"], 9)

    def test_display_names_are_not_rewritten(self):
        markets = {plan["entities"]["market"]["properties"]["name"] for plan in self.plans}
        self.assertIn("TOP 9 MARKETS", markets)
        self.assertIn("INDIA", markets)
        self.assertIn("INM", markets)
        metric_names = {plan["entities"]["metric"]["properties"]["name"] for plan in self.plans}
        self.assertIn("Digital/Mobile Registered", metric_names)
        self.assertIn("tNPS", metric_names)

    def test_null_channel_does_not_create_a_channel_entity(self):
        mex = next(
            plan
            for plan in self.plans
            if plan["entities"]["metric"]["properties"]["name"] == "Digital Registered"
        )
        self.assertIsNone(mex["entities"]["channel"])
        self.assertIsNone(mex["entities"]["group"])
        self.assertEqual(mex["observation_properties"]["channel_status"], "UNSPECIFIED")
        self.assertNotIn("CHANNEL:UNSPECIFIED", mex["observation_id"])
        self.assertIn("|UNSPECIFIED|", mex["observation_id"])

    def test_null_product_does_not_create_a_product_entity(self):
        india = next(
            plan
            for plan in self.plans
            if plan["entities"]["market"]["properties"]["name"] == "INDIA"
        )
        self.assertIsNone(india["entities"]["product"])
        self.assertIsNone(india["entities"]["group"])
        self.assertIsNone(india["entities"]["corridor"])
        self.assertEqual(
            india["observation_id"],
            "OBS:CCO_CLCM|INDIA|ACTIVE_CUSTOMERS|TOTAL|DIGITAL|UNSPECIFIED|UNSPECIFIED|2025|202508",
        )

    def test_taiwan_active_customers_identity(self):
        taiwan = next(
            plan
            for plan in self.plans
            if plan["entities"]["market"]["properties"]["name"] == "TAIWAN"
        )
        self.assertEqual(
            taiwan["observation_id"],
            "OBS:CCO_CLCM|TAIWAN|ACTIVE_CUSTOMERS|PERSONAL|DIGITAL|UNSPECIFIED|UNSPECIFIED|2025|202508",
        )
        self.assertEqual(taiwan["observation_properties"]["mtd_actual"], 2669116)
        self.assertEqual(taiwan["entities"]["metric"]["id"], "METRIC:ACTIVE_CUSTOMERS")

    def test_active_customers_is_one_metric_definition(self):
        metric_ids = {
            plan["entities"]["metric"]["id"]
            for plan in self.plans
            if plan["entities"]["metric"]["properties"]["name"] == "Active Customers"
        }
        self.assertEqual(metric_ids, {"METRIC:ACTIVE_CUSTOMERS"})

    def test_currency_symbol_is_not_treated_as_usd(self):
        revenue = next(
            plan
            for plan in self.plans
            if plan["entities"]["metric"]["properties"]["name"] == "Revenue per Customer"
        )
        unit = revenue["entities"]["unit"]
        self.assertEqual(unit["id"], "UNIT:CURRENCY")
        self.assertEqual(unit["properties"]["source_symbol"], "$")
        self.assertIs(unit["properties"]["currency_inferred"], False)
        self.assertNotIn("currency_code", unit["properties"])

    def test_expected_shape_is_derived_from_distinct_source_values(self):
        summary = expected_graph(self.plans)
        self.assertEqual(summary["node_counts"]["Channel"], 3)
        self.assertEqual(summary["node_counts"]["Product"], 3)
        self.assertEqual(summary["node_counts"]["Corridor"], 0)
        self.assertEqual(summary["node_counts"]["ReportingPeriod"], 1)
        self.assertEqual(summary["node_counts"]["KPIObservation"], 9)
        self.assertGreater(summary["relationship_counts"]["MEASURES"], 0)
        self.assertEqual(
            summary["relationship_counts"]["THROUGH_CHANNEL"],
            sum(1 for plan in self.plans if plan["entities"]["channel"]),
        )
        self.assertEqual(
            summary["relationship_counts"]["FOR_PRODUCT"],
            sum(1 for plan in self.plans if plan["entities"]["product"]),
        )


class FalkorDBIntegrityTests(unittest.TestCase):
    def test_load_is_idempotent_and_matches_sample(self):
        from falkor_client import connect, connection_settings, graph_query, load_env_file, rows_as_dicts
        from load_sample_data import main
        from validate_graph import validate

        load_env_file(ROOT / ".env")
        settings = connection_settings()
        try:
            client = connect(settings["host"], settings["port"])
            client.ping()
        except Exception as exc:  # pragma: no cover - local server is required for this proof
            self.fail(f"FalkorDB is not reachable: {exc}")

        self.assertEqual(main([]), 0)
        self.assertEqual(validate(), [])
        before = rows_as_dicts(
            graph_query(
                client,
                settings["graph"],
                "MATCH (m:BQ_KPIMeasure) RETURN m.measure_id AS measure_id, m.created_at AS created_at ORDER BY measure_id",
            )
        )
        self.assertEqual(main([]), 0)
        after = rows_as_dicts(
            graph_query(
                client,
                settings["graph"],
                "MATCH (m:BQ_KPIMeasure) RETURN m.measure_id AS measure_id, m.created_at AS created_at ORDER BY measure_id",
            )
        )
        self.assertEqual(before, after)
        retired = rows_as_dicts(
            graph_query(
                client,
                settings["graph"],
                "MATCH (n) WHERE n:ReportingPeriod OR n:KPIObservation OR n:RiskProfile OR n:KPIMeasure RETURN count(n) AS retired",
            )
        )
        self.assertEqual(int(retired[0]["retired"]), 0)
        self.assertEqual(validate(), [])


if __name__ == "__main__":
    unittest.main()
