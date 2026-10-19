// Query-time ontology checks. These should show the schema graph only.
// Numbers are not stored here. ReportingPeriod, KPIObservation, RiskProfile,
// and KPIMeasure are retired and should not appear.

MATCH (n)
RETURN labels(n)[0] AS label, count(*) AS nodes
ORDER BY label;

MATCH ()-[r]->()
RETURN type(r) AS relationship, r.origin AS origin, count(*) AS edges
ORDER BY relationship, origin;

MATCH (t:BQ_Table {name: 'agentic_kg_usecase'})-[:HAS_COLUMN]->(c:BQ_column)
RETURN t.name AS table_name, count(c) AS columns
ORDER BY table_name;

MATCH (m:BQ_KPIMeasure {name: 'Revenue YTD Actual'})
OPTIONAL MATCH (m)-[:ON_TABLE]->(t:BQ_Table)
OPTIONAL MATCH (m)-[:USES_COLUMN]->(c:BQ_column)
RETURN m.name AS measure, m.value_column AS value_column, m.aggregation AS aggregation,
       m.filters AS filters, t.name AS table_name, collect(c.name) AS used_columns;

MATCH (n)
WHERE n:ReportingPeriod OR n:KPIObservation OR n:RiskProfile OR n:KPIMeasure
RETURN labels(n) AS labels, count(*) AS nodes;
