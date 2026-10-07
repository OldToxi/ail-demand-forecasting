"""Stage 1 unit tests: adapter contract, hierarchy sums, no dup series-months,
DQ cross-check, and the external-data leakage guard."""
from __future__ import annotations

import pandas as pd
import pytest

from forecasting import config, external
from forecasting.adapters import load_all
from forecasting.adapters.base import STANDARD_COLUMNS
from forecasting.series import build_series, validate_hierarchy


@pytest.fixture(scope="module")
def setup():
    reg = config.load_sbus()
    sbu = next(s for s in reg["sbus"] if s["sbu_id"] == "AIL")
    sbu["_hierarchy"] = reg["hierarchy"]
    frames = load_all(sbu, config.REPO_ROOT)
    series = build_series(sbu, config.REPO_ROOT)
    return sbu, frames, series


def test_adapter_schema(setup):
    _, frames, _ = setup
    for name, df in frames.items():
        assert list(df.columns) == STANDARD_COLUMNS, f"{name} schema mismatch"
        assert df["month"].dtype == "period[M]"
        assert df["y"].dtype.kind == "f"
        assert df["date"].notna().all()
        assert (df["date"].dt.year != 1970).all()


def test_hierarchy_sums(setup):
    sbu, _, series = setup
    checks = validate_hierarchy(series, sbu)
    for k, v in checks.items():
        assert v == v and v <= 1e-6, f"{k} not reconciled: max diff {v}"


def test_no_duplicate_series_months(setup):
    _, _, series = setup
    dup = series.duplicated(subset=["series_id", "month"]).sum()
    assert dup == 0, f"{dup} duplicate series-months"


def test_monthly_totals_match_dq_layer(setup):
    """Channel monthly MT must equal the DQ cleaned layer under the same rules."""
    _, frames, series = setup
    dq = config.REPO_ROOT / "Data" / "work" / "outputs" / "cleaned_sales_with_flags.parquet"
    if not dq.exists():
        pytest.skip("DQ layer not available")
    pq = pd.read_parquet(dq)
    subset = [c for c in ["source", "date", "client", "channel", "zone", "manager", "am",
                          "district", "mt", "s_values", "opb", "collection", "clb"] if c in pq.columns]
    pq = pq[(pq["date"].dt.year != 1970) & pq["date"].notna()].drop_duplicates(subset=subset)
    pq["month"] = pq["date"].dt.to_period("M")
    ref = pq.groupby(["source", "month"])["mt"].apply(lambda s: s.fillna(0).sum())

    got = series[series.level == "channel"].copy()
    got["src"] = got["series_id"].str.split("|").str[-1]
    got = got.set_index(["src", "month"])["y"]
    common = got.index.intersection(ref.index)
    diff = (got.loc[common] - ref.loc[common]).abs().max()
    assert diff <= 1.0, f"channel totals differ from DQ layer by {diff:,.2f} MT"


def test_external_leakage_guard():
    """A leading variable with lag L is only usable up to origin - L."""
    reg = config.load_external_registry()
    origin = pd.Period("2026-03", "M")
    for v in reg["variables"]:
        if v["type"] == external.LEADING:
            assert external.last_available_month(v, origin) == origin - v["lag"]
    # lagged_frame must not use any month after origin - lag for leading vars
    path = config.resolve(reg["monthly_file"])
    if not path.exists():
        pytest.skip("external monthly not available")
    monthly = external.load_monthly(path)
    future = pd.period_range("2026-04", periods=6, freq="M")
    fr = external.lagged_frame(monthly, reg, "STEEL", origin, 6, future)
    lead_cols = [v["feature_key"] for v in reg["variables"]
                 if v["type"] == external.LEADING and v["column"] in monthly]
    for c in lead_cols:
        if c in fr:
            vals = fr[c].dropna()
            # frozen: all future values equal the observed value at/just before origin-lag
            assert len(set(vals.round(6))) <= 1, f"{c} not frozen at origin-lag"
