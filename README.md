# Planning App — AIL Demand Forecast

A standalone demand-forecasting app for Anwar Ispat (AIL) steel. It reads one consolidated sales
source and serves a 12-month demand forecast on the `/ail-forecast` page, driven by a
**raw-data → artifact → serve** pipeline.

```
planning-app/
  backend/      Django service — serves the AIL forecast page from data/outputs/forecast/ (no database tables)
  frontend/     Next.js app — the /ail-forecast page
  forecasting/  Python package — the data pipeline (raw data -> data/outputs/forecast/)
  data/
    raw/        <- the AIL consolidated source (see data/raw/README.md)
    outputs/
      forecast/ <- generated forecasting artifacts (seeded so the app runs immediately)
```

## The page

| Page | Route | API | Artifact(s) |
|------|-------|-----|-------------|
| AIL Forecast | `/ail-forecast` | `/api/forecast/ui`, `/api/forecast/template`, `/api/forecast/planner` | `data/outputs/forecast/ui/forecast_ui.json` |

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

The pipeline is the `forecasting` Python package. It turns the single AIL source into the artifacts
the page reads, and runs in its pinned venv:

```powershell
cd planning-app
.\.venv-forecast-pinned\Scripts\python.exe -m forecasting.run_forecast
# stages: ingest -> backtest(run id) -> stage4(explicit backtest run id) -> publish -> planner
```

It reads the single source of truth `data/raw/AIL-Total_Monthly-2023 to 2026.xlsx` (sheet `Data`,
split into Corporate / Intercompany / Trade by `Channel`) and publishes
`data/outputs/forecast/ui/forecast_ui.json`.

### Artifact layout (`outputs/forecast/`)

```
outputs/forecast/
  run_<id>/             ingest artifacts (actuals, series, DQ gate, feature registry, run metadata)
  backtest/run_<id>/    backtest leaderboard + per-origin metrics
  stage4/run_<id>/      selection, scenarios, intervals, holdout, top accounts
  ui/forecast_ui.json   the payload the /ail-forecast page reads
  ui/planner_adjustments.json  published planner adjustments (statistical vs adjusted)
  zeroshot/             zero-shot (Chronos-Bolt) predictions + series
  external/             ail_rainfall_monthly.csv (external feature)
  state_check/          state-check catalog
```

See `docs/forecasting/README.md` for the full pipeline, configuration and results.

## Notes

- The backend reads files on every request (mtime-cached), so after a pipeline run the page picks
  up new artifacts without a restart.
