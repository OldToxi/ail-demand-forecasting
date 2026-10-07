"""Planner adjustments via a CSV/Excel upload template (no POST endpoint).

Template columns: series_id, month (YYYY-MM), adjusted_forecast_mt, reason (mandatory), entered_by.
The pipeline validates uploads and stores statistical vs adjusted side by side; it never overwrites the
statistical forecast and never feeds adjustments into training.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import config

TEMPLATE = config.FORECASTING_DIR / "templates" / "planner_adjustments_template.csv"
COLUMNS = ["series_id", "month", "adjusted_forecast_mt", "reason", "entered_by"]


def write_template():
    TEMPLATE.parent.mkdir(parents=True, exist_ok=True)
    example = pd.DataFrame([
        {"series_id": "AIL|sbu|external", "month": "2026-10", "adjusted_forecast_mt": 12000,
         "reason": "confirmed project order (example - delete this row)", "entered_by": "planner1"},
    ])
    example.to_csv(TEMPLATE, index=False)


def validate(df: pd.DataFrame, valid_series: set, valid_months: set) -> tuple[list[dict], pd.DataFrame]:
    """Return (errors, clean). Mandatory: valid series, valid month, numeric value, reason, entered_by."""
    errors = []
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        return [{"row": None, "error": f"missing columns: {missing}"}], pd.DataFrame(columns=COLUMNS)
    clean_rows = []
    for i, r in df.iterrows():
        sid = str(r["series_id"]).strip(); mo = str(r["month"]).strip()
        try:
            val = float(r["adjusted_forecast_mt"])
        except (TypeError, ValueError):
            val = None
        reason = str(r["reason"]).strip() if pd.notna(r["reason"]) else ""
        who = str(r["entered_by"]).strip() if pd.notna(r["entered_by"]) else ""
        row_err = []
        if sid not in valid_series:
            row_err.append(f"unknown series_id '{sid}'")
        if mo not in valid_months:
            row_err.append(f"month '{mo}' outside forecast horizon")
        if val is None or val < 0:
            row_err.append("adjusted_forecast_mt must be a non-negative number")
        if not reason:
            row_err.append("reason is mandatory")
        if not who:
            row_err.append("entered_by is mandatory")
        if row_err:
            errors.append({"row": int(i) + 2, "error": "; ".join(row_err)})
        else:
            clean_rows.append({"series_id": sid, "month": mo, "adjusted_forecast_mt": val,
                               "reason": reason, "entered_by": who})
    return errors, pd.DataFrame(clean_rows, columns=COLUMNS)


def publish(upload_path: str | None = None) -> dict:
    """Compare an uploaded adjustment file against the statistical forecast; write planner_adjustments.json."""
    ui = config.OUTPUTS_DIR / "ui" / "forecast_ui.json"
    if not ui.exists():
        raise SystemExit("forecast_ui.json not found - run publish first")
    payload = json.loads(ui.read_text(encoding="utf-8"))
    horizon_months = {f["month"] for s in payload["detail"].values() for f in s["forecasts"]["base"]}
    valid_series = set(payload["detail"]) | {s["series_id"] for s in payload["series"]}
    valid_series |= {a["series_id"] for a in payload.get("accounts", [])}

    if not upload_path or not Path(upload_path).exists():
        (config.OUTPUTS_DIR / "ui" / "planner_adjustments.json").write_text(
            json.dumps({"adjustments": [], "errors": [], "note": "no upload present"}, indent=2), encoding="utf-8")
        return {"adjustments": 0, "errors": 0}

    up = pd.read_csv(upload_path) if str(upload_path).endswith(".csv") else pd.read_excel(upload_path)
    errors, clean = validate(up, valid_series, horizon_months)
    stat = {}
    for sid, s in payload["detail"].items():
        for f in s["forecasts"]["base"]:
            stat[(sid, f["month"])] = f["point"]
    out = []
    for r in clean.itertuples(index=False):
        out.append({"adjustment_id": f"{r.series_id}|{r.month}", "sbu": "AIL", "series_id": r.series_id,
                    "month": r.month, "statistical_forecast_mt": stat.get((r.series_id, r.month)),
                    "adjusted_forecast_mt": r.adjusted_forecast_mt, "reason": r.reason,
                    "entered_by": r.entered_by, "run_id": payload["run_id"]})
    (config.OUTPUTS_DIR / "ui" / "planner_adjustments.json").write_text(
        json.dumps({"adjustments": out, "errors": errors}, indent=2, default=str), encoding="utf-8")
    return {"adjustments": len(out), "errors": len(errors)}


if __name__ == "__main__":
    import sys
    write_template()
    res = publish(sys.argv[1] if len(sys.argv) > 1 else None)
    print(res)
