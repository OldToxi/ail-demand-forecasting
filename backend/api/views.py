"""Planning App API — serves the AIL demand-forecasting page from precomputed artifacts.

    GET /api/health            service health
    GET /api/forecast/ui        AIL demand forecast UI payload
    GET /api/forecast/template  planner-adjustment CSV template (download)
    GET /api/forecast/planner   current planner adjustments (statistical vs adjusted)

Every endpoint reads a file the pipeline wrote under `DATA_DIR` (mtime-cached, so re-running
the pipeline is picked up without a restart). No database involved.
"""
import json

from django.conf import settings
from django.http import JsonResponse

_DATA = settings.DATA_DIR


def _json(path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _not_built(what, script):
    return JsonResponse(
        {"detail": f"{what} not built — run: python -m forecasting.run_forecast"},
        status=404,
    )


def health(request):
    return JsonResponse({"status": "ok", "data_dir": str(_DATA)})


# ────────────────────────────────────────────────────────────────
# AIL demand forecasting (read-only)
# ────────────────────────────────────────────────────────────────
def forecast_ui(request):
    d = _json(_DATA / "forecast" / "ui" / "forecast_ui.json")
    if d is None:
        return _not_built("AIL forecast", "forecasting.stage4 + forecasting.publish")
    return JsonResponse(d)


def forecast_template(request):
    """Serve the planner-adjustment CSV template for download."""
    from django.http import HttpResponse
    p = settings.BASE_DIR.parent / "forecasting" / "templates" / "planner_adjustments_template.csv"
    if not p.exists():
        return _not_built("planner template", "create forecasting/templates/planner_adjustments_template.csv")
    return HttpResponse(p.read_text(encoding="utf-8"), content_type="text/csv",
                        headers={"Content-Disposition": "attachment; filename=planner_adjustments_template.csv"})


def forecast_planner_list(request):
    """Current planner adjustments (statistical vs adjusted), if published."""
    d = _json(_DATA / "forecast" / "ui" / "planner_adjustments.json")
    return JsonResponse(d or {"adjustments": []})
