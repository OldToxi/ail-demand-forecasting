"""Torch-first worker: MUST import torch before numpy/pyarrow. Reads a series parquet, runs chronos-bolt
through a rolling-origin backtest, writes predictions. No pandas, no lightgbm, no statsmodels in-process.

Invoked as a subprocess by zeroshot_runner.py.
"""
import sys

import torch  # noqa: F401  (import first to avoid the DLL conflict)

import json
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


def main():
    series_path, out_path = sys.argv[1], sys.argv[2]
    tbl = pq.read_table(series_path)
    d = tbl.to_pydict()
    months = d["month"]; sids = d["series_id"]; yv = d["y"]
    by = {}
    for m, sid, v in zip(months, sids, yv):
        by.setdefault(sid, []).append((m, v))
    from chronos import BaseChronosPipeline
    pipe = BaseChronosPipeline.from_pretrained("amazon/chronos-bolt-small", device_map="cpu")
    origins = json.loads(sys.argv[3]) if len(sys.argv) > 3 else []
    rows = []
    for sid, seq in by.items():
        seq = sorted(seq)
        ms = [s[0] for s in seq]; ys = np.array([s[1] for s in seq], float)
        for o in origins:
            idx = [i for i, m in enumerate(ms) if m <= o]
            if len(idx) < 12:
                continue
            ctx = torch.tensor([ys[: idx[-1] + 1]])
            q, mean = pipe.predict_quantiles(ctx, prediction_length=12, quantile_levels=[0.025, 0.1, 0.5, 0.9, 0.975])
            arr = np.asarray(mean)[0]
            for h in range(12):
                rows.append({"series_id": sid, "origin": o, "horizon": h + 1, "pred": float(arr[h])})
    pq.write_table(pa.Table.from_pylist(rows), out_path)
    print("worker wrote", out_path, len(rows), "rows")


if __name__ == "__main__":
    main()
