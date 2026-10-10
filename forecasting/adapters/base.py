"""Generic tabular source adapter.

Converts any source described in the SBU registry to one standard long frame:
    sbu, source, channel, zone, client, client_key, district, manager, am,
    month (Period[M]), date, y (MT), value, opening, collection, closing,
    provisional_flag
The adapter is config-driven (column_map, header_row, key_style, sheet) so a new source is a registry
entry, not new code. Raw files are opened read-only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}

STANDARD_COLUMNS = ["sbu", "source", "channel", "zone", "client", "client_key", "district",
                    "manager", "am", "month", "date", "y", "value", "opening", "collection",
                    "closing", "provisional_flag"]


def norm_name(s):
    if pd.isna(s):
        return pd.NA
    return re.sub(r"\s+", " ", str(s).strip()).lower()


def _strip_loc_suffix(name, loc_tokens):
    if pd.isna(name):
        return pd.NA
    s = str(name).strip()
    m = re.match(r"^(.*?)\s*[-\u2013]\s*([A-Za-z\.' ]+)$", s)
    if m and " " not in m.group(2).strip() and re.sub(r"[^a-z]", "", m.group(2).lower()) in loc_tokens:
        return m.group(1).strip()
    return s


@dataclass
class LocationGazetteer:
    """Districts/upazilas used to strip territory suffixes for Trade-style keys."""
    tokens: set

    @classmethod
    def from_frame(cls, df, cols=("district",)):
        toks = set()
        for c in cols:
            if c in df:
                for v in df[c].dropna().unique():
                    toks.add(re.sub(r"[^a-z]", "", str(v).lower()))
        return cls(toks)


def read_raw(source_cfg, base_dir) -> pd.DataFrame:
    path = base_dir / source_cfg["file"]
    header = source_cfg.get("header_row", 1) - 1
    if str(path).lower().endswith(".csv"):
        df = pd.read_csv(path, header=header)
    else:
        df = pd.read_excel(path, sheet_name=source_cfg.get("sheet"), header=header)
    # drop trailing junk columns from the export
    df = df.loc[:, [c for c in df.columns if not str(c).startswith("Unnamed")]]
    # optional row filter: one consolidated file can back multiple named sources
    f = source_cfg.get("filter")
    if f:
        df = df[df[f["column"]] == f["value"]]
    return df


def to_standard(raw: pd.DataFrame, source_cfg, sbu_id: str, gaz: LocationGazetteer | None = None) -> pd.DataFrame:
    cm = source_cfg["column_map"]
    out = pd.DataFrame(index=raw.index)
    out["sbu"] = sbu_id
    out["source"] = source_cfg["name"]
    out["date"] = pd.to_datetime(raw[cm["date"]], errors="coerce")
    out["channel"] = raw[cm["channel"]].astype("string") if "channel" in cm else pd.NA
    out["zone"] = raw[cm["zone"]].astype("string") if "zone" in cm else pd.NA
    out["client"] = raw[cm["client"]].astype("string")
    out["district"] = raw[cm["district"]].astype("string") if "district" in cm else pd.NA
    out["manager"] = raw[cm["manager"]].astype("string") if "manager" in cm else pd.NA
    out["am"] = raw[cm["am"]].astype("string") if "am" in cm else pd.NA
    out["y"] = pd.to_numeric(raw[cm["quantity"]], errors="coerce") if "quantity" in cm else np.nan
    out["value"] = pd.to_numeric(raw[cm["value"]], errors="coerce") if "value" in cm else np.nan
    out["opening"] = pd.to_numeric(raw[cm["opening"]], errors="coerce") if "opening" in cm else np.nan
    out["collection"] = pd.to_numeric(raw[cm["collection"]], errors="coerce") if "collection" in cm else np.nan
    out["closing"] = pd.to_numeric(raw[cm["closing"]], errors="coerce") if "closing" in cm else np.nan

    # junk rows: unparseable dates / 1970 sentinel
    out = out[out.date.notna() & (out.date.dt.year != 1970)].copy()
    out["month"] = out.date.dt.to_period("M")

    # client_key
    if source_cfg.get("key_style") == "name_plus_district":
        toks = gaz.tokens if gaz else set()
        base = out.client.map(lambda s: _strip_loc_suffix(s, toks)).map(norm_name)
        dist = out.district.map(lambda s: re.sub(r"[^a-z]", "", str(s).lower()) if pd.notna(s) else "")
        out["client_key"] = base.fillna("") + " || " + dist
    else:
        out["client_key"] = out.client.map(norm_name)

    # approved case-only merge (ABIR/Abir) applied where it occurs
    out.loc[out.client.map(norm_name) == "abir enterprise", "client_key"] = "abir enterprise"

    # drop exact duplicates (DQ-05); remaining grain duplicates are aggregated later
    out = out.drop_duplicates()

    out["provisional_flag"] = False
    return out[STANDARD_COLUMNS].reset_index(drop=True)


def load_source(sbu_id: str, source_cfg, base_dir) -> pd.DataFrame:
    raw = read_raw(source_cfg, base_dir)
    gaz = None
    if source_cfg.get("key_style") == "name_plus_district":
        # build the gazetteer from this file's own geography columns
        geo = read_raw(source_cfg, base_dir)
        cm = source_cfg["column_map"]
        gaz = LocationGazetteer.from_frame(
            pd.DataFrame({"district": geo[cm["district"]]}) if "district" in cm else geo, ["district"])
    return to_standard(raw, source_cfg, sbu_id, gaz)
