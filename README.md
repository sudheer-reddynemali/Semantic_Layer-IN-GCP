# KPI Insights (ADK + MCP Toolbox + BigQuery)

- `toolbox/` – MCP Toolbox for Databases config (BigQuery tools)
- `backend/` – FastAPI + Google ADK summary and visualization agents
- `frontend/` – React + Tailwind UI
- `data/` – `kpi.csv`, `schema.json`

## Setup
1. Load data into BigQuery:
   `bq load --source_format=CSV --skip_leading_rows=1 DATASET.kpi data/kpi.csv data/schema.json`
2. `gcloud auth application-default login`
3. Toolbox (install from https://github.com/googleapis/genai-toolbox), with env vars `GCP_PROJECT`, `BQ_DATASET`, `BQ_TABLE` set:
   `toolbox --tools-file toolbox/tools.yaml`
4. Backend: `cd backend; cp .env.example .env; pip install -r requirements.txt; uvicorn app.main:app --reload`
5. Frontend: `cd frontend; npm install; npm run dev` (http://localhost:5173)

Endpoints: `POST /api/summary`, `POST /api/visualize` with `{"question": "..."}`.
Looker later: add a Looker source and tools to `tools.yaml`; no code changes needed.
