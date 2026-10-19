# Classes

Operational timestamps `created_at` and `updated_at` exist on every node. They are ingestion metadata, not business time.

| Entity | Purpose | Key | Important properties |
| --- | --- | --- | --- |
| Metric | Reusable KPI definition. One node per business name. | `metric_id` | `name`, `normalized_name`, `metric_type`, `unit_type`, `status` |
| Source | Originating business domain, from the `SOURCE` column. | `source_id` | `name`, `normalized_name`, `status` |
| Market | Reported market value, preserved exactly. | `market_id` | `name`, `normalized_name`, `market_type`, `status` |
| Segment | Reported customer segment. | `segment_id` | `name`, `normalized_name`, `status` |
| Channel | Reported channel. Created only when `CHANNEL` is not null. | `channel_id` | `name`, `normalized_name`, `status` |
| Product | Reported product type. Created only when `PRODUCT_TYPE` is not null. | `product_id` | `name`, `normalized_name`, `status` |
| MetricGroup | Value of `GROUP_ALL`. Not interpreted as a confirmed taxonomy. | `group_id` | `name`, `normalized_name`, `source_field`, `status` |
| MetricLevel | Semantic level such as L1, L2, L3. | `level_id` | `code`, `name`, `rank`, `status` |
| Unit | Semantic unit. The source symbol is preserved. | `unit_id` | `code`, `name`, `source_symbol`, `currency_inferred` on currency only |
| ReportingPeriod | Business month derived from `YEAR` and `REPORTING_MONTH`. | `period_id` | `name`, `year`, `month`, `source_reporting_month`, `source_year`, `period_type` |
| Corridor | Optional source dimension. No node exists while every value is null. | `corridor_id` | `name`, `normalized_name`, `status` |
| KPIObservation | The fact: one metric in one dimensional context and period. | `observation_id` | Measure properties, dimension status, provenance, `source_row_exact` |
| RiskProfile | Appetite, tolerance, and breach for one observation. Omitted when all three are null. | `risk_profile_id` | `appetite`, `tolerance`, `breach_code`, `effective_period`, `status`, `observation_id` |

## KPIObservation properties

Measures: `mtd_actual`, `mtd_plan`, `ytd_actual`, `ytd_plan`, `py_mtd_actual`, `py_ytd_actual`, `fy_forecast`, `fy_plan`, `mom`, `pm_actual`, `vs_plan`, `vs_py`, `vs_ye_target`, `meet_target`.

Context status, not fake dimensions: `segment_status`, `channel_status`, `product_status`, `group_status`, `corridor_status`. Each is `SPECIFIED` or `UNSPECIFIED`.

Provenance: `source_system`, `provenance_platform`, `source_table`, `source_record_hash`, `source_row_exact`, `source_field_mapping`, `ingestion_timestamp`, `loaded_at`, `valid_from`, `valid_to`, `data_version`, `data_quality_status`, `data_quality_reason`, `id_scheme`.

`source_system` repeats the business source code for direct filtering. The semantic link is `FROM_SOURCE`. `provenance_platform` is the technical platform, `BIGQUERY`.

Risk numbers are not copied onto the observation. They live on `RiskProfile`.

## Unit reading

| Source symbol | Unit id | Code | Currency inferred |
| --- | --- | --- | --- |
| `#` | `UNIT:COUNT` | `COUNT` | not applicable |
| `%` | `UNIT:PERCENT` | `PERCENT` | not applicable |
| `$` | `UNIT:CURRENCY` | `CURRENCY` | `false` |

An unrecognized symbol becomes `UNIT:SOURCE_<token>` and the observation is marked `REVIEW`. The symbol itself is kept.
