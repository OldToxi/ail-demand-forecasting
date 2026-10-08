"""One command for the whole forecasting run. Explicit run ids + manifests; a failed stage stops the run.

ingest -> backtest(run id) -> stage4(explicit backtest run id) -> publish -> planner template.
"""
from __future__ import annotations

import argparse

from . import ingest, planner, publish, run_backtest, run_manifest, stage4

DEFAULT_SBU = "AIL"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sbu", default=DEFAULT_SBU)
    ap.add_argument("--adjustments", default=None)
    ap.add_argument("--skip-backtest", action="store_true", help="reuse the backtest run given by --backtest-run")
    ap.add_argument("--backtest-run", default=None)
    a = ap.parse_args()

    print("[1/5] ingest + DQ gate ...")
    ingest.run(a.sbu)
    print("[2/5] backtest ...")
    if a.skip_backtest:
        bt = a.backtest_run
        if not bt:
            raise SystemExit("--skip-backtest requires --backtest-run")
    else:
        bt = run_backtest.run(sbus=a.sbu)
    print("[3/5] stage 4 (consumes backtest run", bt, ") ...")
    s4 = stage4.run(bt)
    print("[4/5] publish ...")
    publish.publish(s4)
    print("[5/5] planner ...")
    planner.write_template()
    print(planner.publish(a.adjustments))
    print("done. stage4 run:", s4)


if __name__ == "__main__":
    main()
