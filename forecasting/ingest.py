"""Stage 1 entry point: ingest -> standard frames -> hierarchy series -> external features -> DQ gate.

Writes a per-run folder under data/outputs/forecast/run_<run_id>/ (never overwrites previous runs).
Run (in the forecasting venv):  python -m forecasting.ingest
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import pandas as pd

from . import config, external, series as series_mod
from .adapters import load_all
from .dq_gate import run_gate


def run(sbu_id: str = "AIL", write: bool = True) -> dict:
    cfg = config.load_config()
    reg = config.load_sbus()
    ext_reg = config.load_external_registry()
    base_dir = config.REPO_ROOT

    sbu_cfg = next(s for s in reg["sbus"] if s["sbu_id"] == sbu_id)
    sbu_cfg["_hierarchy"] = sbu_cfg.get("hierarchy") or reg.get("hierarchy")

    frames = load_all(sbu_cfg, base_dir)
    series = series_mod.build_series(sbu_cfg, base_dir)

    ext_path = config.resolve(ext_reg["monthly_file"])
    ext_monthly = external.load_monthly(ext_path) if ext_path.exists() else None

    gate = run_gate(sbu_cfg, frames, series, ext_monthly, expected_end=cfg.get("forecast_start", "2026-10"))

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = {
        "run_id": run_id,
        "sbu": sbu_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "code_version": _git_sha(),
        "config_hash": config.config_hash(),
        "data_snapshot": config.data_snapshot([config.resolve(s["file"]) for s in sbu_cfg["sources"]]),
        "external_snapshot": config.data_snapshot([ext_path]) if ext_path.exists() else None,
        "channels": {c: int(frames[c]["y"].fillna(0).sum().round(0)) for c in frames},
        "n_series": int(series["series_id"].nunique()),
        "series_types": series.groupby("level")["series_id"].nunique().to_dict(),
        "dq_gate": gate,
    }

    if write:
        d = config.OUTPUTS_DIR / f"run_{run_id}"
        d.mkdir(parents=True, exist_ok=True)
        series.to_parquet(d / "series.parquet", index=False)
        # external features: calendar (known-in-advance) + registry + constraint months
        if ext_monthly is not None:
            seg = sbu_cfg.get("segment_code", "ALL")
            cal = external.calendar_features(ext_monthly, ext_reg, seg)
            cal.to_parquet(d / "external_calendar_features.parquet")
            reg_meta = [{"feature_key": v["feature_key"], "type": v["type"], "lag": v["lag"],
                         "segments": v["segments"], "channels": v.get("channels")}
                        for v in external.enabled_variables(ext_reg, seg)]
            (d / "feature_registry.json").write_text(json.dumps(reg_meta, indent=2), encoding="utf-8")
            cm = sorted(str(m) for m in external.constraint_months(ext_monthly))
            (d / "constraint_months.json").write_text(json.dumps(cm, indent=2), encoding="utf-8")
        # actuals (schema per brief)
        act = series.rename(columns={"y": "actual_mt", "value": "actual_value"}).copy()
        act["provisional_flag"] = act["month"].isin([pd.Period(m, "M") for m in cfg.get("provisional_months", [])])
        if ext_monthly is not None:
            cm = external.constraint_months(ext_monthly)
            act["constraint_flag"] = act["month"].isin(cm)
        else:
            act["constraint_flag"] = False
        act[["sbu", "series_id", "month", "actual_mt", "actual_value", "provisional_flag", "constraint_flag"]] \
            .assign(sbu=sbu_id).to_parquet(d / "actuals.parquet", index=False)
        (d / "run_metadata.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        (d / "dq_gate.json").write_text(json.dumps(gate, indent=2, default=str), encoding="utf-8")
        # current pointer (kept small; previous runs remain under their own run_id)
        config.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        (config.OUTPUTS_DIR / "latest_run.txt").write_text(run_id, encoding="utf-8")
        out["output_dir"] = str(d)
    return out


def _git_sha() -> str:
    try:
        import subprocess
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       cwd=config.APP_ROOT, text=True).strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    sbu = sys.argv[1] if len(sys.argv) > 1 else "AIL"
    result = run(sbu)
    print(json.dumps({k: result[k] for k in ["run_id", "sbu", "channels", "n_series", "series_types"]},
                     indent=2, default=str))
    print("DQ gate passed:", result["dq_gate"]["passed"],
          "| warnings:", len(result["dq_gate"]["warnings"]), "| hard:", result["dq_gate"]["hard_failures"])
