# Source to ontology mapping

Mapping version: `MAP:agentic_kg_usecase:2.0.0`.

The ontology source is `ontology/enterprise_kpi_ontology.csv`. For the BigQuery pilot, the physical source is `usecase_abc` in project `gcp-fs-looker-agentic`; pass `--table-name usecase_abc --project gcp-fs-looker-agentic` to the ontology loader and validator. The `use_case` remains `agentic_kg`, and stable ontology graph IDs are retained.

The graph stores schema and measure definitions so an agent can build a query. Cell values stay in BigQuery. `ReportingPeriod`, `KPIObservation`, `RiskProfile`, and `KPIMeasure` are not loaded. `YEAR` and `REPORTING_MONTH` are ordinary `BQ_column` nodes, recognized by name and label. Their formats are `YYYY` and `MM`.

| Graph object | What it stores | How it connects |
| --- | --- | --- |
| `BQ_Table` | Table name, platform, project, use case, metadata | `HAS_COLUMN` to every physical column |
| `BQ_column` | label, name, type, mode, format, description, table details, metadata (`column_role`), provenance, enum | One node per column of `agentic_kg_usecase` |
| `BQ_KPIMeasure` | name, value column, aggregation, filters | `ON_TABLE` the table. `USES_COLUMN` only the columns that measure aggregates or filters |
| `LookMLKPIMeasure` | type, sql, label, description, value format, filters | `DEFINED_ON` the table. `READS_COLUMN` the sql column. `FILTERS_COLUMN` the resolved filter columns. `ALIGNS_WITH` the matching BigQuery measure when there is one |
| Vocabulary (`Metric`, `Source`, `Market`, `Segment`, `Channel`, `Product`, `MetricGroup`, `MetricLevel`, `Unit`, `Corridor`) | Business terms | `DESCRIBES_COLUMN` the column the term names. No corridor term is created until a name exists |

`column_role` is `dimension`, `kpi_measure`, `filter`, `join_key`, or a combination. A BigQuery measure does not copy the 29-column catalog. At query time the agent can add further columns, such as `MARKET`, `YEAR`, and `REPORTING_MONTH`, from `HAS_COLUMN`.

Sample BigQuery measures filter `SOURCE` to `CCO_REVENUE_L1_L2` and `METRIC` to `Revenue`, and aggregate with `sum`:

| Measure | Value column | Also uses |
| --- | --- | --- |
| Revenue YTD Actual | `YTD_ACTUAL` | `SOURCE`, `METRIC` |
| Revenue - YTD Plan | `YTD_PLAN` | `SOURCE`, `METRIC` |
| Revenue Full Year Plan | `FY_PLAN` | `SOURCE`, `METRIC` |

Closed enums live on the column: markets `SGH|UAE|INM|AOC|EXP|MYH|TWN|USA|MEX`, tiers `L1|L2|L3`, units `$|#|%`. An open column has a blank enum. Filter values stay on the measure node.
