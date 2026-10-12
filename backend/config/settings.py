"""Planning App backend settings.

Minimal Django service that serves the AIL forecast from precomputed artifacts in
`data/outputs/forecast/` via the following endpoints:

    /api/forecast/ui        -> UI configuration for the forecast
    /api/forecast/template  -> planner upload template
    /api/forecast/planner   -> planner adjustments
    /api/health             -> service health check

No models, no database tables needed (sqlite stays only because Django wants a DB configured).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # planning-app/backend
APP_DIR = BASE_DIR.parent                                   # planning-app
PROJECT_ROOT = APP_DIR.parent                               # repo root

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-change-in-prod")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [], "APP_DIRS": True,
    "OPTIONS": {"context_processors": []},
}]
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Dhaka"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# where the pipeline writes its artifacts (the API serves from here)
DATA_DIR = Path(os.environ.get("FORECAST_OUTPUTS_DIR", APP_DIR / "data" / "outputs"))
