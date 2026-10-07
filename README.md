# Planning App — Demand Forecast · Demand Planning · Production Planning

A focused, standalone system built from the Akij sales-forecasting codebase, containing **only the
three planning tabs** and a **raw-data → artifact → serve** pipeline.

```
planning-app/
  backend/     Django service — serves the 3 tabs from data/outputs/ (no database tables)
  frontend/    Next.js app — the 3 tabs + landing page
  pipeline/    data pipeline: raw data -> data/outputs/ (the artifacts the backend serves)
  data/
    raw/       <- drop source files here (see data/raw/README.md)
    interim/   <- upstream parquet releases (final_quantity_forecast, item_monthly_panel)
    outputs/   <- generated artifacts (seeded so the app runs immediately)
```

## The three tabs

| Tab | Route | API | Artifact(s) |
|-----|-------|-----|-------------|
| Demand Forecast | `/demand-forecast-planning` | `/api/demand-planning/demand-forecast-v2`, `/bakeoff` | `demand_forecast_v2.json`, `bakeoff_leaderboard.json` |
| Demand Planning | `/demand-planning` | `/api/demand-planning/market-target` | `market_target.json` |
| Production Planning | `/production` | `/api/production/units`, `/api/production/materials?unit=` | `production_material_forecast.csv` (+ meta/history/by_type) |

The frontend proxies `/api` → `http://127.0.0.1:8000` (see `frontend/next.config.ts`), so both run
on one origin with no CORS.

## Quick start (Windows PowerShell)

```powershell
cd planning-app
.\run.ps1
```

Then open http://localhost:3000 (backend on http://localhost:8000, try `/api/health`).

### Manual

```powershell
# backend
cd backend
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 8000

# frontend (new terminal)
cd frontend
npm install
npm run dev
```

## The pipeline

`pipeline/run_pipeline.py` turns raw data into the artifacts the tabs read.

```powershell
cd planning-app
python -m pip install -r pipeline/requirements.txt

python pipeline/run_pipeline.py --list        # show required inputs vs present
python pipeline/run_pipeline.py               # build every stage whose inputs exist
python pipeline/run_pipeline.py --stage production
```

Stages run in dependency order: `production` → `demand-forecast` → `demand-planning`.
Steps whose raw inputs are missing are skipped with a clear message, so the app keeps serving the
last good artifacts.

### Raw inputs

Drop files into `data/raw/` — see `data/raw/README.md` for the full list and expected columns.
The Production stage additionally needs the upstream parquet release in `data/interim/`
(`final_quantity_forecast.parquet`, `item_monthly_panel.parquet`).

## Notes

- This is the requested slice of `webapp/` — the other pages (dashboard, explore, review, items,
  supply-chain, login, bake-off) are intentionally **not** included.
- The backend reads files on every request (mtime-cached), so after a pipeline run the tabs pick
  up new artifacts without a restart.
