"""Zero-shot backtest in an ISOLATED process (torch DLL conflicts with lightgbm/statsmodels otherwise).

Runs Chronos-Bolt only; imports no native ML libs. Writes data/outputs/forecast/zeroshot_results.json.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import config
from .adapters import load_all
from .series import build_series
from .models.zeroshot import ChronosBolt, ModelUnavailable

AG = {"company", "sbu", "channel", "zone"}


def main():
    cfg = config.load_config(); reg = config.load_sbus()
    sbu = next(s for s in reg["sbus"] if s["sbu_id"] == "AIL"); sbu["_hierarchy"] = reg["hierarchy"]
    series = build_series(sbu, config.REPO_ROOT)
    origins = list(pd.period_range(cfg["backtest_origins"][0], cfg["backtest_origins"][1], freq="M"))
    cut = pd.Period("2026-03", "M")
    out, errs = [], []
    for sid, g in series[series.level.isin(AG)].groupby("series_id"):
        y = pd.Series(g.sort_values("month")["y"].values, index=pd.PeriodIndex(sorted(g["month"]), freq="M"))
        rows = []
        for T in origins:
            train = y[y.index <= T]
            if len(train) < 12:
                continue
            targets = pd.period_range(T + 1, periods=12, freq="M")
            keep = [i for i, t in enumerate(targets) if t <= cut and t in y.index]
            if not keep:
                continue
            try:
                m = ChronosBolt(); m.fit(train); fc = m.predict(12)
            except ModelUnavailable as e:
                errs.append(str(e)); break
            for i in keep:
                t = targets[i]
                rows.append((abs(float(fc.point[i]) - float(y.loc[t])), float(y.loc[t]), i + 1))
        if rows:
            ae = sum(r[0] for r in rows); av = sum(abs(r[1]) for r in rows)
            h16 = [r for r in rows if r[2] <= 6]
            out.append({"series_id": sid, "wape_all": round(ae / max(av, 1), 4),
                        "wape_h1_6": round(sum(r[0] for r in h16) / max(sum(abs(r[1]) for r in h16), 1), 4),
                        "n": len(rows)})
    res = {"model": "chronos_bolt (zero-shot, CPU, isolated process)", "by_series": out, "errors": errs[:3]}
    (config.OUTPUTS_DIR / "zeroshot_results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
