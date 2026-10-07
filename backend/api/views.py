"""Planning App API — serves the three planning tabs from precomputed artifacts.

    GET /api/demand-planning/demand-forecast-v2   demand forecast (national, materials, districts, supply)
    GET /api/demand-planning/bakeoff              model bake-off leaderboard
    GET /api/demand-planning/market-target        top-down CAGR demand target
    GET /api/production/units                     units with a production plan
    GET /api/production/materials?unit=<id>       BOM-exploded material forecast

Every endpoint reads a file the pipeline wrote under `DATA_DIR` (mtime-cached, so re-running
the pipeline is picked up without a restart). No database involved.
"""
import json

import pandas as pd
from django.conf import settings
from django.http import JsonResponse

_DATA = settings.DATA_DIR

_CACHE = {}
_FP_CACHE = {}


def _json(path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _not_built(what, script):
    return JsonResponse(
        {"detail": f"{what} not built — run: python pipeline/run_pipeline.py"},
        status=404,
    )


# ────────────────────────────────────────────────────────────────
# Demand Forecast tab
# ────────────────────────────────────────────────────────────────
def demand_forecast_v2(request):
    d = _json(_DATA / "demand_planning" / "demand_forecast_v2.json")
    if d is None:
        return _not_built("demand forecast v2", "build_demand_forecast_v2.py")
    return JsonResponse(d)


def bakeoff_leaderboard(request):
    d = _json(_DATA / "demand_planning" / "bakeoff_leaderboard.json")
    if d is None:
        return _not_built("bakeoff", "bakeoff.py")
    return JsonResponse(d)


# ────────────────────────────────────────────────────────────────
# Demand Planning tab
# ────────────────────────────────────────────────────────────────
def market_target(request):
    d = _json(_DATA / "demand_planning" / "market_target.json")
    if d is None:
        return _not_built("market target", "build_market_target.py")
    return JsonResponse(d)


# ────────────────────────────────────────────────────────────────
# Production Planning tab
# ────────────────────────────────────────────────────────────────
def _demand_staleness(meta):
    """Has the live demand forecast changed since this production plan was built?"""
    fc_path = _DATA / "interim" / "final_quantity_forecast.parquet"
    if not fc_path.exists() or not meta.get("source_forecast_fingerprint"):
        return None, ""
    mt = fc_path.stat().st_mtime
    if _FP_CACHE.get("mtime") != mt:
        try:
            import hashlib
            fc = pd.read_parquet(fc_path)
            c = fc[fc.Unit_ID == 4].sort_values(["item_key", "month"])
            payload = c[["item_key", "month", "P10", "P50", "P90"]].round(3).to_csv(index=False)
            _FP_CACHE.clear()
            _FP_CACHE["mtime"] = mt
            _FP_CACHE["fp"] = hashlib.sha1(payload.encode()).hexdigest()[:16]
        except Exception:
            return None, ""
    live = _FP_CACHE.get("fp")
    if live and live != meta["source_forecast_fingerprint"]:
        return True, ("The demand forecast has changed since this production plan was built. "
                      "Re-run the pipeline to re-couple them.")
    return False, ""


def _load_production():
    d = _DATA / "data"
    mat_p, type_p, meta_p, hist_p = (
        d / "production_material_forecast.csv",
        d / "production_material_by_type.csv",
        d / "production_plan_meta.json",
        d / "production_material_history.csv",
    )
    if not mat_p.exists():
        return None
    mt = lambda p: p.stat().st_mtime if p.exists() else 0
    stamp = (mat_p.stat().st_mtime, mt(type_p), mt(meta_p), mt(hist_p))
    if _CACHE.get("stamp") != stamp:
        _CACHE.clear()
        _CACHE["stamp"] = stamp
        _CACHE["mat"] = pd.read_csv(mat_p)
        _CACHE["by_type"] = pd.read_csv(type_p) if type_p.exists() else pd.DataFrame()
        _CACHE["meta"] = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
        _CACHE["hist"] = pd.read_csv(hist_p) if hist_p.exists() else pd.DataFrame()
    return _CACHE


_CAT_ORDER = {"clinker": 0, "raw_material": 1, "packaging": 2}


def production_units(request):
    c = _load_production()
    if not c:
        return JsonResponse({"units": []})
    rows = (c["mat"][["unit_id", "unit_name"]].drop_duplicates()
            .sort_values("unit_id").to_dict("records"))
    return JsonResponse({"units": [{"unit_id": int(r["unit_id"]), "name": r["unit_name"]} for r in rows]})


def production_materials(request):
    c = _load_production()
    if not c:
        return _not_built("production plan", "build_production_plan.py")
    mat, by_type, meta = c["mat"], c["by_type"], c["meta"]

    unit = request.GET.get("unit")
    if unit:
        mat = mat[mat.unit_id == int(unit)]
    if mat.empty:
        return JsonResponse({"detail": "no production plan for this unit", "units_available":
                             sorted(int(u) for u in c["mat"].unit_id.unique())}, status=404)

    type_map = {}
    if not by_type.empty:
        for m, g in by_type.groupby("material"):
            type_map[m] = [{"cement_type": r.cement_type, "annual_p50": round(float(r.annual_p50), 1)}
                           for r in g.sort_values("annual_p50", ascending=False).itertuples()]

    annual_meta = meta.get("annual", {})
    has_wc = "p10_wc" in mat.columns
    hist = c.get("hist", pd.DataFrame())
    hist_map = {}
    if not hist.empty:
        for m, g in hist.groupby("material"):
            hist_map[m] = [{"month": r.month, "actual": round(float(r.actual), 1)}
                           for r in g.sort_values("month").itertuples()]

    out = []
    for (material, category, uom), g in mat.groupby(["material", "category", "uom"]):
        g = g.sort_values("month")
        a = annual_meta.get(material, {})
        annual_p50 = a.get("p50", round(float(g.p50.sum()), 1))
        row = {
            "material": material, "category": category, "uom": uom,
            "annual_p10": a.get("p10", round(float(g.p10.sum()), 1)),
            "annual_p50": annual_p50,
            "annual_p90": a.get("p90", round(float(g.p90.sum()), 1)),
            "annual_p10_wc": a.get("p10_wc", round(float(g.p10_wc.sum()), 1) if has_wc else None),
            "annual_p90_wc": a.get("p90_wc", round(float(g.p90_wc.sum()), 1) if has_wc else None),
            "series": [{"month": r.month, "p10": round(float(r.p10), 1),
                        "p50": round(float(r.p50), 1), "p90": round(float(r.p90), 1),
                        "p10_wc": round(float(r.p10_wc), 1) if has_wc else None,
                        "p90_wc": round(float(r.p90_wc), 1) if has_wc else None}
                       for r in g.itertuples()],
            "history": hist_map.get(material, []),
            "by_type": type_map.get(material, []),
        }
        out.append(row)
    out.sort(key=lambda m: (_CAT_ORDER.get(m["category"], 9), -m["annual_p50"]))
    stale, stale_reason = _demand_staleness(meta)

    return JsonResponse({
        "unit": int(unit) if unit else meta.get("unit_id"),
        "unit_name": meta.get("unit_name"),
        "months": meta.get("months", sorted(mat.month.unique())),
        "cement_demand_tons_p50": meta.get("cement_demand_tons_p50"),
        "band_rho": meta.get("band_rho"),
        "built_at": meta.get("built_at"),
        "stale": stale, "stale_reason": stale_reason,
        "note": meta.get("note"),
        "materials": out,
    })


def health(request):
    return JsonResponse({"status": "ok", "data_dir": str(_DATA)})
