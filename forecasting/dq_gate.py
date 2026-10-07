"""Automated data-quality gate (Stage 1 subset). Mirrors the issues formalised in
DATA_QUALITY_REPORT.md. Hard failures stop the SBU; warnings are logged and surfaced to the UI.
"""
from __future__ import annotations

import pandas as pd

from .series import validate_hierarchy


def run_gate(sbu_cfg: dict, frames: dict, series: pd.DataFrame, ext_monthly: pd.DataFrame | None,
             expected_end: str = "2026-09") -> dict:
    hard, warn = [], []
    sbu_id = sbu_cfg["sbu_id"]
    total_rows = sum(len(f) for f in frames.values())

    for name, df in frames.items():
        # grain uniqueness (DQ-03)
        dup_grain = int(df.duplicated(subset=["client_key", "month"], keep=False).sum())
        if dup_grain:
            warn.append(f"{name}: {dup_grain} grain-duplicate rows (party x month) - aggregated (DQ-03)")
        # null vs zero (DQ-07/30) - informational
        null_mt = int(df["y"].isna().sum())
        zero_mt = int((df["y"] == 0).sum())
        if null_mt or zero_mt:
            warn.append(f"{name}: MT null={null_mt} zero={zero_mt} - both treated as no-sale (DQ-07/30)")
        # negatives (DQ-13)
        neg = int((df["y"] < 0).sum())
        if neg:
            warn.append(f"{name}: {neg} negative MT rows")
        # value without quantity (DQ-14/28)
        vwq = int(((df["y"].isna() | (df["y"] == 0)) & (df["value"] > 0)).sum())
        if vwq:
            warn.append(f"{name}: {vwq} rows value>0 with no MT - excluded from MT (DQ-14/28)")
        # date gaps (missing months between first and last)
        months = sorted(df["month"].dropna().unique())
        if months:
            full = pd.period_range(months[0], months[-1], freq="M")
            gaps = len(set(full) - set(months))
            if gaps:
                warn.append(f"{name}: {gaps} calendar months with no rows between {months[0]} and {months[-1]}")

    # hierarchy sums (hard)
    checks = validate_hierarchy(series, sbu_cfg)
    for k, v in checks.items():
        if v == v and v > 1e-6:      # not NaN and material
            hard.append(f"hierarchy {k}: max |diff| = {v:,.2f} MT")
    checks_ok = {k: (v == v and v <= 1e-6) for k, v in checks.items()}

    # history length (per channel series must meet min_history_months - hard for the SBU)
    min_hist = sbu_cfg.get("min_history_months", 24)
    ch = series[series.level == "channel"]
    n_periods = ch["month"].nunique()
    if n_periods < min_hist:
        hard.append(f"history {n_periods} months < min_history_months {min_hist}")

    # external checks
    ext = {"present": ext_monthly is not None}
    if ext_monthly is not None:
        ext["n_months"] = int(len(ext_monthly))
        ext["first"] = str(ext_monthly.index.min())
        ext["last"] = str(ext_monthly.index.max())
        full = pd.period_range(ext_monthly.index.min(), ext_monthly.index.max(), freq="M")
        miss = len(set(full) - set(ext_monthly.index))
        if miss:
            warn.append(f"external: {miss} missing months in coverage")
        if ext_monthly.index.max() < pd.Period(expected_end, "M"):
            warn.append(f"external: last month {ext_monthly.index.max()} < expected {expected_end}")

    return {"sbu": sbu_id, "rows": total_rows, "n_series": int(series["series_id"].nunique()),
            "hierarchy_ok": checks_ok, "hard_failures": hard, "warnings": warn, "external": ext,
            "passed": len(hard) == 0}
