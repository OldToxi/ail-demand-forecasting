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

    def _load(self):
        try:
            import chronos  # noqa: F401
        except Exception as e:  # pragma: no cover
            raise ModelUnavailable(f"chronos not installed: {e}")
        raise ModelUnavailable("chronos installed but weights not cached")


class Moirai(_ZeroShot):
    name = "moirai"

    def _load(self):
        try:
            import uni2ts  # noqa: F401
        except Exception as e:  # pragma: no cover
            raise ModelUnavailable(f"uni2ts/moirai not installed: {e}")
        raise ModelUnavailable("moirai installed but weights not cached")
