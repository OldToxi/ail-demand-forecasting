"""Zero-shot backtest via a torch-first subprocess (P1.11). Parent uses pandas to build series and score;
the subprocess imports torch before numpy/pyarrow. Writes data/outputs/forecast/zeroshot_results.json.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pandas as pd

from . import config
from .adapters import load_all
from .series import build_series

AG = {"company", "sbu", "channel", "zone"}


def backtest_metrics(series_df: pd.DataFrame, origins: list, cut: pd.Period, H: int, sbu_id: str = "AIL"):
    """Run Chronos-Bolt in a torch-first subprocess and return (metric_rows, preds_df).

    series_df: columns series_id, month (str or Period), y. Metric rows match metrics.parquet schema.
    """
    import numpy as np
    agg = series_df[series_df["series_id"].isin(series_df["series_id"].unique())].copy()
    agg["month"] = pd.PeriodIndex(agg["month"], freq="M").astype(str)
    outdir = config.OUTPUTS_DIR / "zeroshot"; os.makedirs(outdir, exist_ok=True)
    sp = outdir / "series.parquet"; opp = outdir / "preds.parquet"
    agg.to_parquet(sp, index=False)
    r = subprocess.run([sys.executable, "-m", "forecasting.zeroshot_worker", str(sp), str(opp),
                        json.dumps([str(o) for o in origins])], capture_output=True, text=True)
    if r.returncode != 0 or not opp.exists():
        return [], None
    preds = pd.read_parquet(opp)
    actual = {(row.series_id, row.month): row.y for row in agg.itertuples()}
    from . import backtest
    rows = []
    for sid, g in preds.groupby("series_id"):
        recs = []
        for r_ in g.itertuples():
            t = str(pd.Period(r_.origin, "M") + r_.horizon)
            if cut is not None and pd.Period(t, "M") > pd.Period(cut, "M"):
                continue
            a = actual.get((sid, t))
            if a is None:
                continue
            recs.append({"origin": r_.origin, "target": t, "horizon": r_.horizon,
                         "actual": float(a), "pred": float(r_.pred),
                         "abs_error": abs(r_.pred - float(a)), "err": float(r_.pred) - float(a)})
        if not recs:
            continue
        s = series_df[series_df["series_id"] == sid].copy()
        s["month"] = pd.PeriodIndex(s["month"], freq="M")
        s = s.sort_values("month")
        y_sid = pd.Series(s["y"].values, index=s["month"])
        scale = backtest.seasonal_naive_mae(y_sid, origins, H)
        summ = backtest.summarize(recs, scale)
        for b, m in summ.items():
            m.update({"sbu": sbu_id, "series_id": sid, "model": "chronos_bolt", "horizon_bucket": b})
            rows.append(m)
    return rows, preds


def main():
    cfg = config.load_config(); reg = config.load_sbus()
    sbu = next(s for s in reg["sbus"] if s["sbu_id"] == "AIL"); sbu["_hierarchy"] = reg["hierarchy"]
    cut = pd.Period("2026-03", "M")
    series = build_series(sbu, config.REPO_ROOT)
    agg = series[series.level.isin(AG)][["series_id", "month", "y"]].copy()
    agg["month"] = agg["month"].astype(str)
    outdir = config.OUTPUTS_DIR / "zeroshot"; os.makedirs(outdir, exist_ok=True)
    sp = outdir / "series.parquet"; opp = outdir / "preds.parquet"
    agg.to_parquet(sp, index=False)
    origins = [str(m) for m in pd.period_range(cfg["backtest_origins"][0], cfg["backtest_origins"][1], freq="M")]
    r = subprocess.run([sys.executable, "-m", "forecasting.zeroshot_worker", str(sp), str(opp), json.dumps(origins)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not opp.exists():
        res = {"model": "chronos_bolt", "status": "failed_subprocess", "stderr": r.stderr[-500:]}
        (config.OUTPUTS_DIR / "zeroshot_results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
        print("zero-shot worker failed:", r.stderr[-300:]); return
    preds = pd.read_parquet(opp)
    # score h1-6 against actuals
    pdf = pd.read_parquet(sp)
    actual = {(r.series_id, r.month): r.y for r in pdf.itertuples()}
    import numpy as np
    rows = []
    for sid, g in preds.groupby("series_id"):
        ae = av = 0.0; h16 = 0.0; hv = 0.0
        for r_ in g.itertuples():
            t = str(pd.Period(r_.origin, "M") + r_.horizon)
            if cut is not None and pd.Period(t, "M") > pd.Period(cut, "M"):
                continue
            a = actual.get((sid, t))
            if a is None:
                continue
            ae += abs(r_.pred - a); av += abs(a)
            if r_.horizon <= 6:
                h16 += abs(r_.pred - a); hv += abs(a)
        if av:
            rows.append({"series_id": sid, "wape_all": round(ae / av, 4),
                         "wape_h1_6": round(h16 / max(hv, 1), 4), "n": int(av > 0)})
    res = {"model": "chronos_bolt (subprocess)", "status": "ok", "by_series": rows,
           "mean_wape_all": round(float(pd.DataFrame(rows).wape_all.mean()), 4) if rows else None}
    (config.OUTPUTS_DIR / "zeroshot_results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps(res, indent=2)[:800])


if __name__ == "__main__":
    main()
