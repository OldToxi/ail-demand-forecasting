"""Load + clean ACCL sales into a district-month cement panel. Reads ONLY the Demand Planning folder
(+ the existing national panel for seasonality). Nothing here touches the forecast/production pipeline.
"""
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]          # planning-app/
DP = ROOT / "data" / "raw"
DELIV_PARQUET = DP / "cement_data.parquet"          # built once from cement_data_date_wise.xlsx
DELIV_XLSX = DP / "cement_data_date_wise.xlsx"
DIM = DP / "DimBusinessPartner.csv"
NATIONAL_PANEL = ROOT / "data" / "interim" / "item_monthly_panel.parquet"

# districts we know (for name-based recovery of unmapped dealers)
from reference_data import DISTRICT_POP_2022  # noqa: E402
KNOWN_DISTRICTS = list(DISTRICT_POP_2022)
# common ERP spelling -> census spelling
DISTRICT_ALIASES = {
    "comilla": "Cumilla", "cumilla": "Cumilla", "jessore": "Jashore", "jashore": "Jashore",
    "bogra": "Bogura", "bogura": "Bogura", "barisal": "Barishal", "barishal": "Barishal",
    "chittagong": "Chattogram", "chattogram": "Chattogram", "b-baria": "Brahmanbaria",
    "brahmanbaria": "Brahmanbaria", "b.baria": "Brahmanbaria", "nawabganj": "Chapainawabganj",
    "chapainawabgonj": "Chapainawabganj", "chapainawabganj": "Chapainawabganj",
    "netrokona": "Netrokona", "moulvibazar": "Moulvibazar", "maulvibazar": "Moulvibazar",
    "cox'sbazar": "Cox's Bazar", "coxsbazar": "Cox's Bazar", "gopalgonj": "Gopalganj",
    "kishoregonj": "Kishoreganj", "sirajgonj": "Sirajganj", "narayangonj": "Narayanganj",
}


def _norm(s):
    return re.sub(r"[^a-z]", "", str(s).lower())


_LOOKUP = {}
for d in KNOWN_DISTRICTS:
    _LOOKUP[_norm(d)] = d
for a, d in DISTRICT_ALIASES.items():
    _LOOKUP[_norm(a)] = d


def _district_from_text(text):
    """Recover a district by scanning a free-text name/address for a known district token."""
    if not isinstance(text, str):
        return None
    t = _norm(text)
    for key, dist in _LOOKUP.items():
        if key in t:
            return dist
    return None


def load_deliveries():
    """Clean cement deliveries with a district on every row where recoverable. Returns a line-level frame."""
    if DELIV_PARQUET.exists():
        d = pd.read_parquet(DELIV_PARQUET)
    else:
        d = pd.read_excel(DELIV_XLSX, sheet_name="Cement Data")
        d.to_parquet(DELIV_PARQUET)
    d["Delivery_Date"] = pd.to_datetime(d["Delivery_Date"], errors="coerce")
    d = d[d["Item_Name"].astype(str).str.contains("Cement", na=False)].copy()   # cement only
    d = d[d["DelQtyMT"] > 0]
    d["month"] = d["Delivery_Date"].dt.to_period("M")

    # dealer master -> district
    dim = pd.read_csv(DIM, low_memory=False)[
        ["intBusinessPartnerId", "strDistrictName", "strDivisionName", "strCustomerType",
         "ExclusivityType", "strPartyStatus"]]
    dim["district_master"] = dim["strDistrictName"].map(
        lambda x: _LOOKUP.get(_norm(x)) if pd.notna(x) else None)
    d = d.merge(dim, left_on="Customer_ID", right_on="intBusinessPartnerId", how="left")

    # recover district for unmapped: from customer name, then territory
    need = d["district_master"].isna()
    d.loc[need, "district_name"] = d.loc[need, "Customer_Name"].map(_district_from_text)
    d["district"] = d["district_master"].fillna(d.get("district_name"))
    still = d["district"].isna()
    d.loc[still, "district"] = d.loc[still, "Territory"].map(_district_from_text)

    # cement type
    up = d["Item_Name"].str.upper()
    d["cement_type"] = np.where(up.str.contains("CEM-II"), "CEM-II",
                        np.where(up.str.contains("OPC"), "OPC", "PCC"))
    d["is_bulk"] = d["Item_Name"].str.contains("Bulk", na=False)
    return d


def district_month_mt(d):
    """District x month delivered MT (mapped rows only). Institutional/unmapped kept separately."""
    mapped = d[d["district"].notna()]
    dm = (mapped.groupby(["district", "month"])["DelQtyMT"].sum().reset_index()
          .rename(columns={"DelQtyMT": "mt"}))
    return dm


def coverage_report(d):
    tot = d["DelQtyMT"].sum()
    mapped = d.loc[d["district"].notna(), "DelQtyMT"].sum()
    by_master = d.loc[d["district_master"].notna(), "DelQtyMT"].sum()
    return {"total_mt": tot, "mapped_mt": mapped, "mapped_pct": mapped / tot,
            "master_pct": by_master / tot, "n_districts": int(d["district"].nunique()),
            "unmapped_mt": tot - mapped}


def national_seasonality():
    """Monthly seasonal index (mean=1.0) from the 57-month national cement panel (Unit 4)."""
    if not NATIONAL_PANEL.exists():
        return {m: 1.0 for m in range(1, 13)}
    h = pd.read_parquet(NATIONAL_PANEL)
    c = h[h.Unit_ID == 4].copy()
    c["date"] = pd.to_datetime(c["date"])
    c["ton"] = np.where(c.Base_UoM.str.lower().eq("bag"), c.qty * 0.05, c.qty)
    monthly = c.groupby(c.date.dt.to_period("M")).ton.sum()
    monthly = monthly[monthly > 0]
    df = monthly.reset_index(); df["m"] = df["date"].dt.month
    idx = df.groupby("m").ton.mean()
    idx = idx / idx.mean()
    return {int(k): float(v) for k, v in idx.items()}
