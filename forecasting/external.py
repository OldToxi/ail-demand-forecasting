"""External-data loading, registry application and the lag/leakage gate.

Rules:
- known_in_advance: usable for any target month (actual future values allowed).
- leading: for a forecast at origin T, only the observed value at (<= T - lag) may be used; for
  future targets it is frozen at that last observation (no peeking).
- scenario_only / constraint_flag / check_only: not base-model features (scenario or flags only).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

KNOWN = "known_in_advance"
LEADING = "leading"
SCENARIO = "scenario_only"
CONSTRAINT = "constraint_flag"
CHECK = "check_only"


def load_monthly(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["month"] = pd.PeriodIndex(df["month"], freq="M")
    return df.set_index("month").sort_index()


def enabled_variables(registry: dict, segment: str) -> list[dict]:
    seg = set([segment, "ALL"])
    return [v for v in registry["variables"] if v.get("enabled", True) and (set(v["segments"]) & seg)]


def calendar_features(monthly: pd.DataFrame, registry: dict, segment: str) -> pd.DataFrame:
    """Known-in-advance calendar/budget features (one column per feature_key)."""
    out = {}
    for v in enabled_variables(registry, segment):
        if v["type"] == KNOWN and v.get("transform") != "annual_level" and v["column"] in monthly:
            out[v["feature_key"]] = monthly[v["column"]].astype(float)
    return pd.DataFrame(out, index=monthly.index)


def constraint_months(monthly: pd.DataFrame) -> set:
    """Months flagged by known disruption/flood constraints (DQ-30/31 / events)."""
    m = set()
    full = monthly.get("disruption_days_full")
    flood = monthly.get("flood_major_flag")
    if full is not None:
        m |= set(monthly.index[full.fillna(0) > 0])
    if flood is not None:
        m |= set(monthly.index[flood.fillna(0) > 0])
    return m


def annual_level_feature(monthly: pd.DataFrame, column: str) -> pd.Series:
    """ADP: annual allocation spread flat across the fiscal-year months (no monthly interpolation)."""
    s = pd.Series(index=monthly.index, dtype=float)
    for fy, grp in monthly.groupby("fiscal_year"):
        val = grp[column].dropna()
        if len(val):
            s.loc[grp.index] = float(val.iloc[0])
    return s


def interventions_for(series_id: str, cfg: dict) -> pd.DataFrame:
    """Return a month-indexed frame of 0/1 intervention columns for a series (from config)."""
    spec = (cfg.get("interventions") or {}).get(series_id) or (cfg.get("interventions") or {}).get("default", {})
    rows = {}
    for name, (a, b) in spec.items():
        idx = pd.period_range(a, b, freq="M")
        rows[name] = idx
    return rows


def lagged_frame(monthly: pd.DataFrame, registry: dict, segment: str, origin: pd.Period,
                 horizon: int, future_index: pd.PeriodIndex) -> pd.DataFrame:
    """Build exog for a forecast made at `origin` covering `future_index`.

    known_in_advance -> actual future values.
    leading          -> frozen at the last observed value (month <= origin - lag); NaN before it exists.
    The returned frame is indexed by future_index.
    """
    cols = {}
    for v in enabled_variables(registry, segment):
        col = v["column"]
        if col not in monthly:
            continue
        if v["type"] == KNOWN and v.get("transform") != "annual_level":
            cols[v["feature_key"]] = monthly[col].reindex(future_index).astype(float).values
        elif v["type"] == LEADING:
            cutoff = origin - v.get("lag", 1)
            hist = monthly.loc[monthly.index <= cutoff, col].dropna()
            cols[v["feature_key"]] = [float(hist.iloc[-1]) if len(hist) else float("nan")] * len(future_index)
    return pd.DataFrame(cols, index=future_index)


def last_available_month(var: dict, origin: pd.Period) -> pd.Period | None:
    """Latest source month allowed for a variable at a given origin (leakage guard)."""
    if var["type"] == KNOWN:
        return None                      # any month allowed
    if var["type"] == LEADING:
        return origin - var.get("lag", 1)
    return None                          # not a base feature
