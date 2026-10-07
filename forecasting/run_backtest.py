"""Stage 2/3 runner: rolling-origin backtest across the model pool for the aggregate series.

Usage: python -m forecasting.run_backtest [--models a,b] [--levels company,sbu,channel,zone]
Writes data/outputs/forecast/backtest/run_<id>/{metrics.parquet,timings.json,summary.txt}.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import pandas as pd

from . import backtest, config, external
from .adapters import load_all
from .series import build_series


def months(a: str, b: str) -> list[pd.Period]:
    return list(pd.period_range(a, b, freq="M"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="")
    ap.add_argument("--levels", default="company,sbu,channel,zone")
    ap.add_argument("--sbus", default="AIL")
    args = ap.parse_args()

    cfg = config.load_config()
    reg = config.load_sbus()
    ext_reg = config.load_external_registry()
    models_cfg = config._load("models.yaml")["models"]
    levels = set(args.levels.split(","))

    cal_cols = [v["feature_key"] for v in ext_reg["variables"]
                if v["type"] == "known_in_advance" and v.get("transform") != "annual_level"]

    ext_path = config.resolve(ext_reg["monthly_file"])
    from . import external
    ext_monthly = external.load_monthly(ext_path) if ext_path.exists() else None

    origins = months(cfg["backtest_origins"][0], cfg["backtest_origins"][1])
    cut = pd.Period("2026-03", "M")
    horizon = cfg["horizon_months"]

    wanted = set(args.models.split(",")) if args.models else None
    models = [m for m in models_cfg if m.get("enabled", True) and not m.get("accounts_only")
              and (wanted is None or m["name"] in wanted)]

    all_metrics, timings, notes = [], {}, []
    for sbu_id in args.sbus.split(","):
        sbu = next(s for s in reg["sbus"] if s["sbu_id"] == sbu_id)
        sbu["_hierarchy"] = reg["hierarchy"]
        frames = load_all(sbu, config.REPO_ROOT)
        series = build_series(sbu, config.REPO_ROOT)
        agg = series[series.level.isin(levels)]
        idx = ext_monthly.index if ext_monthly is not None else pd.PeriodIndex(sorted(series["month"].unique()), freq="M")
        exog_full = backtest.build_exog(ext_monthly, ext_reg, sbu.get("segment_code", "ALL"), idx, cal_cols)

        for sid, g in agg.groupby("series_id"):
            y = pd.Series(g.sort_values("month")["y"].values, index=pd.PeriodIndex(sorted(g["month"]), freq="M"))
            exog_s = exog_full.join(external.intervention_frame(sid, cfg, exog_full.index))
            scale = backtest.seasonal_naive_mae(y, origins, horizon)
            for mc in models:
                name = mc["name"]
                rows, secs = backtest.backtest_series(y, name, mc.get("params", {}), exog_s, origins, horizon, cut)
                timings[name] = round(timings.get(name, 0.0) + secs, 1)
                if rows and "skipped" in rows[0]:
                    notes.append(f"{sid} {name}: {rows[0]['skipped']}")
                    continue
                summ = backtest.summarize(rows, scale)
                for bucket, m in summ.items():
                    m.update({"sbu": sbu_id, "series_id": sid, "model": name, "horizon_bucket": bucket})
                    all_metrics.append(m)
                print(f"  {sid:32s} {name:14s} wape_all={summ.get('all',{}).get('wape')} ({secs:.1f}s)")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    d = config.OUTPUTS_DIR / "backtest" / f"run_{run_id}"
    d.mkdir(parents=True, exist_ok=True)
    metrics = pd.DataFrame(all_metrics)
    metrics.to_parquet(d / "metrics.parquet", index=False)
    (d / "timings.json").write_text(json.dumps(timings, indent=2), encoding="utf-8")
    (d / "notes.json").write_text(json.dumps(notes, indent=2), encoding="utf-8")
    print("\nrun", run_id, "->", d)
    print("timings:", timings)
    print("notes:", notes[:5])
    # quick leaderboard (overall WAPE, aggregate series only)
    if not metrics.empty:
        lb = (metrics[metrics.horizon_bucket == "all"]
              .groupby("model")["wape"].mean().sort_values().round(4))
        print("\nmean overall WAPE by model:\n", lb.to_string())


if __name__ == "__main__":
    main()
