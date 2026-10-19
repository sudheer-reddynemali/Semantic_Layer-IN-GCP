# Redis commands for FalkorDB UNIQUE constraints. These are not Cypher statements.
# Create the indexes in 04_create_indexes.cypher before running these commands.

GRAPH.CONSTRAINT CREATE agentic_kg_pilot UNIQUE NODE BQ_Table PROPERTIES 1 table_id
GRAPH.CONSTRAINT CREATE agentic_kg_pilot UNIQUE NODE BQ_column PROPERTIES 1 column_id
GRAPH.CONSTRAINT CREATE agentic_kg_pilot UNIQUE NODE BQ_KPIMeasure PROPERTIES 1 measure_id
GRAPH.CONSTRAINT CREATE agentic_kg_pilot UNIQUE NODE LookMLKPIMeasure PROPERTIES 1 measure_id
GRAPH.CONSTRAINT CREATE agentic_kg_pilot UNIQUE NODE Metric PROPERTIES 1 metric_id
GRAPH.CONSTRAINT CREATE agentic_kg_pilot UNIQUE NODE Source PROPERTIES 1 source_id
GRAPH.CONSTRAINT CREATE agentic_kg_pilot UNIQUE NODE Market PROPERTIES 1 market_id
GRAPH.CONSTRAINT CREATE agentic_kg_pilot UNIQUE NODE Segment PROPERTIES 1 segment_id
GRAPH.CONSTRAINT CREATE agentic_kg_pilot UNIQUE NODE Channel PROPERTIES 1 channel_id
GRAPH.CONSTRAINT CREATE agentic_kg_pilot UNIQUE NODE Product PROPERTIES 1 product_id
GRAPH.CONSTRAINT CREATE agentic_kg_pilot UNIQUE NODE MetricGroup PROPERTIES 1 group_id
GRAPH.CONSTRAINT CREATE agentic_kg_pilot UNIQUE NODE MetricLevel PROPERTIES 1 level_id
GRAPH.CONSTRAINT CREATE agentic_kg_pilot UNIQUE NODE Unit PROPERTIES 1 unit_id
