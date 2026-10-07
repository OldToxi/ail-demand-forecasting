"""Intermittent-demand models for the Corporate top-accounts layer: Croston (SBA), TSB, and a
two-part hurdle (P(order) x expected size)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import BaseModel, Forecast, normal_quantiles, residual_sigma


def _ses(x, alpha=0.2):
    x = np.asarray(x, float)
    if len(x) == 0:
        return 0.0
    s = x[0]
    for v in x[1:]:
        s = alpha * v + (1 - alpha) * s
    return s


class CrostonSBA(BaseModel):
    name = "croston_sba"; supports_intermittent = True; min_history_months = 12

    def predict(self, horizon, X_future=None):
        y = self.y_.values
        nz = np.where(y > 0)[0]
        if len(nz) == 0:
            p = np.zeros(horizon)
        else:
            sizes = y[nz]
            intervals = np.diff(np.concatenate([[-1], nz]))
            rate = _ses(sizes) / max(_ses(intervals), 1.0)
            p = np.repeat(max(rate * (1 - 0.1), 0.0), horizon)  # SBA correction (1-alpha/2, alpha=0.2)
        return Forecast(p, normal_quantiles(p, residual_sigma(y, horizon)))


class TSB(BaseModel):
    name = "tsb"; supports_intermittent = True; min_history_months = 12

    def predict(self, horizon, X_future=None):
        y = self.y_.values
        occ = (y > 0).astype(float)
        prob = _ses(occ, 0.2)
        size = _ses(y[y > 0], 0.2) if (y > 0).any() else 0.0
        p = np.repeat(prob * size, horizon)
        return Forecast(p, normal_quantiles(p, residual_sigma(y, horizon)))


class Hurdle(BaseModel):
    name = "hurdle"; supports_intermittent = True; min_history_months = 18

    def fit(self, y, X=None):
        super().fit(y, X)
        from sklearn.linear_model import LogisticRegression
        s = self.y_
        occ = (s.values > 0).astype(int)
        if len(s) < 18 or occ.sum() in (0, len(s)):
            self.clf_ = None; self.p_ = float(occ.mean()); self.size_ = float(np.median(s.values[s.values > 0])) if occ.sum() else 0.0
            return self
        recency = np.arange(len(s))[::-1]
        X = np.column_stack([occ * 0 + recency, np.array([p.month for p in s.index])])
        self.clf_ = LogisticRegression(max_iter=200).fit(X, occ)
        self.size_ = float(np.median(s.values[s.values > 0]))
        return self

    def predict(self, horizon, X_future=None):
        last = self.y_.index[-1]
        if getattr(self, "clf_", None) is None:
            return Forecast(np.repeat(self.p_ * self.size_, horizon),
                            normal_quantiles(np.repeat(self.p_ * self.size_, horizon), residual_sigma(self.y_.values, horizon)))
        ps = []
        for i in range(1, horizon + 1):
            per = last + i
            prob = self.clf_.predict_proba(np.array([[-(i), per.month]]))[0, 1]
            ps.append(prob * self.size_)
        p = np.asarray(ps)
        return Forecast(p, normal_quantiles(p, residual_sigma(self.y_.values, horizon)))
