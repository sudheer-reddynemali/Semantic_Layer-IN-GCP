# Identifiers

Display names are the trimmed source values. `TOP 9 MARKETS` stays `TOP 9 MARKETS`. The normalized token is used only inside ids.

Normalization:

1. Trim.
2. Uppercase.
3. Replace every run of non-alphanumeric characters with one underscore.
4. Strip leading and trailing underscores.

| Business value | Id |
| --- | --- |
| `CCO_CLCM` | `SOURCE:CCO_CLCM` |
| `TOP 9 MARKETS` | `MARKET:TOP_9_MARKETS` |
| `Active Customers` | `METRIC:ACTIVE_CUSTOMERS` |
| `Digital/Mobile Registered` | `METRIC:DIGITAL_MOBILE_REGISTERED` |
| `Global Private Banking` | `SEGMENT:GLOBAL_PRIVATE_BANKING` |
| `tNPS` | `GROUP:TNPS` and, for the metric, `METRIC:TNPS` |
| August 2025 | `PERIOD:2025-08` |

## Observation grain

```text
OBS:<source>|<market>|<metric>|<segment>|<channel>|<product>|<corridor>|<year>|<reporting_month>
```

Null slots use the token `UNSPECIFIED`. That token is part of the key so two rows that differ only by a null do not collapse, and it is never created as a Channel, Product, Group, or Corridor node.

India, August 2025:

```text
OBS:CCO_CLCM|INDIA|ACTIVE_CUSTOMERS|TOTAL|DIGITAL|UNSPECIFIED|UNSPECIFIED|2025|202508
```

Taiwan uses the same metric id and a different observation id, because the market and segment slots differ.

The risk profile for the same grain is `RISK:` plus the same body. A risk node is created only when at least one of appetite, tolerance, and breach code is present.

`id_scheme = OBS_V1` records this slot order. Corridor is included even though the conceptual example omitted it. Corridor is a source column, and leaving it out of the key would merge future rows that differ only by corridor.

## Period id

`YEAR` is the business year. The last two digits of `REPORTING_MONTH` are the month. The original `REPORTING_MONTH` is stored as `source_reporting_month`. For the sample, `2025` and `202508` become `PERIOD:2025-08`. If the year prefix of `REPORTING_MONTH` disagrees with `YEAR`, the observation is marked `REVIEW` and both values are kept.

## Reloading

MERGE on these ids makes a second load update the same nodes. `valid_from` and `created_at` stay at the first load. `ingestion_timestamp`, `loaded_at`, and `updated_at` move to the latest load. A new reporting month produces a new observation id and does not rewrite the August node.
