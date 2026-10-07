# Skill: chart specs

Spec shape:

{"type": "bar" | "line", "title": str, "xKey": str,
 "series": [{"key": str, "label": str}], "data": [{xKey: ..., key: number}]}

- Use "line" for trends over months, "bar" for comparisons across markets/metrics.
- Max 30 data rows; values must be numbers, not strings.
- Flatten rows so every series key is a column in each data row (pivot markets into columns if comparing).
- Pick the tool: `kpi_trend` for lines, `kpi_snapshot` for bars.
