# Graph model

The fact pattern for Taiwan, August 2025:

```text
(Metric: Active Customers)
        ^
        | MEASURES
        |
(KPIObservation 2669116 MTD)
   |-- FOR_MARKET -------> (Market: TAIWAN)
   |-- FOR_SEGMENT ------> (Segment: Personal)
   |-- THROUGH_CHANNEL --> (Channel: Digital)
   |-- FOR_PERIOD -------> (ReportingPeriod: 2025-08)
   |-- FROM_SOURCE ------> (Source: CCO_CLCM)
   |-- HAS_LEVEL --------> (MetricLevel: L1)
   |-- HAS_UNIT ---------> (Unit: # / COUNT)
   |-- HAS_RISK_PROFILE -> (RiskProfile appetite 2403937, tolerance 207055, GREEN)
```

There is no product edge and no group edge on this row, because `PRODUCT_TYPE` and `GROUP_ALL` are null. `product_status` and `group_status` are `UNSPECIFIED`.

India is a second observation of the same `METRIC:ACTIVE_CUSTOMERS` node, through `FOR_MARKET` to `Market: INDIA` and `FOR_SEGMENT` to `Total`. The two markets are not connected to each other.

Digital Registered in Mexico has no `THROUGH_CHANNEL` edge. Its observation id contains the slot token `UNSPECIFIED` where the channel would have been. There is no Channel node named unspecified.

## Node and edge budget for the nine rows

57 nodes and 133 relationships, counted from the distinct values in `data/sample_data.json`. Corridor contributes no node. Eight of the nine rows have a channel. Five have a product. Three have a group. All nine have a risk profile because none of them is null for appetite, tolerance, and breach together.

`HAS_LEVEL` is 17 because each of the 9 observations has a fact edge and the 8 metric definitions each have one projection edge.

## Time

The sample is one business month, `PERIOD:2025-08`. The shape for later months is the same metric, a new observation, and a new period:

```text
(Metric: Active Customers)
   |-- HAS_OBSERVATION --> (KPIObservation) -- FOR_PERIOD --> (2025-08)
   |-- HAS_OBSERVATION --> (KPIObservation) -- FOR_PERIOD --> (2025-09)
   |-- HAS_OBSERVATION --> (KPIObservation) -- FOR_PERIOD --> (2025-10)
```

`py_mtd_actual` and `pm_actual` remain properties until a load supplies those months as their own rows.
