"""Common model interface. Every model returns a point path and quantiles (q025,q10,q50,q90,q975)."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

QKEYS = ["q025", "q10", "q50", "q90", "q975"]


@dataclass
class Forecast:
    point: np.ndarray
    quantiles: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    def as_frame(self, index: pd.PeriodIndex) -> pd.DataFrame:
        d = {"point": self.point}
        d.update(self.quantiles)
        return pd.DataFrame(d, index=index)


def normal_quantiles(point: np.ndarray, sigma: np.ndarray) -> dict:
    """Quantiles from a normal band scaled by per-step sigma (widening with horizon)."""
    z = {"q025": -1.96, "q10": -1.2816, "q50": 0.0, "q90": 1.2816, "q975": 1.96}
    return {k: point + zz * sigma for k, zz in z.items()}


def residual_sigma(y: np.ndarray, horizon: int, seasonal: bool = True) -> np.ndarray:
    """Residual std from one-step in-sample errors, widened by sqrt(h)."""
    y = np.asarray(y, dtype=float)
    if len(y) < 3:
        return np.full(horizon, max(np.nanstd(y), 1.0))
    resid = np.diff(y)
    s = np.nanstd(resid)
    if seasonal and len(y) >= 13:
        s = max(s, np.nanstd(y[12:] - y[:-12]))
    s = max(s, 1e-6)
    return s * np.sqrt(np.arange(1, horizon + 1))


class BaseModel:
    name = "base"
    supports_exog = False
    supports_intermittent = False
    min_history_months = 24
    needs_gpu = False
    zero_shot = False
    level = "aggregate"

    def fit(self, y: pd.Series, X: pd.DataFrame | None = None):  # y indexed by Period[M]
        self.y_ = pd.Series(np.asarray(y, dtype=float), index=pd.PeriodIndex(y.index, freq="M"))
        self.X_ = X
        self.sigma_ = residual_sigma(self.y_.values, 12)
        return self

    def predict(self, horizon: int, X_future: pd.DataFrame | None = None) -> Forecast:
        raise NotImplementedError
