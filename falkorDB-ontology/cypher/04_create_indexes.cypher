// Identity and lookup indexes for query-time schema retrieval.
// FalkorDB unique constraints require the matching index to exist first.

// BQ_Table.table_id: Identity lookup for the physical table.
CREATE INDEX FOR (n:BQ_Table) ON (n.table_id);

// BQ_Table.name: Find agentic_kg_usecase by physical table name.
CREATE INDEX FOR (n:BQ_Table) ON (n.name);

// BQ_column.column_id: Identity lookup for a physical column.
CREATE INDEX FOR (n:BQ_column) ON (n.column_id);

// BQ_column.name: Find a column by its BigQuery name.
CREATE INDEX FOR (n:BQ_column) ON (n.name);

// BQ_column.label: Match a question to a column label such as Year.
CREATE INDEX FOR (n:BQ_column) ON (n.label);

// BQ_KPIMeasure.measure_id: Identity lookup for a BigQuery measure definition.
CREATE INDEX FOR (n:BQ_KPIMeasure) ON (n.measure_id);

// BQ_KPIMeasure.name: Match a question to a BigQuery measure name.
CREATE INDEX FOR (n:BQ_KPIMeasure) ON (n.name);

// LookMLKPIMeasure.measure_id: Identity lookup for a LookML measure definition.
CREATE INDEX FOR (n:LookMLKPIMeasure) ON (n.measure_id);

// LookMLKPIMeasure.name: Match a LookML measure token.
CREATE INDEX FOR (n:LookMLKPIMeasure) ON (n.name);

// LookMLKPIMeasure.label: Match a question to a LookML measure label.
CREATE INDEX FOR (n:LookMLKPIMeasure) ON (n.label);

// Metric.metric_id: Identity lookup for a metric term.
CREATE INDEX FOR (n:Metric) ON (n.metric_id);

// Metric.name: Match a metric word such as Revenue.
CREATE INDEX FOR (n:Metric) ON (n.name);

// Source.source_id: Identity lookup for a source term.
CREATE INDEX FOR (n:Source) ON (n.source_id);

// Source.name: Match a source code.
CREATE INDEX FOR (n:Source) ON (n.name);

// Market.market_id: Identity lookup for a market term.
CREATE INDEX FOR (n:Market) ON (n.market_id);

// Market.name: Match a market code such as SGH.
CREATE INDEX FOR (n:Market) ON (n.name);

// Segment.segment_id: Identity lookup for a segment term.
CREATE INDEX FOR (n:Segment) ON (n.segment_id);

// Segment.name: Match a segment name.
CREATE INDEX FOR (n:Segment) ON (n.name);

// Channel.channel_id: Identity lookup for a channel term.
CREATE INDEX FOR (n:Channel) ON (n.channel_id);

// Channel.name: Match a channel name.
CREATE INDEX FOR (n:Channel) ON (n.name);

// Product.product_id: Identity lookup for a product term.
CREATE INDEX FOR (n:Product) ON (n.product_id);

// Product.name: Match a product name.
CREATE INDEX FOR (n:Product) ON (n.name);

// MetricGroup.group_id: Identity lookup for a group term.
CREATE INDEX FOR (n:MetricGroup) ON (n.group_id);

// MetricGroup.name: Match a GROUP_ALL term.
CREATE INDEX FOR (n:MetricGroup) ON (n.name);

// MetricLevel.level_id: Identity lookup for a metric tier.
CREATE INDEX FOR (n:MetricLevel) ON (n.level_id);

// Unit.unit_id: Identity lookup for a unit term.
CREATE INDEX FOR (n:Unit) ON (n.unit_id);
