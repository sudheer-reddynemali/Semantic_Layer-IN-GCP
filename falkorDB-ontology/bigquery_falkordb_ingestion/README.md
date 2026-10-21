# Direct BigQuery to FalkorDB ingestion

This self-contained package streams canonical batches from BigQuery and upserts
the latest query-time ontology into FalkorDB. It loads the table/column schema,
then derives reusable vocabulary and KPI query definitions from source rows.
It does not store row-level facts or KPI amounts in the graph.

The ontology CSV is maintained in `ontology/enterprise_kpi_ontology.csv`.
Mappings and the current `YTD_ACTUAL` KPI are configured in `config.json`.
Add a KPI by adding a definition there, mapping its BigQuery field to a
canonical field, and providing the corresponding FalkorDB column and measure
properties. Its BigQuery value column is checked against the source schema but
is not selected or stored in the graph. If that field is not already in the
ontology, update the ontology CSV as well. Keep the existing KPI ID template
stable when adding another KPI; give each additional KPI a distinct
`measure_id_template` (for example, `BQMEASURE:{metric}_{kpi}`). New dimensions
can likewise be added through `vocabulary_mappings`.

## Install and configure

From the repository root, install the project so the `pyproject.toml` command
is available:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
```

Copy `.env.example` to `.env` inside this folder and set the FalkorDB
connection values. BigQuery uses Google Application Default Credentials:

```powershell
gcloud auth application-default login
```

The root project `.env` is also read for existing BigQuery and FalkorDB
settings. Environment variables already set in the shell take precedence.

## Run

```powershell
bigquery-falkordb-ingest
```

The default reads all rows. To bound the source rows, pass `--limit`; for
example:

```powershell
bigquery-falkordb-ingest --limit 1000
bigquery-falkordb-ingest --limit 2000 --batch-size 250
```

During ingestion, the terminal updates a progress line with the number of rows
processed, percentage complete, succeeded, failed, and pending. The expected
row count comes from BigQuery table metadata and is capped by `--limit` when
provided.

`--batch-size` controls the number of source rows canonicalized at a time
(default: `BIGQUERY_BATCH_SIZE`, or 100). `--retry-limit` controls retries
after the initial row attempt (default: `BIGQUERY_RETRY_LIMIT`, or 3).
Rows that still fail are appended to `failed_records/failed_rows.jsonl`.
Replay them after resolving the cause with:

```powershell
bigquery-falkordb-ingest --replay-failures
```

An alternate failure file can be supplied to `--replay-failures`.
Successfully replayed rows are removed from that file; any failures remain
available for another replay.

The loader creates/ensures identity indexes and unique constraints before
writing. Re-running it is safe: node identities derive from normalized
business terms, and both nodes and relationships use `MERGE`.
