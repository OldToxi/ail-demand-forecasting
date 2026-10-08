"""Rolling-origin backtest runner. Returns an explicit run directory with a manifest; stage 4 consumes
that run id (never "the latest folder").

Usage: python -m forecasting.run_backtest [--models ...] [--levels ...] [--run-id ID]
"""
from __future__ import annotations

import argparse
import json

import pandas as pd

from . import backtest, config, external, run_manifest
from .adapters import load_all
from .series import build_series


def run(models: list | None = None, levels: str = "company,sbu,channel,zone", sbus: str = "AIL",
        run_id: str | None = None) -> str:
    cfg = config.load_config(); reg = config.load_sbus(); ext_reg = config.load_external_registry()
    models_cfg = config._load("models.yaml")["models"]
    lv = set(levels.split(","))
    cal_cols = [v["feature_key"] for v in ext_reg["variables"]
                if v["type"] == "known_in_advance" and v.get("transform") != "annual_level"]
    ext = external.augment_with_files(external.load_monthly(config.resolve(ext_reg["monthly_file"])),
                                      ext_reg, config.REPO_ROOT)
    base_exog = backtest.build_exog(ext, ext_reg, "STEEL", ext.index, cal_cols)
    origins = list(pd.period_range(cfg["backtest_origins"][0], cfg["backtest_origins"][1], freq="M"))
    cut = pd.Period("2026-03", "M"); H = cfg["horizon_months"]

    run_id = run_id or run_manifest.new_run_id()
    d = config.OUTPUTS_DIR / "backtest" / f"run_{run_id}"
    d.mkdir(parents=True, exist_ok=True)
    all_metrics, timings, notes = [], {}, []
    from .models import statistical
    statistical.reset_clip_log()
    try:
        for sbu_id in sbus.split(","):
            sbu = next(s for s in reg["sbus"] if s["sbu_id"] == sbu_id); sbu["_hierarchy"] = reg["hierarchy"]
            series = build_series(sbu, config.REPO_ROOT)
            agg = series[series.level.isin(lv)]
            for sid, g in agg.groupby("series_id"):
                y = pd.Series(g.sort_values("month")["y"].values, index=pd.PeriodIndex(sorted(g["month"]), freq="M"))
                exog_s = base_exog.join(external.intervention_frame(sid, cfg, base_exog.index))
                scale = backtest.seasonal_naive_mae(y, origins, H)
                for mc in models_cfg:
                    if not mc.get("enabled", True) or mc.get("accounts_only"):
                        continue
                    if models is not None and mc["name"] not in models:
                        continue
                    rows, secs = backtest.backtest_series(y, mc["name"], mc.get("params", {}), exog_s,
                                                          origins, H, cut, series_id=sid)
                    timings[mc["name"]] = round(timings.get(mc["name"], 0) + secs, 1)
                    if rows and "skipped" in rows[0]:
                        notes.append(f"{sid} {mc['name']}: {rows[0]['skipped']}"); continue
                    summ = backtest.summarize(rows, scale)
                    for b, m in summ.items():
                        m.update({"sbu": sbu_id, "series_id": sid, "model": mc["name"], "horizon_bucket": b})
                        all_metrics.append(m)
        metrics = pd.DataFrame(all_metrics)
        metrics.to_parquet(d / "metrics.parquet", index=False)
        (d / "timings.json").write_text(json.dumps(timings, indent=2), encoding="utf-8")
        (d / "notes.json").write_text(json.dumps(notes, indent=2), encoding="utf-8")
        from .models import statistical
        (d / "clipping.json").write_text(json.dumps(statistical.CLIP_LOG, indent=2), encoding="utf-8")
        run_manifest.write_manifest(d, "backtest", "ok",
                                    [d / "metrics.parquet", d / "timings.json", d / "notes.json", d / "clipping.json"],
                                    {"origins": [str(o) for o in origins], "cut": str(cut),
                                     "n_rows": int(len(metrics)), "n_clip_events": len(statistical.CLIP_LOG)})
        print("backtest run:", d)
        return str(d)
    except Exception as e:
        run_manifest.write_manifest(d, "backtest", "failed", [], {"error": f"{type(e).__name__}: {e}"})
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="")
    ap.add_argument("--levels", default="company,sbu,channel,zone")
    ap.add_argument("--sbus", default="AIL")
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args()
    run(models=set(a.models.split(",")) if a.models else None, levels=a.levels, sbus=a.sbus, run_id=a.run_id)


if __name__ == "__main__":
    main()
