"""Stage 5 publish: turn the latest Stage-4 run + actuals into a single UI artifact the backend serves.

Writes: data/outputs/forecast/ui/forecast_ui.json  (+ planner_template.csv copied to ui/templates/)
No database. The UI reads this file via new read-only endpoints.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from . import config

def _r4(x):
    """Round to 4 decimal places, coercing NaN -> None for JSON serialisation."""
    if x is None:
        return None
    x = float(x)
    return None if x != x else round(x, 4)


CAVEATS = [
    "Demand forecast (based on sales) - saleproxies demand.",
    "2024-25 structural break (DQ-31): level shift, not seasonality.",
    "2025 Trade data regime unconfirmed (DQ-30): sensitivity flagged.",
    "2026-09 provisional; 2027 holiday dates provisional.",
    "LC months partly interpolated (lc_interpolated_flag).",
    "Evidence for months 7-12 is thin (few long-horizon origins).",
]


def _latest(sub: str, pointer: str | None = None):
    if pointer and (config.OUTPUTS_DIR / pointer).exists():
        rid = (config.OUTPUTS_DIR / pointer).read_text(encoding="utf-8").strip()
        return config.OUTPUTS_DIR / sub / f"run_{rid}"
    runs = sorted((config.OUTPUTS_DIR / sub).glob("run_*"))
    return runs[-1] if runs else None


def publish(stage4_run: str | None = None) -> dict:
    s4 = stage4_run
    if not s4:
        # consume only an "ok" stage4 manifest, never a raw "latest folder"
        base = config.OUTPUTS_DIR / "stage4"
        candidates = sorted([p for p in base.glob("run_*") if (p / "manifest.json").exists()])
        ok = [p for p in candidates if json.loads((p / "manifest.json").read_text(encoding="utf-8")).get("status") == "ok"]
        if not ok:
            raise SystemExit("no successful stage4 run (manifest status ok) found")
        s4 = ok[-1]
    else:
        from pathlib import Path
        s4 = Path(s4)
        m = json.loads((s4 / "manifest.json").read_text(encoding="utf-8"))
        if m.get("status") != "ok":
            raise SystemExit(f"stage4 run {s4} status={m.get('status')} - not consumable")
    ing = _latest("", "latest_run.txt")
    if s4 is None:
        raise SystemExit("no stage4 run found - run forecasting.stage4 first")

    fc = pd.read_parquet(s4 / "forecasts.parquet")
    sel = json.loads((s4 / "model_selection.json").read_text(encoding="utf-8"))
    try:
        extt = json.loads((s4 / "external_variable_tests.json").read_text(encoding="utf-8"))
    except Exception:
        extt = json.loads((s4 / "external_variable_tests.json").read_text(encoding="utf-8")) if (s4 / "external_variable_tests.json").exists() else []
    holdout = json.loads((s4 / "holdout.json").read_text(encoding="utf-8"))
    intervals = json.loads((s4 / "intervals.json").read_text(encoding="utf-8"))
    try:
        scenarios = json.loads((s4 / "scenarios.json").read_text(encoding="utf-8"))
    except Exception:
        scenarios = {}
    try:
        provisional = json.loads((s4 / "provisional_sensitivity.json").read_text(encoding="utf-8"))
    except Exception:
        provisional = {}
    try:
        metrics = pd.read_parquet(s4 / "backtest_metrics.parquet")
    except Exception:
        metrics = pd.DataFrame()

    # ── model leaderboard: mean across the 9 aggregate series, one row per model ──
    # Only models evaluated on every aggregate series are ranked (the lightgbm+external
    # variants are only backtested on 1-2 series and would dominate on a partial mean).
    leaderboard = []
    if not metrics.empty:
        n_series = metrics.series_id.nunique()
        for model, g in metrics.groupby("model"):
            if g.series_id.nunique() != n_series:
                continue
            row = {"model": model}
            for b in ["short", "medium", "long", "all"]:
                sub = g[g.horizon_bucket == b]
                row[f"wape_{b}"] = _r4(float(sub.wape.mean())) if len(sub) else None
            sub_all = g[g.horizon_bucket == "all"]
            row["bias_all"] = _r4(float(sub_all.bias.mean())) if len(sub_all) else None
            row["mase_all"] = _r4(float(sub_all.mase.mean())) if len(sub_all) else None
            leaderboard.append(row)
        leaderboard.sort(key=lambda e: (e["wape_all"] is None, e["wape_all"]))

    actuals = {}
    if ing is not None and (ing / "actuals.parquet").exists():
        a = pd.read_parquet(ing / "actuals.parquet")
        for sid, g in a.groupby("series_id"):
            actuals[sid] = [{"month": str(r.month), "actual_mt": round(float(r.actual_mt), 1),
                             "provisional": bool(r.provisional_flag), "constrained": bool(r.constraint_flag)}
                            for r in g.sort_values("month").itertuples()]

    series_meta = []
    ui_series = {}
    for sid, g in fc.groupby("series_id"):
        parts = sid.split("|")
        level = parts[1] if len(parts) > 1 else ""
        channel = parts[2] if len(parts) > 2 and level == "channel" else (parts[2] if len(parts) > 2 and level in ("zone", "account") else "")
        zone = parts[3] if len(parts) > 3 and level == "zone" else ""
        label = {"company": "Company total", "sbu": "SBU external total", "channel": f"Channel: {channel}",
                 "zone": f"Zone: {zone}", "account": f"Account: {parts[-1]}"}.get(level, sid)
        series_meta.append({"series_id": sid, "level": level, "channel": channel, "zone": zone, "label": label})
        base = g[g.scenario == "base"].sort_values("horizon")
        scens = {}
        for sc, gg in g.groupby("scenario"):
            scens[sc] = [{"month": r.month, "horizon": int(r.horizon), "point": r.point_forecast_mt,
                          "q025": r.q025, "q10": r.q10, "q50": r.q50, "q90": r.q90, "q975": r.q975}
                         for r in gg.sort_values("horizon").itertuples()]
        mm = metrics[(metrics.series_id == sid) & (metrics.model == sel.get(sid, {}).get("short", {}).get("best_model", ""))]
        acc = {b: {"wape": float(mm[mm.horizon_bucket == b].wape.iloc[0])} if (mm.horizon_bucket == b).any() else None
               for b in ["short", "medium", "long", "all"]}
        ui_series[sid] = {"series_id": sid, "actuals": actuals.get(sid, []), "forecasts": scens,
                          "selection": sel.get(sid, {}), "accuracy": acc,
                          "external_tested": [t for t in extt if t.get("series_id") == sid]}

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": s4.name.replace("run_", ""),
        "title": "AIL demand forecast",
        "label": "Demand forecast (based on sales)",
        "horizon_months": int(fc.horizon.max()),
        "scenarios": sorted(fc.scenario.unique().tolist()),
        "caveats": CAVEATS,
        "holdout": holdout,
        "series": series_meta,
        "detail": ui_series,
        "leaderboard": leaderboard,
        "champion": leaderboard[0]["model"] if leaderboard else None,
        "provisional": provisional.get("per_series", {}),
        "level_tracking_weight": provisional.get("level_tracking_weight", {}),
        "scenario_notes": scenarios.get("notes", []),
        "sensitivity_selected": (json.loads((s4 / "sensitivity_selected.json").read_text(encoding="utf-8"))
                                 if (s4 / "sensitivity_selected.json").exists() else {}),
    }
    acct_p = s4 / "top_accounts.json"
    if acct_p.exists():
        acct = json.loads(acct_p.read_text(encoding="utf-8"))
        payload["accounts_summary"] = acct
    out = config.OUTPUTS_DIR / "ui"
    out.mkdir(parents=True, exist_ok=True)
    (out / "forecast_ui.json").write_text(json.dumps(payload, default=str), encoding="utf-8")
    print(f"published {len(series_meta)} series -> {out/'forecast_ui.json'}")
    return payload


if __name__ == "__main__":
    publish()
