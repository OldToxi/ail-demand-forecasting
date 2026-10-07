"""One command for the whole forecasting run: ingest -> DQ gate -> (backtest) -> selection -> final
forecast -> reconcile -> scenarios -> publish.

Usage (in the forecasting venv): python -m forecasting.run_forecast [--skip-backtest]
"""
from __future__ import annotations

import argparse

from . import ingest, planner, publish, stage4

DEFAULT_SBU = "AIL"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sbu", default=DEFAULT_SBU)
    ap.add_argument("--adjustments", default=None, help="planner adjustment CSV/XLSX to ingest")
    args = ap.parse_args()

    print("[1/4] ingest + DQ gate ...")
    ingest.run(args.sbu)
    print("[2/4] backtest + selection + final forecast (Stage 4) ...")
    stage4.run()
    print("[3/4] publish UI artifact ...")
    publish.publish()
    print("[4/4] planner adjustments ...")
    planner.write_template()
    print(planner.publish(args.adjustments))
    print("done.")


if __name__ == "__main__":
    main()
