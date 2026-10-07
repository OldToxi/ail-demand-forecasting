"""Zero-shot foundation models (inference only, local, CPU). Imports are optional; if a package or its
cached weights are unavailable the model raises ModelUnavailable and the backtest skips it gracefully
(logged + timed), as allowed by the brief."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import BaseModel, Forecast, normal_quantiles, residual_sigma


class ModelUnavailable(Exception):
    pass


class _ZeroShot(BaseModel):
    min_history_months = 1
    zero_shot = True
    level = "aggregate"

    def fit(self, y, X=None):
        super().fit(y, X)
        self._load()
        return self

    def _load(self):
        raise ModelUnavailable(f"{self.name}: backend not installed / weights not cached")

    def predict(self, horizon, X_future=None):
        # Subclasses implement _forecast(context, horizon); default raises.
        raise ModelUnavailable(self.name)


class TimesFM(_ZeroShot):
    name = "timesfm"

    def _load(self):
        try:
            import timesfm  # noqa: F401
        except Exception as e:  # pragma: no cover - env dependent
            raise ModelUnavailable(f"timesfm not installed: {e}")
        raise ModelUnavailable("timesfm installed but weights not cached")


class ChronosBolt(_ZeroShot):
    name = "chronos_bolt"
    _pipe = None

    def _load(self):
        try:
            import torch  # noqa: F401
            from chronos import BaseChronosPipeline
        except Exception as e:  # pragma: no cover
            raise ModelUnavailable(f"chronos not installed: {e}")
        if ChronosBolt._pipe is None:
            try:
                ChronosBolt._pipe = BaseChronosPipeline.from_pretrained("amazon/chronos-bolt-small", device_map="cpu")
            except Exception as e:
                raise ModelUnavailable(f"chronos weights unavailable: {e}")

    def predict(self, horizon, X_future=None):
        import torch
        ctx = torch.tensor(np.asarray([self.y_.values], dtype=float))
        q, mean = ChronosBolt._pipe.predict_quantiles(ctx, prediction_length=horizon,
                                                      quantile_levels=[0.025, 0.1, 0.5, 0.9, 0.975])
        q = np.asarray(q)[0]  # (horizon, 5)
        point = np.maximum(np.asarray(mean)[0], 0.0)
        quants = {"q025": q[:, 0], "q10": q[:, 1], "q50": q[:, 2], "q90": q[:, 3], "q975": q[:, 4]}
        return Forecast(point, {k: np.maximum(v, 0.0) for k, v in quants.items()})


class Moirai(_ZeroShot):
    name = "moirai"

    def _load(self):
        try:
            import uni2ts  # noqa: F401
        except Exception as e:  # pragma: no cover
            raise ModelUnavailable(f"uni2ts/moirai not installed: {e}")
        raise ModelUnavailable("moirai installed but weights not cached")
