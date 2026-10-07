"""Unified pipeline for the three planning tabs.

Raw data (data/raw/) -> artifacts (data/outputs/) -> served by the backend.

Stages (run in dependency order):
  production        data/raw/Bom.xlsx
                    + data/interim/final_quantity_forecast.parquet, item_monthly_panel.parquet
                    -> data/outputs/data/cement_bom.csv
                       data/outputs/data/production_material_forecast.csv
                       data/outputs/data/production_material_by_type.csv
                       data/outputs/data/production_material_history.csv
                       data/outputs/data/production_plan_meta.json
  demand-forecast   data/raw/National Sales Data_Cement.xlsx
                    + data/raw/cement_data.parquet, DimBusinessPartner.csv
                    -> data/outputs/demand_planning/bakeoff_leaderboard.json
                       data/outputs/demand_planning/demand_forecast_v2.json
  demand-planning   data/raw/National Sales Data_Cement.xlsx
                    + data/raw/cement_data.parquet
                    -> data/outputs/demand_planning/market_target.json

Usage:
  python run_pipeline.py                 # run every stage whose inputs exist
  python run_pipeline.py --stage production
  python run_pipeline.py --list          # show inputs/outputs per stage, don't run
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # planning-app/
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
OUT = ROOT / "data" / "outputs"
DP_OUT = OUT / "demand_planning"
DATA_OUT = OUT / "data"

PY = sys.executable

# a stage = list of steps; a step = (label, script, cwd, required inputs, produced outputs)
STAGES = {
    "production": [
        ("cement BOM", "build_cement_bom.py", ROOT / "pipeline",
         [RAW / "Bom.xlsx"], [DATA_OUT / "cement_bom.csv"]),
        ("material plan", "build_production_plan.py", ROOT / "pipeline",
         [INTERIM / "final_quantity_forecast.parquet", INTERIM / "item_monthly_panel.parquet"],
         [DATA_OUT / "production_material_forecast.csv", DATA_OUT / "production_plan_meta.json"]),
    ],
    "demand-forecast": [
        ("bake-off", "bakeoff.py", ROOT / "pipeline" / "demand_planning",
         [RAW / "National Sales Data_Cement.xlsx"], [DP_OUT / "bakeoff_leaderboard.json"]),
        ("demand forecast v2", "build_demand_forecast_v2.py", ROOT / "pipeline" / "demand_planning",
         [RAW / "National Sales Data_Cement.xlsx", RAW / "cement_data.parquet", RAW / "DimBusinessPartner.csv"],
         [DP_OUT / "demand_forecast_v2.json"]),
    ],
    "demand-planning": [
        ("market target", "build_market_target.py", ROOT / "pipeline" / "demand_planning",
         [RAW / "National Sales Data_Cement.xlsx", RAW / "cement_data.parquet"],
         [DP_OUT / "market_target.json"]),
    ],
}
ORDER = ["production", "demand-forecast", "demand-planning"]


def _missing(inputs):
    return [p for p in inputs if not p.exists()]


def describe():
    for name in ORDER:
        print(f"\n[{name}]")
        for label, script, cwd, inputs, outputs in STAGES[name]:
            print(f"  {label}: {script}")
            for p in inputs:
                print(f"    in  {'OK ' if p.exists() else 'MISS'}  {p.relative_to(ROOT)}")
            for p in outputs:
                print(f"    out {'OK ' if p.exists() else '-- '}  {p.relative_to(ROOT)}")


def run_stage(name, strict=False):
    print(f"\n=== stage: {name} ===")
    ok = True
    for label, script, cwd, inputs, outputs in STAGES[name]:
        missing = _missing(inputs)
        if missing:
            print(f"  SKIP {label}: missing inputs:")
            for p in missing:
                print(f"        {p.relative_to(ROOT)}")
            ok = False
            continue
        print(f"  RUN  {label}: python {script}")
        r = subprocess.run([PY, script], cwd=str(cwd))
        if r.returncode != 0:
            print(f"  FAIL {label} (exit {r.returncode})")
            ok = False
            if strict:
                raise SystemExit(1)
        else:
            print(f"  DONE {label}")
    return ok


def main():
    ap = argparse.ArgumentParser(description="Planning-app pipeline")
    ap.add_argument("--stage", choices=ORDER + ["all"], default="all")
    ap.add_argument("--list", action="store_true", help="show inputs/outputs and exit")
    ap.add_argument("--strict", action="store_true", help="abort on first failure/missing input")
    args = ap.parse_args()

    if args.list:
        describe()
        return

    stages = ORDER if args.stage == "all" else [args.stage]
    results = {s: run_stage(s, args.strict) for s in stages}

    print("\n=== summary ===")
    for s in stages:
        print(f"  {s:16s} {'ok' if results[s] else 'incomplete (missing inputs or failed)'}")
    if not all(results.values()):
        print("\nDrop the required raw files into data/raw/ (and interim parquets into data/interim/), then re-run.")
        sys.exit(0 if not args.strict else 1)


if __name__ == "__main__":
    main()
