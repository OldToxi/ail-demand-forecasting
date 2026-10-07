"""Explode the published cement DEMAND forecast into a PRODUCTION material plan (clinker + raw materials).

This is the deterministic derivation layer of the integrated planning chain:
    Demand forecast (per finished cement item, P10/P50/P90)
        -> convert to bulk-ton equivalent  (bag = 50 kg = 0.05 t; bulk = as-is)
        -> BOM explosion (outputs/data/cement_bom.csv, per-ton grinding recipe by cement type)
        -> monthly requirement of Clinker / Gypsum / Limestone / Slag / Grinding Aid  (+ empty bags)

No new forecasting happens here — every quantile is a linear function of the demand quantile, so the
P10/P50/P90 band propagates straight through. (Linear propagation ignores cross-item diversification, so
the material band is intentionally conservative — same caveat the app already states for portfolio bands.)

Inputs : outputs/data/final_quantity_forecast.parquet   (the published demand release)
         outputs/data/cement_bom.csv                    (built by build_cement_bom.py)
Outputs: outputs/data/production_material_forecast.csv  (unit x material x month, P10/P50/P90)
         outputs/data/production_material_by_type.csv   (material x cement_type annual contribution)

Run: python scripts/build_cement_bom.py && python scripts/build_production_plan.py
"""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]                # planning-app/
DATA = ROOT / "data" / "outputs" / "data"
INTERIM = ROOT / "data" / "interim"
FC = INTERIM / "final_quantity_forecast.parquet"          # the published demand release (input)
HIST = INTERIM / "item_monthly_panel.parquet"            # actual cement SALES history (the past line)
BOM = DATA / "cement_bom.csv"
OUT_MAT = DATA / "production_material_forecast.csv"
OUT_TYPE = DATA / "production_material_by_type.csv"
OUT_META = DATA / "production_plan_meta.json"
OUT_PROC = DATA / "procurement_material_plan.csv"   # procurement-ready export (clean headers + annual)
OUT_HIST = DATA / "production_material_history.csv"  # past requirement = sales history x BOM
HIST_MONTHS = 24                                     # months of history to show on the plot

KG_PER_BAG = 50.0
TON_PER_BAG = KG_PER_BAG / 1000.0            # 0.05 t — confirmed by BOM numLotSize=20 (20 bags/ton)
CEMENT_UNIT_ID = 4                            # Akij Cement Company Ltd. (ACCL)
Z = 1.2816                                   # z-score for the P10/P90 (10th/90th) band
RHO = 0.0                                    # assumed cross-item uncertainty correlation (0 = risk-pooling)

# clinker is called out separately (it drives the make-vs-buy decision); bags are packaging, not RM.
CATEGORY = {"Clinker": "clinker", "Gypsum": "raw_material", "Limestone": "raw_material",
            "Slag": "raw_material", "Grinding Aid": "raw_material", "Empty Cement Bags": "packaging"}


def cement_type(name: str) -> str:
    n = name.upper()
    if "CEM-II" in n:
        return "CEM-II"
    if "OPC" in n:
        return "OPC"
    if "PCC" in n or "PPC" in n:
        return "PCC"
    return "OTHER"


def demand_fingerprint(fc: "pd.DataFrame") -> str:
    """Content hash of the cement demand forecast (item x month x P10/P50/P90). Changes iff the demand
    that feeds production changes — the anchor for detecting demand->production drift."""
    import hashlib
    c = fc[fc.Unit_ID == CEMENT_UNIT_ID].sort_values(["item_key", "month"])
    payload = c[["item_key", "month", "P10", "P50", "P90"]].round(3).to_csv(index=False)
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


def main() -> None:
    fc = pd.read_parquet(FC)
    bom = pd.read_csv(BOM)

    cement = fc[fc.Unit_ID == CEMENT_UNIT_ID].copy()
    cement["cement_type"] = cement.Item_Name.map(cement_type)
    cement["is_bag"] = cement.Base_UoM.str.lower().eq("bag")
    # bulk-ton equivalent of demand, per quantile
    for q in ("P10", "P50", "P90"):
        cement[f"tons_{q}"] = cement[q] * cement.is_bag.map({True: TON_PER_BAG, False: 1.0})

    unmatched = sorted(set(cement.cement_type) - set(bom.cement_type) - {"OTHER"})
    if unmatched:
        print(f"  ! warning: cement types with no BOM recipe (skipped): {unmatched}")
    dropped = cement[cement.cement_type == "OTHER"].Item_Name.unique()
    if len(dropped):
        print(f"  ! warning: items not classified to a cement type (skipped): {list(dropped)}")

    # ---- explode: demand tons x per-ton recipe -> per-item material contribution (the "cells") ----
    merged = cement.merge(bom, on="cement_type", how="inner")
    for q in ("P10", "P50", "P90"):
        merged[q] = merged[f"tons_{q}"] * merged.qty_per_ton
    rm_cells = merged.assign(uom="Ton")[["material", "month", "uom", "P10", "P50", "P90"]]
    # empty bags: one bag per bag produced (packaging, counted in bags)
    bag_cells = (cement[cement.is_bag].assign(material="Empty Cement Bags", uom="Bag")
                 [["material", "month", "uom", "P10", "P50", "P90"]])
    cells = pd.concat([rm_cells, bag_cells], ignore_index=True)
    cells["category"] = cells.material.map(CATEGORY).fillna("raw_material")

    # ---- aggregate cells into a band. Two views on the same expected value (sum of item P50s):
    #   * worst-case (p*_wc): sum the item quantiles — assumes ALL items hit their extreme together
    #     (comonotonic). Correct only if demands are perfectly correlated; here far too wide.
    #   * diversification-aware (p10/p90): pool VARIANCE across items, not quantiles — the inventory
    #     "square-root law". Pool the DOWNSIDE (P50-P10) and UPSIDE (P90-P50) spreads SEPARATELY so the
    #     band is asymmetric: for these lumpy items the upside (P90>>P50) is huge but the downside is
    #     modest, so a single symmetric sigma would drag the lower bound to 0. Seasonal co-movement lives
    #     in the P50; residual SKU uncertainty is ~independent, so RHO defaults to 0.
    def _pool(spread):  # sqrt of pooled variance (independence + RHO cross terms), in sigma units
        s = spread / Z
        return (float((s ** 2).sum()) + RHO * (float(s.sum()) ** 2 - float((s ** 2).sum()))) ** 0.5

    def agg_band(g: pd.DataFrame) -> pd.Series:
        p50 = float(g.P50.sum())
        sd_lo = _pool((g.P50 - g.P10).clip(lower=0))
        sd_hi = _pool((g.P90 - g.P50).clip(lower=0))
        return pd.Series({"p10": max(0.0, p50 - Z * sd_lo), "p50": p50, "p90": p50 + Z * sd_hi,
                          "p10_wc": float(g.P10.sum()), "p90_wc": float(g.P90.sum())})

    keys = ["category", "material", "uom", "month"]
    mat = cells.groupby(keys, as_index=False).apply(agg_band, include_groups=False)
    mat["unit_id"] = CEMENT_UNIT_ID
    mat["unit_name"] = "Akij Cement Company Ltd."
    mat = mat.sort_values(["category", "material", "month"]).reset_index(drop=True)
    mat = mat[["unit_id", "unit_name", "material", "category", "uom", "month",
               "p10", "p50", "p90", "p10_wc", "p90_wc"]]
    mat.to_csv(OUT_MAT, index=False)
    # annual per material, diversification-aware over ALL item x month cells (not a sum of monthly bands)
    annual_band = (cells.groupby(["category", "material", "uom"], as_index=False)
                   .apply(agg_band, include_groups=False))

    # ---- procurement-ready export: month x material, Low/Expected/High (diversification-aware) +
    #      worst-case Low/High + annual totals. Annual band is computed over all cells (NOT summed
    #      monthly bands — variances don't add that way). ----
    ren = {"p10": "low", "p50": "expected", "p90": "high", "p10_wc": "low_worstcase", "p90_wc": "high_worstcase"}
    cols = ["month", "category", "material", "uom", "low", "expected", "high", "low_worstcase", "high_worstcase"]
    proc = mat.rename(columns=ren)[["month", "category", "material", "uom",
                                    "low", "expected", "high", "low_worstcase", "high_worstcase"]]
    annual = annual_band.rename(columns=ren).assign(month="ANNUAL TOTAL")[cols]
    proc = pd.concat([proc, annual], ignore_index=True)
    for c in ("low", "expected", "high", "low_worstcase", "high_worstcase"):
        proc[c] = proc[c].round(0).astype("int64")
    cat_ord = {"clinker": 0, "raw_material": 1, "packaging": 2}
    proc["_c"] = proc.category.map(cat_ord).fillna(9)
    proc["_m"] = proc.month.eq("ANNUAL TOTAL")   # annual rows last within each material block
    proc = (proc.sort_values(["_c", "material", "_m", "month"]).drop(columns=["_c", "_m"]))
    proc.to_csv(OUT_PROC, index=False)

    # ---- annual contribution by cement type (for the UI drill-down) ----
    by_type = (merged.groupby(["material", "cement_type"], as_index=False)["P50"].sum()
               .rename(columns={"P50": "annual_p50"}))
    by_type["annual_p50"] = by_type.annual_p50.round(2)
    by_type.to_csv(OUT_TYPE, index=False)

    # ---- PAST: actual material requirement = cement SALES history x BOM (same derivation as the forecast,
    #      so the past line joins the future band on one consistent basis). Sales is the reliable anchor;
    #      the raw production file is quarantined (see PRODUCTION_DATA_RECONCILIATION_PROPOSAL). ----
    _build_history(bom)

    # ---- headline meta (cement demand + annual bands + note) so the API stays self-contained ----
    import json
    tot_cement_tons = float(cement["tons_P50"].sum())
    months = sorted(mat.month.unique())
    annual = {r.material: {"p10": round(float(r.p10), 1), "p50": round(float(r.p50), 1),
                           "p90": round(float(r.p90), 1), "p10_wc": round(float(r.p10_wc), 1),
                           "p90_wc": round(float(r.p90_wc), 1)}
              for r in annual_band.itertuples()}
    meta = {
        "unit_id": CEMENT_UNIT_ID, "unit_name": "Akij Cement Company Ltd.",
        "months": months, "horizon_months": len(months),
        "cement_demand_tons_p50": round(tot_cement_tons, 1),
        "bag_to_ton": TON_PER_BAG, "source_release": FC.name, "band_rho": RHO,
        # provenance stamp: ties this plan to the exact demand forecast it was built from. The API + the
        # verify script use it to detect drift (demand changed but production not rebuilt). See
        # scripts/verify_production_link.py — the guardrail that keeps demand->production coupled.
        "source_forecast_fingerprint": demand_fingerprint(fc),
        "source_forecast_mtime": FC.stat().st_mtime if FC.exists() else 0,
        "built_at": pd.Timestamp.now().isoformat(timespec="seconds"),
        "annual": annual,
        "note": ("Materials are derived from the published demand forecast by BOM explosion — no separate "
                 "forecast. The Low/High band is diversification-aware (variance pooling across products, "
                 "the inventory square-root law); a wider worst-case band assumes all products move together."),
    }
    OUT_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # ---- summary + sanity check vs recent actual production ----
    print(f"\nproduction_material_forecast.csv -> {OUT_MAT}  ({len(mat)} rows)  [band RHO={RHO}]")
    print(f"12-month cement demand (bulk-ton equiv, P50): {tot_cement_tons:,.0f} t")
    print("Annual material requirement — Expected [diversification-aware Low..High] (worst-case Low..High):")
    for r in annual_band.sort_values("p50", ascending=False).itertuples():
        print(f"  {r.material:20s} {r.p50:>13,.0f} {r.uom:4s} "
              f"[{r.p10:>11,.0f} .. {r.p90:>13,.0f}]  (wc {r.p10_wc:,.0f} .. {r.p90_wc:,.0f})")
    _sanity_vs_production(tot_cement_tons)


def _build_history(bom: pd.DataFrame) -> None:
    """Explode cement sales history through the BOM -> monthly actual material requirement (last N months)."""
    if not HIST.exists():
        print("  ! history panel not found; skipping past series"); return
    h = pd.read_parquet(HIST)
    h = h[h.Unit_ID == CEMENT_UNIT_ID].copy()
    h["cement_type"] = h.Item_Name.map(cement_type)
    h["is_bag"] = h.Base_UoM.str.lower().eq("bag")
    h["month"] = pd.to_datetime(h["date"]).dt.strftime("%Y-%m")
    h["tons"] = h.qty * h.is_bag.map({True: TON_PER_BAG, False: 1.0})
    # raw materials
    hm = h.merge(bom, on="cement_type", how="inner")
    hm["actual"] = hm.tons * hm.qty_per_ton
    rm = hm.groupby(["material", "month"], as_index=False)["actual"].sum().assign(uom="Ton")
    # empty bags
    bg = (h[h.is_bag].groupby("month", as_index=False)["qty"].sum()
          .rename(columns={"qty": "actual"}).assign(material="Empty Cement Bags", uom="Bag"))
    hist = pd.concat([rm, bg[["material", "month", "actual", "uom"]]], ignore_index=True)
    hist["category"] = hist.material.map(CATEGORY).fillna("raw_material")
    keep = sorted(hist.month.unique())[-HIST_MONTHS:]
    hist = hist[hist.month.isin(keep)].sort_values(["category", "material", "month"])
    hist = hist[["material", "category", "uom", "month", "actual"]]
    hist["actual"] = hist.actual.round(1)
    hist.to_csv(OUT_HIST, index=False)
    print(f"production_material_history.csv -> {OUT_HIST}  ({len(hist)} rows, last {len(keep)} months)")


def _sanity_vs_production(demand_tons: float) -> None:
    """Reasonableness check: does demand-implied cement volume line up with recent production?"""
    src = ROOT / "data" / "raw" / "Itemwise Production.xlsx"
    if not src.exists():
        return
    p = pd.read_excel(src, parse_dates=["dteProductionDate"])
    p = p[p.strItemName.notna()].copy()
    p["ton"] = p.apply(lambda r: r.numQuantity / 20 if r.strUOMName == "Bag" else r.numQuantity, axis=1)
    last12 = p[p.dteProductionDate >= p.dteProductionDate.max() - pd.Timedelta(days=365)]
    prod_tons = last12.ton.sum()
    ratio = demand_tons / prod_tons if prod_tons else float("nan")
    print(f"\nSanity vs actual production (last 12 mo): produced ~{prod_tons:,.0f} t cement; "
          f"demand forecast ~{demand_tons:,.0f} t  (demand/production = {ratio:.2f}).")
    if ratio < 0.5 or ratio > 1.5:
        print("  ! NOTE: demand and production volumes diverge materially. The explosion is correct for "
              "whatever demand is fed in, but the demand panel (anonymised sales items) appears to cover a "
              "different cement volume than plant output — a reconciliation item to raise, not a bug here.")


if __name__ == "__main__":
    main()
