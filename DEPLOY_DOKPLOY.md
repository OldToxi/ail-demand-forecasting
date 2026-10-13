# Deploying to Dokploy (Docker Compose)

This repo runs as two services behind Dokploy:

| Service | Image build | Role |
| --- | --- | --- |
| `api`  | `backend/Dockerfile` (gunicorn + Django) | Serves `/api/forecast/*` from the shipped JSON artifact |
| `web`  | `frontend/Dockerfile` (Next.js standalone) | Serves the UI and proxies `/api/*` to `api` |

## Prerequisites

- The repo is pushed to a Git host Dokploy can read (GitHub/GitLab).
- The forecast artifact is committed (see [Refreshing the forecast artifact](#refreshing-the-forecast-artifact)):

  ```powershell
  git ls-files --error-unmatch data/outputs/forecast/ui/forecast_ui.json
  ```

## Create the Dokploy app

1. In Dokploy, create a new **Application** of type **Compose**.
2. Point it at this repo and select the compose file **`docker-compose.dokploy.yml`**.
3. Build context is the repo root (`planning-app/`); each service declares its own
   `dockerfile` path and `context: .` in the compose file.
4. Deploy. Dokploy builds both images and starts `api` (internal, port 8000) and
   `web` (published on port 3000).

## Domains

| Service | Internal address | Public domain |
| --- | --- | --- |
| `web` | `http://web:3000` | your-app.example.com (proxy to `web:3000`) |
| `api`  | `http://api:8000` | internal only — the browser never talks to it directly |

The `web` service rewrites `/api/*` to `http://api:8000/api/*` (via `API_DEST`), so only
the `web` domain needs to be public.

## Environment variables

- `api`:
  - `FORECAST_OUTPUTS_DIR` — where the shipped artifact lives (default in the image:
    `/app/data/outputs`). Normally leave as-is.
  - Optional: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`.
- `web`:
  - `API_DEST` — base URL the `/api` rewrite proxies to, e.g. `http://api:8000`.
    Next.js evaluates `rewrites()` at **build time** (it is baked into the routes
    manifest), so the value is taken from the `frontend/Dockerfile` build stage
    (`ARG API_DEST`, default `http://api:8000`). Override with a build arg if needed;
    the runtime `API_DEST` in the compose file is kept for parity.
  - `NEXT_TELEMETRY_DISABLED=1` (already set).

## Refreshing the forecast artifact

The pipeline writes `data/outputs/forecast/ui/forecast_ui.json` locally. After re-running
the pipeline, commit it so the next deploy ships the new data:

```powershell
# from the repo root (planning-app/)
python -m forecasting.run_forecast   # or your normal pipeline entry point

# force-add the shipped artifact (it lives under an ignored data/ tree)
git add -f data/outputs/forecast/ui
git commit -m "chore(forecast): refresh shipped forecast artifact"
git push
```

Dokploy redeploys on push (or trigger a manual redeploy). The `api` container reads the
artifact at startup with mtime-based caching, so the new JSON is picked up on redeploy.
