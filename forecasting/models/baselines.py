"""Baseline models: naive, seasonal naive, 3/6-month moving averages, drift."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import BaseModel, Forecast, normal_quantiles


class Naive(BaseModel):
    name = "naive"; min_history_months = 1

    def predict(self, horizon, X_future=None):
        p = np.repeat(self.y_.values[-1], horizon)
        return Forecast(p, normal_quantiles(p, self.sigma_[:horizon]))


class SeasonalNaive(BaseModel):
    name = "seasonal_naive"; min_history_months = 12

    def predict(self, horizon, X_future=None):
        y = self.y_.values
        per = min(12, len(y))
        p = np.array([y[-per + (i % per)] for i in range(horizon)])
        return Forecast(p, normal_quantiles(p, self.sigma_[:horizon]))


class MovingAverage(BaseModel):
    min_history_months = 1

    def __init__(self, window=3):
        self.window = window; self.name = f"ma{window}"

    def predict(self, horizon, X_future=None):
        p = np.repeat(np.mean(self.y_.values[-self.window:]), horizon)
        return Forecast(p, normal_quantiles(p, self.sigma_[:horizon]))


class Drift(BaseModel):
    name = "drift"; min_history_months = 3

    def predict(self, horizon, X_future=None):
        y = self.y_.values
        slope = (y[-1] - y[0]) / (len(y) - 1)
        p = np.maximum(y[-1] + slope * np.arange(1, horizon + 1), 0.0)
        return Forecast(p, normal_quantiles(p, self.sigma_[:horizon]))
