"""Stage-8 tests: holdout guard, forecast reconciliation, and scenario separation."""
from __future__ import annotations

import glob
import os

import pandas as pd
import pytest

from forecasting import backtest, config


def _latest_stage4():
    runs = sorted(glob.glob(str(config.OUTPUTS_DIR / "stage4" / "run_*")))
    if not runs:
        pytest.skip("no stage4 run")
    return runs[-1]


def test_holdout_guard_no_targets_after_cut():
    """The backtest must never return a target month after the backtest cut (2026-03)."""
    import numpy as np
    y = pd.Series(np.arange(1, 40, dtype=float),
                  index=pd.period_range("2023-01", periods=39, freq="M"))
    origins = list(pd.period_range("2024-12", "2026-02", freq="M"))
    cut = pd.Period("2026-03", "M")
    exog = pd.DataFrame(index=y.index)
    rows, _ = backtest.backtest_series(y, "naive", {}, exog, origins, 12, cut)
    assert rows, "expected rows"
    assert all(pd.Period(r["target"], "M") <= cut for r in rows), "backtest leaked past the cut"


def test_forecast_reconciliation():
    d = _latest_stage4()
    fc = pd.read_parquet(os.path.join(d, "forecasts.parquet"))
    for scenario in fc.scenario.unique():
        for q in ["point_forecast_mt", "q10", "q90"]:
            piv = (fc[fc.scenario == scenario]
                   .pivot_table(index="month", columns="series_id", values=q, aggfunc="sum"))
            def col(sid):
                return piv[sid] if sid in piv.columns else 0.0
            ext = col("AIL|sbu|external"); co = col("AIL|channel|Corporate"); tr = col("AIL|channel|Trade")
            ic = col("AIL|channel|Intercompany"); comp = col("AIL|company")
            zsum = sum(col(f"AIL|zone|Trade|{z}") for z in ["Dhaka", "North", "North East", "South"])
            assert ((co + tr - ext).abs() <= 1.0).all(), f"{scenario}/{q}: external != Corporate+Trade"
            assert ((ext + ic - comp).abs() <= 1.0).all(), f"{scenario}/{q}: company != external+intercompany"
            assert ((zsum - tr).abs() <= 1.0).all(), f"{scenario}/{q}: Trade != sum(zones)"


def test_scenarios_differ_from_base():
    d = _latest_stage4()
    fc = pd.read_parquet(os.path.join(d, "forecasts.parquet"))
    diff = []
    for sid, g in fc.groupby("series_id"):
        base = g[g.scenario == "base"].point_forecast_mt.values
        for sc in ["disruption", "flood"]:
            v = g[g.scenario == sc].point_forecast_mt.values
            if len(v) == len(base) and abs(v - base).max() > 1e-6:
                diff.append(sid)
    assert diff, "no scenario differs from base - scenarios are inert"
