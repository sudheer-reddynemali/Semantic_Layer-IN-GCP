# Relationships

Stored direction is observation toward the dimension. Cypher can traverse that edge in either direction, so the inverse edge is not materialized.

| From | Relationship | To | Cardinality | Origin | Meaning |
| --- | --- | --- | --- | --- | --- |
| KPIObservation | `MEASURES` | Metric | many to one | `SOURCE_FACT` | This row measures that KPI definition. |
| KPIObservation | `FOR_MARKET` | Market | many to one | `SOURCE_FACT` | Reported market context. |
| KPIObservation | `FOR_SEGMENT` | Segment | many to one, optional | `SOURCE_FACT` | Present when `SEGMENT` is not null. |
| KPIObservation | `THROUGH_CHANNEL` | Channel | many to one, optional | `SOURCE_FACT` | Present when `CHANNEL` is not null. |
| KPIObservation | `FOR_PRODUCT` | Product | many to one, optional | `SOURCE_FACT` | Present when `PRODUCT_TYPE` is not null. |
| KPIObservation | `FOR_CORRIDOR` | Corridor | many to one, optional | `SOURCE_FACT` | Present when `CORRIDOR` is not null. None in the sample. |
| KPIObservation | `FROM_SOURCE` | Source | many to one | `SOURCE_FACT` | Business domain that produced the row. |
| KPIObservation | `FOR_PERIOD` | ReportingPeriod | many to one | `SOURCE_FACT` | Business reporting month. |
| KPIObservation | `BELONGS_TO_GROUP` | MetricGroup | many to one, optional | `SOURCE_FACT` | Present when `GROUP_ALL` is not null. |
| KPIObservation | `HAS_LEVEL` | MetricLevel | many to one | `SOURCE_FACT` | Level reported on this row. |
| KPIObservation | `HAS_UNIT` | Unit | many to one | `SOURCE_FACT` | Unit symbol reported on this row. |
| KPIObservation | `HAS_RISK_PROFILE` | RiskProfile | one to one, optional | `SOURCE_FACT` | Present when appetite, tolerance, or breach is not null. |
| Metric | `DEFINED_BY_SOURCE` | Source | many to many | `SOURCE_PROJECTION` | Sources that have reported this metric name. |
| Metric | `HAS_LEVEL` | MetricLevel | many to many | `SOURCE_PROJECTION` | Levels at which this metric name has been reported. |
| Metric | `USES_UNIT` | Unit | many to many | `SOURCE_PROJECTION` | Units in which this metric name has been reported. |
| Metric | `GROUPED_UNDER` | MetricGroup | many to many | `SOURCE_PROJECTION` | Groups attached to this metric name by `GROUP_ALL`. |
| Metric | `HAS_OBSERVATION` | KPIObservation | one to many | `DERIVED` | Convenience inverse of `MEASURES`. |
| Metric | `OBSERVED_IN` | Market | many to many | `DERIVED` | Markets in which this metric has an observation. |

In the sample, each metric name has one source, one level, and one unit. The projection relationships are still many-to-many so a later conflict is visible as two edges instead of a silent overwrite of history. The single-valued `metric_type` and `unit_type` properties on `Metric` follow the latest load of that metric name.

`HAS_LEVEL` is used twice on purpose. From an observation it is the fact. From a metric it is the definitional projection. `origin` distinguishes them. The sample therefore has 17 `HAS_LEVEL` edges: 9 facts and 8 metric projections.

Risk is not lifted onto `Metric`. Appetite in the sample changes by market and is often null, so a single metric-level threshold would be an invented policy.
