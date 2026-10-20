# KPI Insights (ADK + MCP Toolbox + BigQuery)

- `toolbox/` – MCP Toolbox for Databases config (BigQuery tools)
- `backend/` – FastAPI + Google ADK summary and visualization agents
- `frontend/` – React + Tailwind UI
- `data/` – `kpi.csv`, `schema.json`

## Run locally (Windows PowerShell)

Run the following steps from separate PowerShell terminals. Replace the project, dataset, and table values if you are connecting to a different BigQuery table.

### 1. Authenticate with Google Cloud

Run once and complete the browser consent flow. The account needs access to the BigQuery table and Vertex AI in the configured project.

```powershell
gcloud auth application-default login --project=gcp-fs-looker-agentic
```

### 2. Start MCP Toolbox

If `toolbox\toolbox.exe` is not present, download the official Windows amd64 release:

```powershell
Set-Location "C:\path\to\Semantic_Layer-IN-GCP"
Invoke-WebRequest `
  -Uri "https://storage.googleapis.com/mcp-toolbox-for-databases/v1.14.0/windows/amd64/toolbox.exe" `
  -OutFile ".\toolbox\toolbox.exe"
```

Then start Toolbox in this terminal:

```powershell
Set-Location "C:\path\to\Semantic_Layer-IN-GCP"
$env:GCP_PROJECT = "gcp-fs-looker-agentic"
$env:BQ_DATASET = "kg_demo_usecase"
$env:BQ_TABLE = "usecase_abc"
./toolbox/toolbox.exe --config ./toolbox/tools.yaml
```

Keep this terminal open while using the application.

### 3. Start the backend

In a second terminal:

```powershell
Set-Location "C:\path\to\Semantic_Layer-IN-GCP\backend"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Keep this terminal open too. The backend reads settings from `backend\.env`. Create it from `.env.example` if needed, then set `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, and `TOOLBOX_URL` for your environment.

### 4. Start the frontend

In a third terminal:

```powershell
Set-Location "C:\path\to\Semantic_Layer-IN-GCP\frontend"
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

Open http://127.0.0.1:5173/ in your browser. The API health check is http://127.0.0.1:8000/health.

To load the bundled sample CSV into your own BigQuery table, use `bq load --source_format=CSV --skip_leading_rows=1 DATASET.kpi data/kpi.csv data/schema.json` from the repository root.

Endpoints: `POST /api/summary`, `POST /api/visualize` with `{"question": "..."}`.
Looker later: add a Looker source and tools to `tools.yaml`; no code changes needed.
