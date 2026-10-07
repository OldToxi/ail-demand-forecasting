"""Build a clean, auditable cement BOM artifact from the raw ERP export.

Input : Production/Bom.xlsx  (ERP BOM dump, ~90 versioned BOMs for the cement family)
Output: outputs/data/cement_bom.csv  (one row per cement_type x raw material, qty per 1 Ton of bulk cement)

Modeling decisions (documented so a future worker can audit them):
  * The published grinding recipe is the BULK BOM that contains 'Cement Clinker' as a component.
    Bag BOMs are just (1 bulk-ton-equivalent + empty bags) so they carry no new RM information — we
    explode bags via the bulk recipe + a 50 kg/bag conversion in build_production_plan.py.
  * When an item has several versioned BOMs over time, we take the LATEST (max intBillOfMaterialId) —
    that is the recipe currently in force.
  * Component ratios already embed wastage/loss (they sum to ~1.03 per ton), so we keep them raw.
  * Materials are canonicalised to short names for display; the raw ERP name is kept for traceability.

Run: python scripts/build_cement_bom.py
"""
from pathlib import Path
import re
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]               # planning-app/
SRC = ROOT / "data" / "raw" / "Bom.xlsx"
OUT = ROOT / "data" / "outputs" / "data" / "cement_bom.csv"

CLINKER = "Cement Clinker"

# cement_type is what we join demand -> BOM on. Derived from the finished-good name.
def cement_type(name: str) -> str:
    n = name.upper()
    if "CEM-II" in n:
        return "CEM-II"
    if "OPC" in n:
        return "OPC"
    if "PCC" in n or "PPC" in n:
        return "PCC"
    return "OTHER"

# raw ERP component name -> (canonical material, is_raw_material). Empty bags handled separately downstream.
MATERIAL_CANON = {
    "Cement Clinker": "Clinker",
    "Gypsum": "Gypsum",
    'Lime Stone 3/4"': "Limestone",
    "Slag Blast Furnesh": "Slag",
    "Grinding Aid (Cement Additives)": "Grinding Aid",
}


def main() -> None:
    bom = pd.read_excel(SRC)
    # bulk grinding recipes = BOMs whose finished good is a *Bulk* cement AND that list clinker
    bulk_ids = bom.loc[bom["strItemName"].str.contains("Bulk", case=False, na=False)
                       & (bom["strItemName1"] == CLINKER), "intBillOfMaterialId"].unique()
    bulk = bom[bom["intBillOfMaterialId"].isin(bulk_ids)].copy()
    bulk["cement_type"] = bulk["strItemName"].map(cement_type)

    rows = []
    for ctype, grp in bulk.groupby("cement_type"):
        latest = grp["intBillOfMaterialId"].max()          # current recipe in force
        recipe = grp[grp["intBillOfMaterialId"] == latest]
        src_name = recipe["strItemName"].iloc[0]
        for _, r in recipe.iterrows():
            raw = str(r["strItemName1"]).strip()
            canon = MATERIAL_CANON.get(raw)
            if canon is None:                              # skip non-RM lines (e.g. bags/SFG) if any slip in
                continue
            rows.append({
                "cement_type": ctype,
                "material": canon,
                "qty_per_ton": round(float(r["numQuantity"]), 6),
                "raw_material_name": raw,
                "source_bom_id": int(latest),
                "source_bom_name": src_name,
            })

    out = pd.DataFrame(rows).sort_values(["cement_type", "material"]).reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)

    print(f"cement_bom.csv written -> {OUT}  ({len(out)} rows)")
    for ctype, g in out.groupby("cement_type"):
        tot = g["qty_per_ton"].sum()
        print(f"  {ctype:8s} (BOM {g.source_bom_id.iloc[0]}): "
              + ", ".join(f"{m}={q:.4f}" for m, q in zip(g.material, g.qty_per_ton))
              + f"  [sum={tot:.4f}]")


if __name__ == "__main__":
    main()
