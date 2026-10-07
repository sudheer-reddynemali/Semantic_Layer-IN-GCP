# KPI domain

BigQuery table with one row per market / metric / segment / month.

- SOURCE, MARKET, METRIC, SEGMENT, CHANNEL, PRODUCT_TYPE: dimensions.
- METRIC_TYPE: L1 headline, L2 core, L3 business.
- REPORTING_MONTH: YYYYMM integer.
- MTD_* / YTD_* / FY_*: actual, plan and forecast values; VS_PLAN, VS_PY, MOM: variances.
- SQ_BREACH_CODE: GREEN, AMBER or RED risk appetite status.
- UNIT_TYPE: `$`, `#` or `%` (percent values are fractions, e.g. 0.62 = 62%).

Rules:
- Use only the provided tools; never invent numbers.
- If the user gives no month, call `list_kpi_dimensions` with REPORTING_MONTH and use the latest.
- Pass an empty string to a tool filter to skip it.
