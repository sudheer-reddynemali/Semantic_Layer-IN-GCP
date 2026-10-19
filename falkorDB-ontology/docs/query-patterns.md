# Query patterns

These are graph traversals over `enterprise_kpi`. They are not a retrieval service. Variances are the source-supplied properties. "Below plan" compares `mtd_actual` with `mtd_plan`.

The Python list that was executed is `EXAMPLE_QUERIES` in `scripts/validate_graph.py`. Run it with:

```bash
.venv/bin/python scripts/validate_graph.py --examples
```

## 1. Exact metric lookup

```cypher
MATCH (m:Metric {name: 'Active Customers'})
RETURN m.metric_id, m.name, m.metric_type, m.unit_type, m.status
```

Returns one metric, `METRIC:ACTIVE_CUSTOMERS`, level L1, unit `#`.

## 2. Metric and market

```cypher
MATCH (m:Metric {name: 'Active Customers'})<-[:MEASURES]-(o:KPIObservation)-[:FOR_MARKET]->(mk:Market {name: 'INDIA'})
RETURN m.name, mk.name, o.mtd_actual, o.ytd_actual
```

India MTD actual is `3327893`. YTD actual is `3236275`.

## 3. Metric, market, and period

```cypher
MATCH (m:Metric {name: 'Active Customers'})<-[:MEASURES]-(o:KPIObservation)-[:FOR_MARKET]->(mk:Market {name: 'INDIA'})
MATCH (o)-[:FOR_PERIOD]->(p:ReportingPeriod {period_id: 'PERIOD:2025-08'})
RETURN m.name, mk.name, p.name, o.mtd_actual, o.mtd_plan, o.ytd_actual
```

MTD plan is `3075642`.

## 4. One metric across markets

```cypher
MATCH (m:Metric {name: 'Active Customers'})<-[:MEASURES]-(o:KPIObservation)-[:FOR_MARKET]->(mk:Market)
MATCH (o)-[:FOR_PERIOD]->(p:ReportingPeriod)
RETURN mk.name, p.name, o.mtd_actual, o.ytd_actual
ORDER BY mk.name
```

India `3327893` and Taiwan `2669116` for `2025-08`.

## 5. Below MTD plan

```cypher
MATCH (o:KPIObservation)-[:MEASURES]->(m:Metric)
MATCH (o)-[:FOR_MARKET]->(mk:Market)
WHERE o.mtd_actual < o.mtd_plan
RETURN m.name, mk.name, o.mtd_actual, o.mtd_plan, o.vs_plan
ORDER BY m.name, mk.name
```

Taiwan Active Customers, Mexico Digital Registered, USA First Contact Resolution, AOC Revenue per Customer.

## 6. Above MTD plan

```cypher
MATCH (o:KPIObservation)-[:MEASURES]->(m:Metric)
MATCH (o)-[:FOR_MARKET]->(mk:Market)
WHERE o.mtd_actual > o.mtd_plan
RETURN m.name, mk.name, o.mtd_actual, o.mtd_plan, o.vs_plan
ORDER BY m.name, mk.name
```

India Active Customers, MYH Customer Effort Score, INM Digital Retail Values, TOP 9 MARKETS Digital/Mobile Registered, AOC tNPS.

## 7. RED and AMBER

```cypher
MATCH (o:KPIObservation)-[:HAS_RISK_PROFILE]->(r:RiskProfile)
MATCH (o)-[:MEASURES]->(m:Metric)
MATCH (o)-[:FOR_MARKET]->(mk:Market)
WHERE r.breach_code IN ['RED', 'AMBER']
RETURN m.name, mk.name, r.breach_code, r.appetite, r.tolerance
ORDER BY r.breach_code, m.name
```

AMBER: Customer Effort Score and tNPS. RED: First Contact Resolution. `NA` is excluded and still stored.

## 8. By segment

```cypher
MATCH (seg:Segment {name: 'Premier'})<-[:FOR_SEGMENT]-(o:KPIObservation)-[:MEASURES]->(m:Metric)
RETURN seg.name, m.name, o.mtd_actual
ORDER BY m.name
```

Premier contains Digital Registered and First Contact Resolution.

## 9. By channel

```cypher
MATCH (ch:Channel {name: 'Digital'})<-[:THROUGH_CHANNEL]-(o:KPIObservation)-[:MEASURES]->(m:Metric)
MATCH (o)-[:FOR_MARKET]->(mk:Market)
RETURN ch.name, m.name, mk.name
ORDER BY m.name, mk.name
```

Digital contains Active Customers in India and Taiwan, and Revenue per Customer in AOC.

## 10. By source

```cypher
MATCH (s:Source {name: 'CCO_CLCM'})<-[:FROM_SOURCE]-(o:KPIObservation)-[:MEASURES]->(m:Metric)
MATCH (o)-[:FOR_MARKET]->(mk:Market)
RETURN s.name, m.name, mk.name
ORDER BY mk.name
```

CCO_CLCM contains Active Customers for India and Taiwan.

## 11. History

```cypher
MATCH (o:KPIObservation)-[:FOR_PERIOD]->(p:ReportingPeriod)
MATCH (o)-[:MEASURES]->(m:Metric)
MATCH (o)-[:FOR_MARKET]->(mk:Market)
RETURN m.name, mk.name, p.name, o.mtd_actual
ORDER BY p.year, p.month, m.name, mk.name
```

With one loaded month this returns the nine August rows, ordered so later periods will sort after them.

## 12. Latest observation per grain

```cypher
MATCH (o:KPIObservation)-[:FOR_PERIOD]->(p:ReportingPeriod)
MATCH (o)-[:MEASURES]->(m:Metric)
MATCH (o)-[:FOR_MARKET]->(mk:Market)
MATCH (o)-[:FROM_SOURCE]->(s:Source)
OPTIONAL MATCH (o)-[:FOR_SEGMENT]->(seg:Segment)
OPTIONAL MATCH (o)-[:THROUGH_CHANNEL]->(ch:Channel)
OPTIONAL MATCH (o)-[:FOR_PRODUCT]->(prd:Product)
WITH s.source_id AS source_id, mk.market_id AS market_id, m.metric_id AS metric_id,
     seg.segment_id AS segment_id, ch.channel_id AS channel_id, prd.product_id AS product_id,
     m, mk, p, o
ORDER BY p.year DESC, p.month DESC
WITH source_id, market_id, metric_id, segment_id, channel_id, product_id,
     collect({metric: m.name, market: mk.name, period: p.name, mtd_actual: o.mtd_actual})[0] AS latest
RETURN latest.metric AS metric, latest.market AS market, latest.period AS period, latest.mtd_actual AS mtd_actual
ORDER BY metric, market
```

Grain is source, market, metric, segment, channel, and product. The latest period wins. Today every grain has one month.

## 13. Current month versus previous year

```cypher
MATCH (o:KPIObservation)-[:MEASURES]->(m:Metric)
MATCH (o)-[:FOR_MARKET]->(mk:Market)
RETURN m.name, mk.name, o.mtd_actual, o.py_mtd_actual, o.vs_py
ORDER BY m.name, mk.name
```

`py_mtd_actual` and `vs_py` are properties of the August observation.

## 14. MTD versus YTD

```cypher
MATCH (o:KPIObservation)-[:MEASURES]->(m:Metric)
MATCH (o)-[:FOR_MARKET]->(mk:Market)
RETURN m.name, mk.name, o.mtd_actual, o.ytd_actual, o.mtd_plan, o.ytd_plan
ORDER BY m.name, mk.name
```

## 15. FY forecast below FY plan

```cypher
MATCH (o:KPIObservation)-[:MEASURES]->(m:Metric)
MATCH (o)-[:FOR_MARKET]->(mk:Market)
WHERE o.fy_forecast < o.fy_plan
RETURN m.name, mk.name, o.fy_forecast, o.fy_plan
ORDER BY m.name, mk.name
```

India Active Customers, Taiwan Active Customers, TOP 9 MARKETS Digital/Mobile Registered, and AOC tNPS.

## 16. Risk appetite present

```cypher
MATCH (o:KPIObservation)-[:HAS_RISK_PROFILE]->(r:RiskProfile)
MATCH (o)-[:MEASURES]->(m:Metric)
MATCH (o)-[:FOR_MARKET]->(mk:Market)
WHERE r.appetite IS NOT NULL
RETURN m.name, mk.name, r.appetite, r.breach_code
ORDER BY m.name, mk.name
```

Five observations have an appetite. The other four still have a risk profile because tolerance or breach code is present. tNPS appetite is `10.81` and its tolerance is null.

## 17. Market, observation, metric, source

```cypher
MATCH (mk:Market)<-[:FOR_MARKET]-(o:KPIObservation)-[:MEASURES]->(m:Metric)
MATCH (o)-[:FROM_SOURCE]->(s:Source)
RETURN mk.name, m.name, s.name
ORDER BY mk.name, m.name
```

The stored direction is observation to market. The query walks that edge inward from the market.

## 18. Segment, observation, metric, channel

```cypher
MATCH (seg:Segment)<-[:FOR_SEGMENT]-(o:KPIObservation)-[:MEASURES]->(m:Metric)
OPTIONAL MATCH (o)-[:THROUGH_CHANNEL]->(ch:Channel)
RETURN seg.name, m.name, ch.name
ORDER BY seg.name, m.name
```

Premier / Digital Registered has an empty channel. That is the Mexico row whose channel was null.

## 19. Metrics by level

```cypher
MATCH (m:Metric)-[:HAS_LEVEL]->(l:MetricLevel)
RETURN l.code, m.name
ORDER BY l.rank, m.name
```

L1: Active Customers, tNPS. L2: Digital Registered, Digital/Mobile Registered, First Contact Resolution. L3: Customer Effort Score, Digital Retail Values, Revenue per Customer.
