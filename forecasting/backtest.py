"""Evaluation framework: rolling-origin backtest (12-month horizon), metrics and buckets.

Rules (Stage 2):
- horizons 1-12, buckets short 1-3 / medium 4-6 / long 7-12.
- rolling origins monthly (config backtest_origins), but DISCARD any target month after the backtest cut
  (2026-03); the final holdout (2026-04..09 from origin 2026-03) is evaluated once, separately.
- lag-aware exog: known-in-advance features use actual future values; leading features are frozen at
  origin - lag (handled by external.lagged_frame).
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from .models.base import BaseModel


def buckets():
    return {"short": (1, 3), "medium": (4, 6), "long": (7, 12)}


def bucket_of(h: int) -> str:
    for name, (a, b) in buckets().items():
        if a <= h <= b:
            return name
    return "long"


def build_exog(ext_monthly, registry, segment, index: pd.PeriodIndex, cols: list[str]) -> pd.DataFrame:
    if ext_monthly is None:
        return pd.DataFrame(index=index)
    from . import external
    cal = external.calendar_features(ext_monthly, registry, segment)
    have = [c for c in cols if c in cal.columns]
    return cal.reindex(index)[have]


def backtest_series(y: pd.Series, model_name: str, model_params: dict, exog_full: pd.DataFrame,
                    origins: list[pd.Period], horizon: int, cut: pd.Period,
                    series_id: str | None = None) -> tuple[list[dict], float]:
    """Return (error rows, seconds). One row per origin x horizon actually evaluated."""
    from .models import build_model, statistical
    from .models.zeroshot import ModelUnavailable
    rows = []
    t0 = time.time()
    probe = build_model(model_name, model_params)          # capability probe only
    supports_exog = probe.supports_exog
    min_hist = probe.min_history_months
    for T in origins:
        train = y[y.index <= T]
        if len(train) < max(3, min_hist):
            continue
        targets = pd.period_range(T + 1, periods=horizon, freq="M")
        keep = [i for i, t in enumerate(targets) if t <= cut and t in y.index]
        if not keep:
            continue
        Xtr = exog_full.reindex(train.index) if supports_exog else None
        Xfu = exog_full.reindex(targets) if supports_exog else None
        try:
            m = build_model(model_name, model_params)      # fresh, unfitted each origin
            statistical.CLIP_CONTEXT = {"series": series_id, "model": model_name, "origin": str(T)}
            m.fit(train, Xtr)
            fc = m.predict(horizon, Xfu)
        except ModelUnavailable:
            return ([{"skipped": "model_unavailable"}], time.time() - t0)
        except Exception as e:
            return ([{"skipped": f"error:{type(e).__name__}"}], time.time() - t0)
        for i in keep:
            t = targets[i]
            actual = float(y.loc[t])
            pred = float(fc.point[i])
            rows.append({"origin": str(T), "target": str(t), "horizon": i + 1,
                         "actual": actual, "pred": pred, "abs_error": abs(pred - actual),
                         "err": pred - actual})
    return rows, time.time() - t0


def summarize(rows: list[dict], scale_mae: float) -> dict:
    """Aggregate error rows into metrics by bucket (WAPE headline, MASE, bias, cumulative volume error)."""
    if not rows:
        return {}
    df = pd.DataFrame(rows)
    out = {}
    for b, (a, c) in buckets().items():
        d = df[(df.horizon >= a) & (df.horizon <= c)]
        if len(d) == 0:
            continue
        sa, sp = d.actual.abs().sum(), d.pred.sum()
        out[b] = {
            "wape": round(float(d.abs_error.sum() / max(sa, 1e-9)), 4),
            "mase": round(float(d.abs_error.mean() / max(scale_mae, 1e-9)), 4),
            "bias": round(float(d.err.sum() / max(sa, 1e-9)), 4),
            "cumvol_err": round(float(sp - d.actual.sum()), 1),
            "n_origins": int(d.origin.nunique()), "n": int(len(d)),
        }
    # overall
    sa = df.actual.abs().sum()
    out["all"] = {"wape": round(float(df.abs_error.sum() / max(sa, 1e-9)), 4),
                  "mase": round(float(df.abs_error.mean() / max(scale_mae, 1e-9)), 4),
                  "bias": round(float(df.err.sum() / max(sa, 1e-9)), 4),
                  "n_origins": int(df.origin.nunique()), "n": int(len(df))}
    return out


def seasonal_naive_mae(y: pd.Series, origins: list[pd.Period], horizon: int) -> float:
    """MASE scale: mean |seasonal naive error| over the backtest origins (per series)."""
    errs = []
    for T in origins:
        train = y[y.index <= T]
        if len(train) < 13:
            continue
        for i in range(1, horizon + 1):
            t = T + i
            if t in y.index:
                errs.append(abs(train.values[-12 + ((i - 1) % 12)] - float(y.loc[t])))
    return float(np.mean(errs)) if errs else 1.0
