# Data lineage

Two clocks are kept apart.

| Clock | Where it lives | Sample value |
| --- | --- | --- |
| Business time | `ReportingPeriod.year`, `month`, `source_reporting_month` | `2025`, `8`, `202508` |
| Ingestion time | `ingestion_timestamp`, `loaded_at`, `created_at`, `updated_at`, `valid_from` | UTC time of the graph load |

The extract does not contain an event timestamp. None is invented from `REPORTING_MONTH`. `valid_from` is the first time that observation id was written. `valid_to` stays null, meaning the row is the current graph version. A second load of the same grain updates measures and ingestion time and leaves `valid_from` in place. It does not keep the previous numeric version.

## Provenance on every observation

| Property | Meaning |
| --- | --- |
| `source_system` | Business source code from `SOURCE`, for example `CCO_CLCM` |
| `provenance_platform` | `BIGQUERY` |
| `source_table` | Logical table `KPI_MONTHLY_SNAPSHOT` |
| `source_field_mapping` | `MAP:KPI_MONTHLY_SNAPSHOT:1.0.0` |
| `source_row_exact` | Canonical JSON of the source row, with numbers as exact decimal text |
| `source_record_hash` | SHA-256 of `source_row_exact` |
| `data_version` | `1.0.0` |
| `data_quality_status` | `VALID` or `REVIEW` |
| `id_scheme` | `OBS_V1` |

`source_table` is a logical name. The physical BigQuery table path was not part of the extract.

## What is a fact

A source fact is an observation edge with `origin = 'SOURCE_FACT'`, plus the measure properties. A projection repeats a source column on the metric so a definition can be traversed without scanning facts. A derived edge only shortens a path that already exists. The validator rejects edges that are not in that set, including any market-to-market link.

## Quality rules

An observation requires source, market, metric, year, and reporting month. A blank string is treated as null. A null channel, product, group, or corridor sets the matching status to `UNSPECIFIED` and creates no node. An unknown unit symbol, an unmapped column, or a year that disagrees with `REPORTING_MONTH` sets `data_quality_status` to `REVIEW` and keeps the source values.
