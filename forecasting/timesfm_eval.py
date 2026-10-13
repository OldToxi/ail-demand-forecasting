"""TimesFM 2.5-200M zero-shot backtest vs Chronos-Bolt + equal-weight ensemble.

Step 4: run TimesFM zero-shot, compare WAPE against the Chronos-Bolt leaderboard reference
(0.2841), build the chronos+timesfm equal-weight ensemble, and report the AIL|company
last-origin (2026-02) seasonality analysis. Writes data/outputs/forecast/zeroshot_bakeoff.json.

Scoring mirrors zeroshot_runner.backtest_metrics (per-series per-bucket WAPE via
backtest.summarize; headline = unweighted mean over the 9 aggregate series). The reference
0.2841 is UNCUT (targets through 2026-09); we also report a cut-at-2026-03 variant.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

from . import backtest, config, zeroshot_runner
from .series import build_series

AG = {"company", "sbu", "channel", "zone"}
MODEL_REPO = "google/timesfm-2.5-200m-pytorch"
CUT = pd.Period("2026-03", "M")
BUCKETS = ["short", "medium", "long", "all"]


def _score(preds: pd.DataFrame, actual: dict, model_name: str, cut: pd.Period | None) -> list[dict]:
    """Score a preds frame (series_id, origin, horizon, pred) into per-series per-bucket metric rows."""
    rows = []
    for sid, g in preds.groupby("series_id"):
        recs = []
        for r_ in g.itertuples():
            t_period = pd.Period(r_.origin, "M") + r_.horizon
            if cut is not None and t_period > cut:
                continue
            t = str(t_period)
            a = actual.get((sid, t))
            if a is None:
                continue
            recs.append({"origin": r_.origin, "target": t, "horizon": r_.horizon,
                         "actual": float(a), "pred": float(r_.pred),
                         "abs_error": abs(r_.pred - float(a)), "err": float(r_.pred) - float(a)})
        if not recs:
            continue
        summ = backtest.summarize(recs, 1.0)
        for b, m in summ.items():
            m.update({"sbu": "AIL", "series_id": sid, "model": model_name, "horizon_bucket": b})
            rows.append(m)
    return rows


def _mean_wape(rows: list[dict], model_name: str) -> dict:
    """Unweighted mean of per-series per-bucket WAPE (matches the leaderboard convention)."""
    df = pd.DataFrame([r for r in rows if r["model"] == model_name])
    if df.empty:
        return {b: None for b in BUCKETS}
    return {b: (round(float(df[df.horizon_bucket == b].wape.mean()), 4)
                if len(df[df.horizon_bucket == b]) else None) for b in BUCKETS}


def _ensemble(p1: pd.DataFrame, p2: pd.DataFrame) -> pd.DataFrame:
    m = p1.merge(p2, on=["series_id", "origin", "horizon"], suffixes=("_c", "_t"))
    m["pred"] = (m.pred_c + m.pred_t) / 2.0
    return m[["series_id", "origin", "horizon", "pred"]]


def _detrended_month_of_year_index(agg: pd.DataFrame) -> dict:
    """OLS-linear-detrended seasonal index of AIL|company actuals: mean residual per calendar month.

    Returns {month_int 1..12: mean_detrended_value}.
    """
    comp = agg[agg.series_id == "AIL|company"].sort_values("month").reset_index(drop=True)
    months = pd.PeriodIndex(comp.month, freq="M")
    y = comp.y.values.astype(float)
    n = len(y)
    t = np.arange(n, dtype=float)
    b = np.polyfit(t, y, 1)
    detrended = y - np.polyval(b, t)
    idx = {}
    for m in range(1, 13):
        vals = detrended[months.month == m]
        idx[m] = float(vals.mean()) if len(vals) else 0.0
    return idx


def _company_analysis(chronos_preds: pd.DataFrame, timesfm_preds: pd.DataFrame, agg: pd.DataFrame) -> dict:
    sid, origin = "AIL|company", "2026-02"

    def get12(preds):
        sub = preds[(preds.series_id == sid) & (preds.origin == origin)].sort_values("horizon")
        return np.asarray(sub.pred.values, dtype=float)

    c = get12(chronos_preds)
    t = get12(timesfm_preds)
    e = (c + t) / 2.0
    idx = _detrended_month_of_year_index(agg)
    # origin 2026-02 -> h=1..12 => calendar months Mar..Feb
    align = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2]
    idx_aligned = np.array([idx[m] for m in align], dtype=float)

    def cov(v):
        return float(np.std(v) / np.mean(v)) if np.mean(v) else float("nan")

    def corr(v):
        return float(np.corrcoef(v, idx_aligned)[0, 1])

    return {
        "origin": origin,
        "detrended_month_of_year_index": {str(m): round(idx[m], 2) for m in range(1, 13)},
        "method": "OLS linear detrend of AIL|company actuals -> mean residual per calendar month; "
                  "forecast aligned h=1..12 -> Mar..Feb",
        "chronos_bolt": {"forecast": [round(float(x), 2) for x in c], "cov": round(cov(c), 4),
                         "corr_vs_detrended_index": round(corr(c), 4)},
        "timesfm": {"forecast": [round(float(x), 2) for x in t], "cov": round(cov(t), 4),
                    "corr_vs_detrended_index": round(corr(t), 4)},
        "ensemble_equal_weight": {"forecast": [round(float(x), 2) for x in e], "cov": round(cov(e), 4),
                                  "corr_vs_detrended_index": round(corr(e), 4)},
    }


def main():
    cfg = config.load_config()
    reg = config.load_sbus()
    sbu = next(s for s in reg["sbus"] if s["sbu_id"] == "AIL")
    sbu["_hierarchy"] = reg["hierarchy"]
    series = build_series(sbu, config.REPO_ROOT)
    agg = series[series.level.isin(AG)][["series_id", "month", "y"]].copy()
    agg["month"] = agg["month"].astype(str)

    outdir = config.OUTPUTS_DIR / "zeroshot"
    os.makedirs(outdir, exist_ok=True)
    sp = outdir / "series.parquet"
    agg.to_parquet(sp, index=False)

    origins = [str(m) for m in pd.period_range(cfg["backtest_origins"][0], cfg["backtest_origins"][1], freq="M")]
    H = cfg["horizon_months"]

    # --- Chronos-Bolt reference (uncut, reproduces 0.2841) ---
    chronos_rows, chronos_preds = zeroshot_runner.backtest_metrics(agg, origins, CUT, H)

    # --- TimesFM ---
    tp = outdir / "preds_timesfm.parquet"
    r = subprocess.run([sys.executable, "-m", "forecasting.timesfm_worker", str(sp), str(tp),
                        json.dumps(origins)], capture_output=True, text=True)
    if r.returncode != 0 or not tp.exists():
        res = {"status": "failed_subprocess", "stderr": (r.stderr or "")[-2000:]}
        (config.OUTPUTS_DIR / "zeroshot_bakeoff.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
        print("timesfm worker failed:", (r.stderr or "")[-800:])
        return
    timesfm_preds = pd.read_parquet(tp)

    actual = {(row.series_id, row.month): row.y for row in agg.itertuples()}

    # --- Score (uncut = reference convention; cut = instruction) ---
    timesfm_rows = _score(timesfm_preds, actual, "timesfm", cut=None)
    ens_preds = _ensemble(chronos_preds, timesfm_preds)
    ens_rows = _score(ens_preds, actual, "ensemble_equal_weight", cut=None)

    chronos_cut_rows = _score(chronos_preds, actual, "chronos_bolt", cut=CUT)
    timesfm_cut_rows = _score(timesfm_preds, actual, "timesfm", cut=CUT)
    ens_cut_rows = _score(ens_preds, actual, "ensemble_equal_weight", cut=CUT)

    mean_wape = {
        "chronos_bolt": _mean_wape(chronos_rows, "chronos_bolt"),
        "timesfm": _mean_wape(timesfm_rows, "timesfm"),
        "ensemble_equal_weight": _mean_wape(ens_rows, "ensemble_equal_weight"),
    }
    cut_all = {
        "chronos_bolt": _mean_wape(chronos_cut_rows, "chronos_bolt")["all"],
        "timesfm": _mean_wape(timesfm_cut_rows, "timesfm")["all"],
        "ensemble_equal_weight": _mean_wape(ens_cut_rows, "ensemble_equal_weight")["all"],
    }

    company = _company_analysis(chronos_preds, timesfm_preds, agg)

    ref = 0.2841
    ens_all = mean_wape["ensemble_equal_weight"]["all"]
    verdict = (
        f"ensemble WAPE {ens_all} vs chronos_bolt {ref}: "
        + ("ensemble BEATS chronos" if ens_all is not None and ens_all < ref else
           "ensemble does NOT beat chronos" if ens_all is not None else "ensemble unavailable")
    )

    res = {
        "status": "ok",
        "task": "timesfm_zero_shot_bakeoff",
        "model_repo": MODEL_REPO,
        "series_count": int(agg.series_id.nunique()),
        "origins": origins[0] + ".." + origins[-1],
        "reference": {"chronos_bolt_wape": ref,
                      "note": "uncut (targets through 2026-09); unweighted mean of per-series WAPE"},
        "mean_wape_by_bucket": mean_wape,
        "cut_at_2026_03_wape_all": cut_all,
        "company_last_origin": company,
        "verdict": verdict,
    }
    (config.OUTPUTS_DIR / "zeroshot_bakeoff.json").write_text(json.dumps(res, indent=2), encoding="utf-8")

    # --- human-readable report ---
    print("=" * 72)
    print("TimesFM zero-shot bakeoff")
    print(f"series: {res['series_count']}   origins: {res['origins']}   (uncut reference convention)")
    print("-" * 72)
    hdr = f"{'model':22s} {'all':>8s} {'short':>8s} {'medium':>8s} {'long':>8s}   {'cut@2026-03':>12s}"
    print(hdr)
    for name in ["chronos_bolt", "timesfm", "ensemble_equal_weight"]:
        w = mean_wape[name]
        print(f"{name:22s} {str(w['all']):>8s} {str(w['short']):>8s} {str(w['medium']):>8s} "
              f"{str(w['long']):>8s}   {str(cut_all[name]):>12s}")
    print("-" * 72)
    ca = company
    print("AIL|company last origin 2026-02 (12 forecasts): CoV / corr vs detrended month-of-year index")
    for name in ["chronos_bolt", "timesfm", "ensemble_equal_weight"]:
        m = ca[name]
        print(f"  {name:22s} CoV={m['cov']:<8} corr={m['corr_vs_detrended_index']}")
    print(f"  detrended month-of-year index: {ca['detrended_month_of_year_index']}")
    print("-" * 72)
    print(verdict)
    print("wrote", config.OUTPUTS_DIR / "zeroshot_bakeoff.json")


if __name__ == "__main__":
    main()
