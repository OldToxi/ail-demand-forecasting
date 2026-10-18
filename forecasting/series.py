"""Build the standard series from the registry and validate the hierarchy.

Volume rule (DQ-07/30): null and zero MT are BOTH 'no sale' -> y summed as 0.
"""
from __future__ import annotations

import pandas as pd

from .adapters import load_all


def _agg(df: pd.DataFrame, series_id: str, level: str, channel=None, zone=None, account=None) -> pd.DataFrame:
    g = (df.groupby("month", as_index=False)[["y", "value"]].sum()
         .assign(series_id=series_id, level=level, channel=channel, zone=zone, account=account))
    return g[["series_id", "level", "channel", "zone", "account", "month", "y", "value"]]


def build_series(sbu_cfg: dict, base_dir) -> pd.DataFrame:
    sbu_id = sbu_cfg["sbu_id"]
    frames = load_all(sbu_cfg, base_dir)
    h = sbu_cfg["_hierarchy"]
    out = []

    # channel totals per source
    for name, df in frames.items():
        d = df.copy()
        d["y"] = d["y"].fillna(0.0)
        d["value"] = d["value"].fillna(0.0)
        out.append(_agg(d, f"{sbu_id}|channel|{name}", "channel", channel=name))

    # Trade zones
    tr = frames.get("Trade")
    if tr is not None:
        t = tr.copy(); t["y"] = t["y"].fillna(0.0); t["value"] = t["value"].fillna(0.0)
        t["zone"] = t["zone"].astype("string").fillna("Unassigned")
        for zone, zf in t.groupby("zone"):
            out.append(_agg(zf, f"{sbu_id}|zone|Trade|{zone}", "zone", channel="Trade", zone=zone))

    # external = Corporate + Trade
    ext = pd.concat([frames[c][["month", "y", "value"]] for c in h["external_channels"] if c in frames], ignore_index=True)
    ext["y"] = ext["y"].fillna(0.0)
    ext["value"] = ext["value"].fillna(0.0)
    out.append(_agg(ext, h["external_series"], "sbu"))

    # company = external + intercompany (the Intercompany channel series was already emitted above)
    if h["intercompany_channel"] in frames:
        comp = pd.concat([ext, frames[h["intercompany_channel"]][["month", "y", "value"]]], ignore_index=True)
    else:
        comp = ext
    comp["y"] = comp["y"].fillna(0.0)
    comp["value"] = comp["value"].fillna(0.0)
    out.append(_agg(comp, h["company_series"], "company"))

    # Corporate account level (top-accounts layer input)
    co = frames.get(h["account_channel"])
    if co is not None:
        c = co.copy(); c["y"] = c["y"].fillna(0.0); c["value"] = c["value"].fillna(0.0)
        for key, cf in c.groupby("client_key"):
            out.append(_agg(cf, f"{sbu_id}|account|{h['account_channel']}|{key}", "account",
                            channel=h["account_channel"], account=key))

    series = pd.concat(out, ignore_index=True)
    series = series.groupby(["series_id", "level", "channel", "zone", "account", "month"],
                            dropna=False, as_index=False)[["y", "value"]].sum()
    series.insert(1, "sbu", sbu_id)
    return series


def validate_hierarchy(series: pd.DataFrame, sbu_cfg: dict) -> dict:
    """Child sums must equal parents, month by month. Returns {check: max_abs_diff}."""
    h = sbu_cfg["_hierarchy"]; sbu_id = sbu_cfg["sbu_id"]
    piv = series.pivot_table(index="month", columns="series_id", values="y", aggfunc="sum").fillna(0.0)
    checks = {}

    def diff(parent, children):
        have = [c for c in children if c in piv.columns]
        return float((piv[parent] - piv[have].sum(axis=1)).abs().max()) if parent in piv.columns and have else float("nan")

    checks["company = external + intercompany"] = diff(
        h["company_series"], [h["external_series"], f"{sbu_id}|channel|{h['intercompany_channel']}"])
    checks["external = Corporate + Trade"] = diff(
        h["external_series"], [f"{sbu_id}|channel|{c}" for c in h["external_channels"]])
    tr_zones = [c for c in piv.columns if c.startswith(f"{sbu_id}|zone|Trade|")]
    checks["Trade = sum(zones)"] = diff(f"{sbu_id}|channel|Trade", tr_zones)
    co_accts = [c for c in piv.columns if c.startswith(f"{sbu_id}|account|Corporate|")]
    checks["Corporate = sum(accounts)"] = diff(f"{sbu_id}|channel|Corporate", co_accts)
    return checks


def monthly_totals(series: pd.DataFrame, sbu_id: str) -> pd.DataFrame:
    """Channel-level monthly MT totals (for cross-check against the DQ layer)."""
    ch = series[series.level == "channel"].copy()
    return ch.pivot_table(index="month", columns="channel", values="y", aggfunc="sum").fillna(0.0)
