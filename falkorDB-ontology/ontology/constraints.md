# Constraints and indexes

Uniqueness has two layers.

1. The loader uses `MERGE` on the deterministic id, so a repeated load cannot create a second node for the same business key.
2. FalkorDB `UNIQUE` node constraints reject a second node with the same id if a write bypasses the loader.

On FalkorDB 6.0.1 the unique constraint requires the matching index to exist first. `CREATE INDEX FOR (n:Label) ON (n.property)` creates the range index the constraint accepts. Run `cypher/04_create_indexes.cypher` before `cypher/01_create_constraints.cypher`. The Python loader does that.

Constraints are created with:

```text
GRAPH.CONSTRAINT CREATE enterprise_kpi UNIQUE NODE <Label> PROPERTIES 1 <id_property>
```

They become `OPERATIONAL` asynchronously. The loader waits for that status before writing observations.

## Indexes

FalkorDB lists one index entry per label. Properties on that label are indexed together.

| Index | Why it exists |
| --- | --- |
| `Source.source_id` | Identity and the unique constraint. |
| `Source.name` | Find a domain such as `CCO_CLCM` by its reported code. |
| `Market.market_id` | Identity and the unique constraint. |
| `Market.name` | Market lookup, including `TOP 9 MARKETS`. |
| `Segment.segment_id` | Identity and the unique constraint. |
| `Segment.name` | Segment lookup. |
| `Channel.channel_id` | Identity and the unique constraint. |
| `Channel.name` | Channel lookup for Digital, Mobile, and Branch. |
| `Product.product_id` | Identity and the unique constraint. |
| `Product.name` | Product lookup. |
| `Metric.metric_id` | Identity and the unique constraint. |
| `Metric.name` | Exact KPI lookup, for example Active Customers. |
| `MetricGroup.group_id` | Identity and the unique constraint. |
| `MetricGroup.name` | Group lookup for `tNPS` and `Complaints`. |
| `MetricLevel.level_id` | Identity and the unique constraint. |
| `Unit.unit_id` | Identity and the unique constraint. |
| `ReportingPeriod.period_id` | Resolve a business month such as `PERIOD:2025-08`. |
| `KPIObservation.observation_id` | Identity and the unique constraint. |
| `KPIObservation.source_record_hash` | Find a row by its source fingerprint. |
| `RiskProfile.risk_profile_id` | Identity and the unique constraint. |
| `Corridor.corridor_id` | Identity for the corridor dimension when a future row populates it. |

Name indexes are not unique constraints. Identity is the normalized id. Level and unit names are not separately indexed because those sets are tiny and are reached through relationships.

No vector, full-text, or embedding index is created.
