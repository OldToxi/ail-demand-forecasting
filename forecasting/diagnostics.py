"""Diagnostics (item 1): actual vs forecast for every model at chosen origins, plus exog-alignment and
intervention checks. Writes a table (CSV) and charts per series under data/outputs/forecast/diagnostics/.
"""
from __future__ import annotations

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from . import backtest, config, external
from .adapters import load_all
from .models import build_model
from .series import build_series

SERIES = {"AIL|company": "company", "AIL|channel|Trade": "trade", "AIL|zone|Trade|Dhaka": "dhaka"}
ORIGINS = ["2024-12", "2025-06", "2026-02"]
MODELS = ["naive", "seasonal_naive", "ma3", "ets", "stl_ets", "theta", "lightgbm", "structural", "sarimax"]


def run():
    cfg = config.load_config(); reg = config.load_sbus(); ext_reg = config.load_external_registry()
    ext = external.augment_with_files(external.load_monthly(config.resolve(ext_reg["monthly_file"])),
                                      ext_reg, config.REPO_ROOT)
    cal = [v["feature_key"] for v in ext_reg["variables"]
           if v["type"] == "known_in_advance" and v.get("transform") != "annual_level"]
    base = backtest.build_exog(ext, ext_reg, "STEEL", ext.index, cal)
    sbu = next(s for s in reg["sbus"] if s["sbu_id"] == "AIL"); sbu["_hierarchy"] = reg["hierarchy"]
    series = build_series(sbu, config.REPO_ROOT)
    out = config.OUTPUTS_DIR / "diagnostics"; out.mkdir(parents=True, exist_ok=True)

    rows = []
    for sid, tag in SERIES.items():
        g = series[series.series_id == sid].sort_values("month")
        y = pd.Series(g["y"].values, index=pd.PeriodIndex(g["month"], freq="M"))
        exog = base.join(external.intervention_frame(sid, cfg, base.index))
        for T in ORIGINS:
            T = pd.Period(T, "M")
            train = y[y.index <= T]
            targets = pd.period_range(T + 1, periods=12, freq="M")
            for name in MODELS:
                try:
                    m = build_model(name, {}); sup = m.supports_exog
                    m.fit(train, exog.reindex(train.index) if sup else None)
                    fc = m.predict(12, exog.reindex(targets) if sup else None)
                    for i, t in enumerate(targets):
                        act = float(y.loc[t]) if t in y.index else np.nan
                        rows.append({"series": tag, "origin": str(T), "model": name, "target": str(t),
                                     "horizon": i + 1, "actual": act, "forecast": round(float(fc.point[i]), 1)})
                except Exception as e:
                    rows.append({"series": tag, "origin": str(T), "model": name, "target": "", "horizon": 0,
                                 "actual": np.nan, "forecast": np.nan, "error": type(e).__name__})
    df = pd.DataFrame(rows)
    df.to_csv(out / "actual_vs_forecast.csv", index=False)

    # charts per series
    for sid, tag in SERIES.items():
        d = df[df.series == tag]
        fig, axes = plt.subplots(1, 3, figsize=(16, 4), sharey=False)
        for ax, T in zip(axes, ORIGINS):
            dd = d[d.origin == T]
            base_actual = dd[dd.model == "naive"][["target", "actual"]].dropna()
            ax.plot(base_actual.target, base_actual.actual, "k-", lw=2, label="actual")
            for name in ["ets", "stl_ets", "structural", "sarimax", "seasonal_naive"]:
                mm = dd[dd.model == name]
                if mm.empty:
                    continue
                ax.plot(mm.target, mm.forecast, "--", label=name)
            ax.set_title(f"{tag} @ {T}"); ax.tick_params(axis="x", rotation=90, labelsize=6); ax.legend(fontsize=6)
        plt.tight_layout(); plt.savefig(out / f"diag_{tag}.png"); plt.close()

    # exog alignment + intervention check for company
    sid = "AIL|company"; exog = base.join(external.intervention_frame(sid, cfg, base.index))
    fut = pd.period_range("2026-04", periods=6, freq="M")
    print("exog columns:", list(exog.columns))
    print("future exog rows:\n", exog.reindex(fut)[["eid_closure_days_total", "working_days_6day", "slump"]].to_string())
    print("\nactual vs forecast (company, origin 2024-12):")
    print(df[(df.series == "company") & (df.origin == "2024-12")].pivot_table(
        index="horizon", columns="model", values="forecast").round(0).to_string())
    print("\nWAPE by model (mean over series/origins, horizons 1-6):")
    dd = df[(df.horizon >= 1) & (df.horizon <= 6) & df.actual.notna()]
    dd = dd.assign(ae=lambda x: (x.forecast - x.actual).abs())
    print((dd.groupby("model").apply(lambda g: g.ae.sum() / g.actual.abs().sum())).sort_values().round(3).to_string())
    print("wrote", out)


if __name__ == "__main__":
    run()
