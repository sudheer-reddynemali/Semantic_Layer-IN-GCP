# Skill: chart specs

First, look up the knowlege graph. Call 'get_kg_schema', then use 'query_kg' to match the user's words to graph nodes (Metric, Market, Source, Unit, MetricLevel, etc) and find the eact BigQuery column and values via DESCRIBE_COLUMN and USES_COLUMMN. If nothing matches, ask the user.


Spec shape:

{"type": "bar" | "line", "title": str, "xKey": str,
 "series": [{"key": str, "label": str}], "data": [{xKey: ..., key: number}]}

- Use "line" for trends over months, "bar" for comparisons across markets/metrics.
- Max 30 data rows; values must be numbers, not strings.
- Flatten rows so every series key is a column in each data row (pivot markets into columns if comparing).
- Pick the tool: `kpi_trend` for lines, `kpi_snapshot` for bars.
- Never mix SEGMENT "total" with individual segments in one chart.
