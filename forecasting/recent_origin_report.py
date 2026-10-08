"""Recent-origin vs full-origin selection report (P1.6, report only - no automatic switch).

For every aggregate series: compare the full-origin selection (the stage-4 base forecast) with an
alternative forecast that uses the best model under origins 2025-07..2026-02. Writes PNGs and a CSV.
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from . import backtest, config, external
from .adapters import load_all
from .models import build_model
from .series import build_series

AG = {"company", "sbu", "channel", "zone"}


def _latest_ok_stage4():
    ds = [d for d in sorted(glob.glob(str(config.OUTPUTS_DIR / "stage4" / "run_*")))
          if os.path.exists(os.path.join(d, "manifest.json"))
          and json.loads(open(os.path.join(d, "manifest.json"), encoding="utf-8").read()).get("status") == "ok"]
    return ds[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage4", default=None)
    a = ap.parse_args()
    s4 = a.stage4 or _latest_ok_stage4()
    cfg = config.load_config(); reg = config.load_sbus(); er = config.load_external_registry()
    ext = external.augment_with_files(external.load_monthly(config.resolve(er["monthly_file"])), er, config.REPO_ROOT)
    cal = [v["feature_key"] for v in er["variables"] if v["type"] == "known_in_advance" and v.get("transform") != "annual_level"]
    base_exog = backtest.build_exog(ext, er, "STEEL", ext.index, cal)
    extra = [c for c in ["disruption_days_full", "disruption_days_partial", "flood_major_flag"] if c in ext.columns]
    train_exog = base_exog.join(ext[extra].reindex(base_exog.index).fillna(0.0))
    sbu = next(s for s in reg["sbus"] if s["sbu_id"] == "AIL"); sbu["_hierarchy"] = reg["hierarchy"]
    series = build_series(sbu, config.REPO_ROOT)
    agg = series[series.level.isin(AG)]
    fut = pd.period_range(cfg["forecast_start"], periods=cfg["horizon_months"], freq="M")

    recent = pd.read_json(os.path.join(s4, "recent_origin_wape.json"))
    fc = pd.read_parquet(os.path.join(s4, "forecasts.parquet"))
    sel = json.loads(open(os.path.join(s4, "model_selection.json"), encoding="utf-8").read())
    outdir = config.OUTPUTS_DIR / "diagnostics"; os.makedirs(outdir, exist_ok=True)
    rows = []
    for sid, g in agg.groupby("series_id"):
        y = pd.Series(g.sort_values("month")["y"].values, index=pd.PeriodIndex(sorted(g["month"]), freq="M"))
        exog_s = train_exog.join(external.intervention_frame(sid, cfg, train_exog.index))
        rb = recent[recent.series_id == sid].sort_values("wape_recent")
        recent_best = rb.iloc[0]["model"] if len(rb) else "ets"
        base_sel = ",".join(sel.get(sid, {}).get("short", {}).get("selected_models", []))
        def fit_model(name):
            m = build_model(name, {}); sup = m.supports_exog
            m.fit(y, exog_s.reindex(y.index) if sup else None)
            return m.predict(len(fut), exog_s.reindex(fut) if sup else None).point
        try:
            alt = fit_model(recent_best)
        except Exception:
            alt = np.repeat(y.values[-1], len(fut))
        cur = fc[(fc.series_id == sid) & (fc.scenario == "base")].sort_values("horizon").point_forecast_mt.values
        fig, ax = plt.subplots(figsize=(10, 3.6))
        ax.plot(y.index.astype(str), y.values, "k-", lw=1.4, label="actual")
        ax.plot([str(m) for m in fut], cur, "-", color="#2a78d6", lw=2, label=f"full-origin: {base_sel[:32]}")
        ax.plot([str(m) for m in fut], alt, "--", color="#d03b3b", lw=2, label=f"recent-origin: {recent_best}")
        ax.set_title(f"{sid}: full vs recent-origin selection"); ax.tick_params(axis="x", rotation=90, labelsize=6)
        ax.legend(fontsize=6); plt.tight_layout()
        plt.savefig(outdir / f"recent_vs_full_{sid.replace('|', '_')}.png"); plt.close()
        rows.append({"series_id": sid, "full_selected": base_sel, "recent_best_model": recent_best,
                     "full_12m_total": round(float(np.sum(cur)), 1), "recent_12m_total": round(float(np.sum(alt)), 1),
                     "pct_diff": round(float((np.sum(alt) - np.sum(cur)) / max(np.sum(cur), 1) * 100), 2)})
    tab = pd.DataFrame(rows)
    out = config.OUTPUTS_DIR / "state_check"; os.makedirs(out, exist_ok=True)
    tab.to_csv(out / "PC2_recent_vs_full.csv", index=False)
    print(tab.to_string(index=False))
    print("charts ->", outdir)


if __name__ == "__main__":
    main()
