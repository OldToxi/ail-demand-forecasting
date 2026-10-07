"""Top-down CAGR demand target for ACCL from the national brand-level market panel.

Method:
  national market size by year (actual, all brands)  -> market CAGR (adjustable window)
  ACCL share by year                                 -> pick a target share (hold / recover)
  next-12mo market   = latest full year x (1 + CAGR)
  ACCL target        = next-12mo market x target share
  monthly targets    = ACCL target x national seasonality (normalised to sum = annual)

Also emits the yearly national + ACCL series and the seasonal index so the web page can recompute the
target live when the CAGR window or target share is changed. Baseline (do-nothing trend) is shown too so
the "ask" (gap between trend and target) is explicit.

Source: National Sales Data_Cement.xlsx  (git-ignored — contains competitor data).
Run: python scripts/demand_planning/build_market_target.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

import load_data as L  # for national seasonality (57-mo panel)

ROOT = Path(__file__).resolve().parents[2]                       # planning-app/
SRC = ROOT / "data" / "raw" / "National Sales Data_Cement.xlsx"
OUT = ROOT / "data" / "outputs" / "demand_planning" / "market_target.json"
CEMENT_DATA = ROOT / "data" / "raw" / "cement_data.parquet"      # ACCL deliveries -> cement-type mix
BOM = ROOT / "data" / "outputs" / "data" / "cement_bom.csv"      # per-ton raw-material ratios by type
HEADLINE_MATERIALS = ["Clinker", "Gypsum", "Limestone", "Slag"]


def cement_type(name):
    n = str(name).upper()
    return "CEM-II" if "CEM-II" in n else "OPC" if "OPC" in n else "PCC" if ("PCC" in n or "PPC" in n) else "oth"


DOW_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DEFAULT_TRUCK_MT = 15.0


def dispatch_profile():
    """National day-of-week dispatch weights (mean=1) from the daily delivery history — for spreading the
    sales target into day-wise truck loads."""
    d = pd.read_parquet(CEMENT_DATA)
    d["Delivery_Date"] = pd.to_datetime(d["Delivery_Date"], errors="coerce")
    g = d.groupby(d["Delivery_Date"].dt.day_name())["DelQtyMT"].sum().reindex(DOW_ORDER).fillna(0)
    w = g / g.mean()
    return {k: round(float(v), 4) for k, v in w.items()}


def monthly_history():
    """Completed-month ACCL cement delivery volume by calendar month (YYYY-MM -> MT).
    Lets the page show a material's PAST need (volume x recipe) beside the FUTURE plan for any month.
    Drops the in-progress current month so a partial month is never charted as an actual."""
    d = pd.read_parquet(CEMENT_DATA)
    d["Delivery_Date"] = pd.to_datetime(d["Delivery_Date"], errors="coerce")
    m = d.groupby(d["Delivery_Date"].dt.to_period("M"))["DelQtyMT"].sum()
    cur = pd.Timestamp.today().to_period("M")
    m = m[m.index < cur]                       # only fully-elapsed months are "actual"
    return {str(p): round(float(v), 1) for p, v in m.items()}


def production_ratios():
    """Blended raw-material tonnes per tonne of ACCL cement, = cement-type mix x per-type BOM ratios.
    Turns a sales-volume target into a raw-material requirement (clinker/gypsum/limestone/slag)."""
    d = pd.read_parquet(CEMENT_DATA)
    d["ct"] = d["Item_Name"].map(cement_type)
    mix = d.groupby("ct")["DelQtyMT"].sum()
    mix = (mix / mix.sum())
    piv = pd.read_csv(BOM).pivot(index="cement_type", columns="material", values="qty_per_ton")
    blended, by_type = {}, {}
    for m in HEADLINE_MATERIALS:
        tot = 0.0
        for t, sh in mix.items():
            if t in piv.index and m in piv.columns and pd.notna(piv.loc[t, m]):
                tot += float(sh) * float(piv.loc[t, m])
        blended[m] = round(tot, 5)
    for t in ("OPC", "PCC", "CEM-II"):
        by_type[t] = {m: (round(float(piv.loc[t, m]), 4)
                          if t in piv.index and m in piv.columns and pd.notna(piv.loc[t, m]) else 0.0)
                      for m in HEADLINE_MATERIALS}
    return {"type_mix": {k: round(float(v), 4) for k, v in mix.items() if k in ("OPC", "PCC", "CEM-II")},
            "blended_ratio_per_ton": blended, "by_type_ratio": by_type}

ACCL_GROUP = "Akij"
DEFAULT_CAGR_WINDOW = 3      # years (recent) — adjustable in UI
DEFAULT_TARGET_SHARE = None  # None => hold latest actual share


def main():
    d = pd.read_excel(SRC, sheet_name="Cement Sales Master Data")
    d["Date"] = pd.to_datetime(d["Date"], errors="coerce")

    # ---- annual national market + ACCL, full years only (drop partial current year) ----
    months_per_year = d.groupby("Year")["Date"].apply(lambda s: s.dt.to_period("M").nunique())
    full_years = sorted(y for y in months_per_year.index if months_per_year[y] >= 12)
    nat = (d.groupby("Year")["Sales_In_MT"].sum() / 1e6)                        # M MT
    accl = (d[d["Company_Group"] == ACCL_GROUP].groupby("Year")["Sales_In_MT"].sum() / 1e6)
    accl = accl.reindex(nat.index).fillna(0.0)
    share = (accl / nat * 100)

    latest = full_years[-1]                                                     # base year for projection
    latest_market = float(nat[latest])
    latest_accl = float(accl[latest])
    latest_share = float(share[latest])

    # ---- CAGR windows ----
    def cagr(series, a, b):
        return ((series[b] / series[a]) ** (1 / (b - a)) - 1) * 100 if b > a and series[a] > 0 else 0.0

    windows = {}
    for w in (3, 5, latest - full_years[0]):
        a = latest - w
        if a in nat.index:
            windows[f"{w}yr"] = round(cagr(nat, a, latest), 2)
    default_cagr = windows.get(f"{DEFAULT_CAGR_WINDOW}yr", list(windows.values())[0])

    # ---- ACCL recent trend (do-nothing baseline) = ACCL CAGR over same default window ----
    a = latest - DEFAULT_CAGR_WINDOW
    accl_trend_cagr = cagr(accl, a, latest) if a in accl.index else 0.0

    # ---- seasonality (mean=1) ----
    seas = L.national_seasonality()

    # ---- default target: hold latest share, grow with market ----
    target_share = DEFAULT_TARGET_SHARE if DEFAULT_TARGET_SHARE else latest_share
    market_next = latest_market * (1 + default_cagr / 100)
    target_accl = market_next * target_share / 100
    baseline_accl = latest_accl * (1 + accl_trend_cagr / 100)                   # if the decline/trend continues

    # monthly split of the annual target (calendar months Jul..next Jun style not needed — 12 rolling)
    sidx = np.array([seas.get(m, 1.0) for m in range(1, 13)])
    sidx = sidx / sidx.sum()
    monthly = [round(target_accl * 1e6 * f, 0) for f in sidx]                   # MT

    payload = {
        "source": "National Sales Data_Cement.xlsx (actual national brand panel)",
        "latest_full_year": latest,
        "latest_market_mmt": round(latest_market, 2),
        "latest_accl_mmt": round(latest_accl, 3),
        "latest_share_pct": round(latest_share, 2),
        "cagr_windows": windows,
        "default_cagr_window_yr": DEFAULT_CAGR_WINDOW,
        "default_cagr_pct": default_cagr,
        "accl_trend_cagr_pct": round(accl_trend_cagr, 2),
        "default_target_share_pct": round(target_share, 2),
        "market_next12_mmt": round(market_next, 2),
        "target_accl_next12_mmt": round(target_accl, 3),
        "baseline_accl_next12_mmt": round(baseline_accl, 3),
        "gap_vs_baseline_mmt": round(target_accl - baseline_accl, 3),
        "monthly_target_mt": monthly,
        "seasonality": {int(k): round(v, 3) for k, v in seas.items()},
        # yearly series for the chart + live recompute
        "years": [int(y) for y in nat.index],
        "market_mmt": [round(float(v), 3) for v in nat.values],
        "accl_mmt": [round(float(v), 3) for v in accl.values],
        "share_pct": [round(float(v), 2) for v in share.values],
        "full_years": [int(y) for y in full_years],
        # production link: raw materials per tonne of cement sold (for the share-lever -> materials chain)
        "production": production_ratios(),
        # dispatch link: day-of-week weights + truck size (for the share-lever -> day-wise trucks chain)
        "dispatch": {"dow_profile": dispatch_profile(), "default_truck_mt": DEFAULT_TRUCK_MT,
                     "dow_order": DOW_ORDER},
        # actual ACCL monthly cement volume (completed months) -> past vs plan per material/month
        "accl_monthly_history": monthly_history(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload), encoding="utf-8")

    print(f"market_target.json -> {OUT}")
    print(f"latest full year {latest}: market {latest_market:.1f}M, ACCL {latest_accl:.2f}M ({latest_share:.2f}%)")
    print(f"CAGR windows: {windows} | default {DEFAULT_CAGR_WINDOW}yr = {default_cagr:.1f}%")
    print(f"ACCL trend (do-nothing): {accl_trend_cagr:+.1f}%/yr -> baseline {baseline_accl:.2f}M")
    print(f"TARGET (hold {target_share:.2f}% share, market +{default_cagr:.1f}%): "
          f"market {market_next:.1f}M -> ACCL {target_accl:.2f}M | gap vs baseline {target_accl-baseline_accl:+.2f}M")


if __name__ == "__main__":
    main()
