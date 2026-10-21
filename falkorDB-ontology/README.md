# Enterprise KPI ontology on FalkorDB

The graph stores query-time metadata for the configured BigQuery table. An agent uses it to choose columns and a measure definition, then runs the query in BigQuery. Numeric fact values are not stored on the graph.

`BQ_Table` is the parent. `HAS_COLUMN` links it to one `BQ_column` per physical column. A `BQ_KPIMeasure` is a query definition (`name`, `value_column`, `aggregation`, `filters`) linked with `ON_TABLE` and `USES_COLUMN`. A `LookMLKPIMeasure` stays separate (`type`, `sql`, `label`, `description`, `value_format_name`, `filters`) and may `ALIGNS_WITH` the matching BigQuery measure. `YEAR` and `REPORTING_MONTH` are ordinary columns. `ReportingPeriod`, `KPIObservation`, `RiskProfile`, and `KPIMeasure` are not loaded.

The source file is `ontology/enterprise_kpi_ontology.csv`. The field mapping is [docs/source-to-ontology-mapping.md](docs/source-to-ontology-mapping.md).

## Start FalkorDB

Docker Desktop is required. The compose file uses `falkordb/falkordb:6.0.1`. The graph name is `enterprise_kpi`. Set `FALKORDB_USERNAME` and `FALKORDB_PASSWORD` in `.env` when connecting to an authenticated instance; leave them blank for an unauthenticated local instance.

```bash
cd falkordb-ontology
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
docker compose up -d
```

Wait until the container is healthy (`docker compose ps`), then open [http://localhost:3000](http://localhost:3000) and select `enterprise_kpi`.

## Verify BigQuery read access

The read-only client uses Google Application Default Credentials (ADC) and retrieves at most five rows from `gcp-fs-looker-agentic.kg_demo_usecase.usecase_abc`. It does not export the data or write to BigQuery or FalkorDB.

```powershell
gcloud auth application-default login
.venv\Scripts\python.exe scripts\read_bigquery.py
```

Use `--limit` to change the number of rows displayed, for example `--limit 10`. The command reports table metadata, column names, and the retrieved rows. The account used by ADC must have permission to read this BigQuery table.

## Load the query-time ontology using the BigQuery pilot

The 100-row `data/bigquery_pilot.csv` seeds categorical vocabulary and query-measure definitions only from values actually present in those rows. Ontology sample nodes are excluded; the ontology supplies table/column schema and mapping rules. Monthly numeric values are not loaded as graph facts. The exporter maps BigQuery field names to the canonical CSV format; the CSV is ignored by Git because it contains source data.

The project installs the short commands from `pyproject.toml`. Install once, then activate the environment in each new PowerShell terminal:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\Activate.ps1
```

The `.env` file controls the input and ontology paths, BigQuery table identity, and FalkorDB graph. Relative file paths are resolved from the project root:

```dotenv
INPUT_DATA_FILE=data/bigquery_pilot.csv
ONTOLOGY_FILE=ontology/enterprise_kpi_ontology.csv
BIGQUERY_PROJECT=gcp-fs-looker-agentic
BIGQUERY_TABLE_NAME=usecase_abc
```

Load and validate without passing file paths:

```powershell
ontology-ingest
ontology-validate
```

`ontology-ingest` loads table/column schema and derives vocabulary and BigQuery measure nodes solely from the configured source CSV; it removes stale source-derived nodes that are absent from that CSV. Ontology sample nodes such as Revenue and LookML measure examples are not ingested. Numeric row values are not stored. `ontology-validate` checks exact source-derived node IDs and relationships against FalkorDB. Both commands target `FALKORDB_GRAPH` from `.env`.

To switch input data, update `INPUT_DATA_FILE` in `.env`; to switch the ontology, update `ONTOLOGY_FILE`. CLI flags can still override config for one-off runs. Do not use `--reset` for a normal load: it deletes every graph on the configured FalkorDB instance.

The loader upserts the stable ontology IDs. It does not load KPI fact rows. The current model excludes `ReportingPeriod`, `KPIObservation`, `RiskProfile`, and legacy `KPIMeasure` nodes.

## Direct BigQuery ingestion

The packaged `bigquery-falkordb-ingest` command streams BigQuery rows directly into the current ontology without creating a CSV. It upserts the table/column schema, distinct vocabulary, and KPI query definitions; numeric row values remain in BigQuery. The command defaults to all rows and supports bounded runs with `--limit 1000`. See [the direct-ingestion README](./bigquery_falkordb_ingestion/README.md) for installation, retries, failure replay, and configuration.

Install the project entry points with `.\.venv\Scripts\python.exe -m pip install -e .`, then run `bigquery-falkordb-ingest` or `bigquery-falkordb-ingest --limit 2000`.


## Historical fact-ingestion workflow (do not use for the current ontology)

The older `scripts/ingest_records.py` writes `KPIObservation` fact nodes. It is retained for the earlier experiment, but must not be used with the current query-time ontology because numeric facts are meant to stay in BigQuery.

## Commands

| Action | Command |
| --- | --- |
| Start | `docker compose up -d` |
| Stop | `docker compose stop` |
| Load ontology catalog from `.env` | `ontology-ingest` |
| Validate ontology catalog from `.env` | `ontology-validate` |
| Export configured BigQuery batch | `python scripts/export_bigquery_csv.py` |
| Direct BigQuery ingestion (all rows) | `bigquery-falkordb-ingest` |
| Show loader options | `ontology-ingest --help` |

`docker compose down` removes the container and keeps the named volume. `docker compose down -v` deletes that volume.
