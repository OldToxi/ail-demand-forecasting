"""Forecast Value Added: statistical vs planner-adjusted WAPE per series and per planner, once actuals exist.

No real adjustments exist yet - this is exercised by a unit test with synthetic adjustments.
"""
from __future__ import annotations

import pandas as pd


def forecast_value_added(records: list[dict]) -> pd.DataFrame:
    """records: [{series_id, month, statistical, adjusted, actual, entered_by}].

    Returns per (series_id, entered_by) rows plus a small summary of adjusted-vs-statistical WAPE.
    """
    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=["series_id", "entered_by", "wape_statistical", "wape_adjusted", "n"])
    out = []
    for (sid, who), g in df.groupby(["series_id", "entered_by"], dropna=False):
        denom = g["actual"].abs().sum()
        ws = (g["statistical"] - g["actual"]).abs().sum() / max(denom, 1)
        wa = (g["adjusted"] - g["actual"]).abs().sum() / max(denom, 1)
        out.append({"series_id": sid, "entered_by": who, "wape_statistical": round(float(ws), 4),
                    "wape_adjusted": round(float(wa), 4), "n": int(len(g)),
                    "fva_improvement": round(float(ws - wa), 4)})
    return pd.DataFrame(out)
