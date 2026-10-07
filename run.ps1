# Boot the Planning App: installs deps, migrates, starts backend (:8000) + frontend (:3000).
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host "Planning App -- setup" -ForegroundColor Cyan

# ---- backend deps + migrate ----
Push-Location "$root\backend"
python -m pip install -q -r requirements.txt
python manage.py migrate --noinput | Out-Null
Pop-Location

# ---- pipeline deps (for rebuilding artifacts later) ----
Push-Location "$root\pipeline"
python -m pip install -q -r requirements.txt
Pop-Location

# ---- frontend deps ----
Push-Location "$root\frontend"
npm install --silent
Pop-Location

Write-Host "Starting backend (http://localhost:8000) and frontend (http://localhost:3000)..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; python manage.py runserver 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev"

Write-Host "Open http://localhost:3000" -ForegroundColor Cyan
