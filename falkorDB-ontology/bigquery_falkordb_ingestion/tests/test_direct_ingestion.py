from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import redis

from bigquery_falkordb_ingestion.graph import graph_query
from bigquery_falkordb_ingestion.ingest import (
    canonicalize_row,
    process_batches,
    replay_failures,
    selected_source_columns,
    upsert_record,
)
from bigquery_falkordb_ingestion.kpi_measures import load_config, validate_config
from bigquery_falkordb_ingestion.ontology import check_config_columns, load_schema

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config(PACKAGE_ROOT / "config.json")
SCHEMA = load_schema(
    PACKAGE_ROOT / "ontology" / "enterprise_kpi_ontology.csv",
    "usecase_abc",
    "gcp-fs-looker-agentic",
)


class FakeGraph:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.queries: list[str] = []

    def write(self, _graph: str, query: str) -> None:
        self.queries.append(query)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("temporary FalkorDB write failure")


class RejectingGraph:
    def execute_command(self, *_args: str) -> None:
        raise redis.ResponseError("invalid query")


def sample_source_row() -> dict[str, str]:
    return {
        "SOURCE": "CCO_CLCM",
        "MARKET": "INM",
        "METRIC": "Active Customers",
        "METRIC_TYPE": "L1",
        "SEGMENT": "Retail",
        "GROUP_ALL": "tNPS",
        "CHANNEL": "Digital",
        "UNIT_TYPE": "#",
        "PRODUCT_TYPE": "Cards",
        "CORRIDOR": "NA",
    }


class DirectIngestionTests(unittest.TestCase):
    def test_latest_ontology_schema_and_configured_columns_agree(self) -> None:
        check_config_columns(CONFIG, SCHEMA)
        self.assertEqual(len(SCHEMA["columns"]), 29)
        self.assertEqual(len(SCHEMA["edges"]), 29)
        self.assertEqual(
            {node["label"] for node in SCHEMA["nodes"]},
            {"BQ_Table", "BQ_column"},
        )
        self.assertEqual(SCHEMA["nodes"][0]["properties"].get("project"), "gcp-fs-looker-agentic")

    def test_canonicalize_row_applies_aliases_and_required_fields(self) -> None:
        record = canonicalize_row(
            {
                **sample_source_row(),
                "YTD_ACTL": "1200.50",
            },
            CONFIG,
        )
        self.assertEqual(record["ytd_actual"], "1200.50")
        self.assertEqual(record["metric"], "Active Customers")
        self.assertNotIn("YTD_ACTL", selected_source_columns(CONFIG))

    def test_future_kpi_can_be_added_by_configuration_only(self) -> None:
        config = deepcopy(CONFIG)
        config["canonical_field_mappings"]["YTD_PLAN"] = "ytd_plan"
        config["kpi_definitions"].append(
            {
                "key": "ytd_plan",
                "bigquery_column": "YTD_PLAN",
                "canonical_field": "ytd_plan",
                "falkordb_column": "YTD_PLAN",
                "name_template": "{metric} YTD Plan",
                "measure_id_template": "BQMEASURE:{metric}_{kpi}",
                "aggregation": "sum",
                "filters": {"METRIC": "metric"},
            }
        )
        validate_config(config)
        graph = FakeGraph()
        with patch(
            "bigquery_falkordb_ingestion.ingest.graph_query",
            side_effect=lambda client, _graph_name, query: client.write(_graph_name, query),
        ):
            upsert_record(
                graph,
                "enterprise_kpi",
                SCHEMA,
                config,
                canonicalize_row(sample_source_row(), config),
            )
        query = graph.queries[0]
        self.assertIn("BQMEASURE:active_customers_ytd_plan", query)
        self.assertIn("BQMEASURE:active_customers'", query)
        self.assertIn("value_column = 'YTD_PLAN'", query)

    def test_upsert_uses_stable_merge_ids_and_does_not_store_fact_values(self) -> None:
        graph = FakeGraph()
        record = canonicalize_row(sample_source_row(), CONFIG)
        with patch(
            "bigquery_falkordb_ingestion.ingest.graph_query",
            side_effect=lambda client, _graph_name, query: client.write(_graph_name, query),
        ):
            upsert_record(graph, "enterprise_kpi", SCHEMA, CONFIG, record)

        self.assertEqual(len(graph.queries), 1)
        query = graph.queries[0]
        self.assertIn("MERGE (v0:Source {source_id: 'SOURCE:CCO_CLCM'})", query)
        self.assertIn("MERGE (v2:Metric {metric_id: 'METRIC:ACTIVE_CUSTOMERS'})", query)
        self.assertIn("MERGE (m0:BQ_KPIMeasure {measure_id: 'BQMEASURE:active_customers'})", query)
        self.assertIn("DESCRIBES_COLUMN", query)
        self.assertIn("USES_COLUMN", query)
        self.assertNotIn("KPIObservation", query)
        self.assertNotIn("ytd_actual", query)
        self.assertIn("\nWITH *\nMATCH (v0)", query)

    def test_progress_callback_reports_success_and_failure_counts(self) -> None:
        graph = FakeGraph(failures=1)
        progress: list[dict[str, int]] = []
        with tempfile.TemporaryDirectory() as temporary:
            with patch("bigquery_falkordb_ingestion.ingest.time.sleep"):
                with patch(
                    "bigquery_falkordb_ingestion.ingest.graph_query",
                    side_effect=lambda client, graph_name, query: client.write(graph_name, query),
                ):
                    result = process_batches(
                        [sample_source_row(), sample_source_row()],
                        client=graph,
                        graph="enterprise_kpi",
                        schema=SCHEMA,
                        config=CONFIG,
                        batch_size=1,
                        retry_limit=0,
                        retry_base_seconds=0,
                        failed_file=Path(temporary) / "failed_rows.jsonl",
                        progress_callback=progress.append,
                    )
        self.assertEqual(result, {"batches": 2, "rows": 2, "succeeded": 1, "failed": 1})
        self.assertEqual(progress, [
            {"batches": 1, "rows": 1, "succeeded": 0, "failed": 1},
            {"batches": 2, "rows": 2, "succeeded": 1, "failed": 1},
        ])

    def test_graph_errors_do_not_persist_query_literals(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "FalkorDB query failed: invalid query") as raised:
            graph_query(
                RejectingGraph(),
                "enterprise_kpi",
                "MERGE (n:Source {name: 'sensitive-row-value'})",
            )
        self.assertNotIn("sensitive-row-value", str(raised.exception))

    def test_failed_row_is_retried_and_persisted_after_retry_limit(self) -> None:
        graph = FakeGraph(failures=4)
        row = sample_source_row()
        with tempfile.TemporaryDirectory() as temporary:
            failed_file = Path(temporary) / "failed_rows.jsonl"
            with patch("bigquery_falkordb_ingestion.ingest.time.sleep"):
                with patch(
                    "bigquery_falkordb_ingestion.ingest.graph_query",
                    side_effect=lambda client, graph_name, query: client.write(graph_name, query),
                ):
                    result = process_batches(
                        [row],
                        client=graph,
                        graph="enterprise_kpi",
                        schema=SCHEMA,
                        config=CONFIG,
                        batch_size=100,
                        retry_limit=2,
                        retry_base_seconds=0,
                        failed_file=failed_file,
                    )
            self.assertEqual(result, {"batches": 1, "rows": 1, "succeeded": 0, "failed": 1})
            entry = json.loads(failed_file.read_text(encoding="utf-8"))
            self.assertEqual(entry["attempts"], 3)
            self.assertEqual(entry["source_record"], row)

    def test_replay_removes_a_failure_after_a_successful_upsert(self) -> None:
        graph = FakeGraph()
        with tempfile.TemporaryDirectory() as temporary:
            failed_file = Path(temporary) / "failed_rows.jsonl"
            failed_file.write_text(
                json.dumps({"source_record": sample_source_row()}) + "\n",
                encoding="utf-8",
            )
            with patch("bigquery_falkordb_ingestion.ingest.time.sleep"):
                with patch(
                    "bigquery_falkordb_ingestion.ingest.graph_query",
                    side_effect=lambda client, graph_name, query: client.write(graph_name, query),
                ):
                    result = replay_failures(
                        failed_file,
                        client=graph,
                        graph="enterprise_kpi",
                        schema=SCHEMA,
                        config=CONFIG,
                        retry_limit=1,
                        retry_base_seconds=0,
                    )
            self.assertEqual(result, {"replayed": 1, "succeeded": 1, "failed": 0})
            self.assertEqual(failed_file.read_text(encoding="utf-8"), "")


if __name__ == "__main__":
    unittest.main()
