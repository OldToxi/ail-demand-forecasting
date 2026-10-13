"""Torch-first worker: MUST import torch before numpy/pyarrow. Reads a series parquet, runs TimesFM 2.5-200M
zero-shot through a rolling-origin backtest, writes predictions. No pandas, no lightgbm, no statsmodels
in-process.

Invoked as a subprocess by timesfm_eval.py.

Output parquet schema: series_id (str), origin (str "YYYY-MM"), horizon (int 1..12), pred (float).
Min history per origin is 16 points (TimesFM default min context), unlike Chronos-Bolt's 12.
"""
import sys

import torch  # noqa: F401  (import first to avoid the DLL conflict)

import json
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

MODEL_REPO = "google/timesfm-2.5-200m-pytorch"
MIN_HISTORY = 16


def main():
    series_path, out_path = sys.argv[1], sys.argv[2]
    tbl = pq.read_table(series_path)
    d = tbl.to_pydict()
    months = d["month"]; sids = d["series_id"]; yv = d["y"]
    by = {}
    for m, sid, v in zip(months, sids, yv):
        by.setdefault(sid, []).append((m, v))

    from timesfm import TimesFM_2p5_200M_torch, ForecastConfig
    model = TimesFM_2p5_200M_torch.from_pretrained(MODEL_REPO)
    model.compile(ForecastConfig(max_context=512, max_horizon=12, normalize_inputs=True,
                                 per_core_batch_size=16, infer_is_positive=True))

    origins = json.loads(sys.argv[3]) if len(sys.argv) > 3 else []
    rows = []
    for sid, seq in by.items():
        seq = sorted(seq)
        ms = [s[0] for s in seq]
        ys = np.array([s[1] for s in seq], float)
        for o in origins:
            idx = [i for i, m in enumerate(ms) if m <= o]
            if len(idx) < MIN_HISTORY:
                continue
            window = np.asarray(ys[: idx[-1] + 1], dtype=float)
            point, _ = model.forecast(horizon=12, inputs=[window])
            arr = np.asarray(point)[0]
            for h in range(12):
                rows.append({"series_id": sid, "origin": o, "horizon": h + 1, "pred": float(arr[h])})
    pq.write_table(pa.Table.from_pylist(rows), out_path)
    print("worker wrote", out_path, len(rows), "rows")


if __name__ == "__main__":
    main()
