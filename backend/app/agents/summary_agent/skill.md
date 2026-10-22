# Skill: KPI summarisation
0. Look up the knowlege graph first. Call 'get_kg_schema', then use 'query_kg' to match the user's words to graph nodes (Metric, Market, Source, Unit, MetricLevel, etc). Follow DESCRIBE_COLUMN to find the BQ_column, and BQ_KPIMeasure USES_COLUMMN to find the number column. Use those exact names and values in the next step. if nothing matches, or several things do, ask the user.

1. Pick the tool: `kpi_snapshot` for a month view, `kpi_trend` for change over time, `kpi_breaches` for risk.
2. Output format:
   - One-line headline.
   - 3-5 bullets citing values, market, % vs plan and vs prior year.
   - A "Breaches" line listing RED/AMBER items, if any.
3. Format numbers by UNIT_TYPE; keep the whole answer under 150 words.
4. SEGMENT "Total" already includes the other segments: never add it to them, or count it as a separate segment 
