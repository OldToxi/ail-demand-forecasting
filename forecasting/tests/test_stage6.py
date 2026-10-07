"""Stage 6 tests: registry validation, a synthetic second SBU via registry+adapter only,
minimum-history reduced model pool, and an end-to-end fixture run."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from forecasting import backtest, config
from forecasting.adapters.base import STANDARD_COLUMNS, load_source
from forecasting.dq_gate import run_gate
from forecasting.models import build_model
from forecasting.series import build_series


def test_registry_validation():
    reg = config.load_sbus()
    assert "sbus" in reg and reg["sbus"], "no SBUs configured"
    for s in reg["sbus"]:
        for key in ["sbu_id", "name", "segment_code", "sources"]:
            assert key in s, f"SBU missing {key}"
        for src in s["sources"]:
            assert src.get("adapter"), "source missing adapter"
            assert "column_map" in src and "date" in src["column_map"]
    ext = config.load_external_registry()
    for v in ext["variables"]:
        assert {"feature_key", "column", "lag", "type", "segments"} <= set(v), v


def _synthetic_cem(tmp_path):
    """18 months of a CEM SBU with a DIFFERENT layout (column names)."""
    months = pd.period_range("2025-01", "2026-06", freq="M")
    rows = []
    rng = np.random.default_rng(0)
    for m in months:
        for buyer, base in [("Cem Buyer A", 900), ("Cem Buyer B", 400), ("Cem Buyer C", 150)]:
            vol = max(base + rng.normal(0, base * 0.2), 0)
            rows.append({"TrxDate": m.to_timestamp().date(), "Buyer": buyer, "Channel": "Cement",
                         "Territory": "Central", "District": "Dhaka", "Volume_MT": round(vol, 1),
                         "Value": round(vol * 80000, 0), "OpenBal": 0, "Receipt": 0, "CloseBal": 0})
    df = pd.DataFrame(rows)
    p = tmp_path / "acme_cement_monthly.csv"
    df.to_csv(p, index=False)
    return p


def test_synthetic_cem_adapter_and_gate(tmp_path):
    _synthetic_cem(tmp_path)
    source_cfg = {
        "name": "Cement", "adapter": "tabular", "file": "acme_cement_monthly.csv", "sheet": "Data",
        "header_row": 1, "key_style": "name_plus_district",
        "column_map": {"date": "TrxDate", "channel": "Channel", "zone": "Territory", "client": "Buyer",
                       "district": "District", "quantity": "Volume_MT", "value": "Value",
                       "opening": "OpenBal", "collection": "Receipt", "closing": "CloseBal"},
    }
    std = load_source("ACME", source_cfg, tmp_path)
    assert list(std.columns) == STANDARD_COLUMNS
    assert std["month"].nunique() == 18
    assert std["y"].notna().all()

    sbu_cfg = {"sbu_id": "ACME", "segment_code": "CEM", "min_history_months": 12,
               "sources": [source_cfg],
               "_hierarchy": {"company_series": "ACME|company", "external_series": "ACME|sbu|external",
                              "external_channels": ["Cement"], "intercompany_channel": "Intercompany",
                              "account_channel": "Cement"}}
    series = build_series(sbu_cfg, tmp_path)
    gate = run_gate(sbu_cfg, {"Cement": std}, series, ext_monthly=None, expected_end="2026-06")
    assert gate["passed"], gate["hard_failures"]
    # hierarchy reconciles for the synthetic SBU too
    check = series[series.level == "channel"]["y"].sum()
    assert abs(series[series.level == "sbu"]["y"].sum() - check) < 1e-6


def test_reduced_model_pool_for_18_months():
    # 18 months -> two-seasonal-cycle models (min_history 24) must be excluded by the rule
    assert build_model("ets").min_history_months == 24
    assert build_model("seasonal_naive").min_history_months == 12
    n_months = 18
    full = [m for m in ["ets", "stl_ets", "theta", "sarimax", "structural", "lightgbm"]
            if build_model(m).min_history_months <= n_months]
    assert full == [], f"18-month series should drop these: {full}"


def test_end_to_end_fixture(tmp_path):
    _synthetic_cem(tmp_path)
    source_cfg = {
        "name": "Cement", "adapter": "tabular", "file": "acme_cement_monthly.csv", "sheet": "Data",
        "header_row": 1, "key_style": "name_plus_district",
        "column_map": {"date": "TrxDate", "channel": "Channel", "zone": "Territory", "client": "Buyer",
                       "district": "District", "quantity": "Volume_MT", "value": "Value",
                       "opening": "OpenBal", "collection": "Receipt", "closing": "CloseBal"},
    }
    std = load_source("ACME", source_cfg, tmp_path)
    sbu_cfg = {"sbu_id": "ACME", "segment_code": "CEM", "min_history_months": 12, "sources": [source_cfg],
               "_hierarchy": {"company_series": "ACME|company", "external_series": "ACME|sbu|external",
                              "external_channels": ["Cement"], "intercompany_channel": "Intercompany",
                              "account_channel": "Cement"}}
    series = build_series(sbu_cfg, tmp_path)
    g = series[series.level == "sbu"].sort_values("month")
    y = pd.Series(g["y"].values, index=pd.PeriodIndex(g["month"], freq="M"))
    origins = list(pd.period_range("2026-01", "2026-03", freq="M"))
    rows, _ = backtest.backtest_series(y, "seasonal_naive", {}, pd.DataFrame(index=y.index),
                                       origins, 3, pd.Period("2026-06", "M"))
    assert rows and "skipped" not in rows[0]
    summ = backtest.summarize(rows, 1.0)
    assert "all" in summ and np.isfinite(summ["all"]["wape"])
