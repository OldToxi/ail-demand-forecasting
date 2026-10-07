"""LightGBM: one pooled-per-series direct/recursive learner with lag + calendar features."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import BaseModel, Forecast, normal_quantiles, residual_sigma

LAGS = [1, 2, 3, 6, 12]


class LightGBM(BaseModel):
    name = "lightgbm"; supports_exog = True; min_history_months = 24

    def __init__(self, params=None):
        self.params = params or dict(objective="regression", n_estimators=300, learning_rate=0.05,
                                     num_leaves=15, min_child_samples=5, verbose=-1, random_state=42)

    def _design(self, y: pd.Series, exog: pd.DataFrame | None):
        df = pd.DataFrame({"y": y.values}, index=y.index)
        for lag in LAGS:
            df[f"lag{lag}"] = df["y"].shift(lag)
        df["roll3"] = df["y"].shift(1).rolling(3).mean()
        df["roll6"] = df["y"].shift(1).rolling(6).mean()
        df["month"] = [p.month for p in y.index]
        df["fyend"] = (df["month"] == 6).astype(int)
        if exog is not None:
            for c in exog.columns:
                df[c] = exog[c].reindex(y.index).values
        return df

    def fit(self, y, X=None):
        super().fit(y, X)
        import lightgbm as lgb
        df = self._design(self.y_, X).dropna()
        if len(df) < 12:
            self.m_ = None; return self
        feats = [c for c in df.columns if c != "y"]
        self.feats_ = feats
        self.m_ = lgb.LGBMRegressor(**self.params).fit(df[feats], df["y"])
        return self

    def predict(self, horizon, X_future=None):
        if self.m_ is None:
            p = np.repeat(self.y_.values[-1], horizon)
            return Forecast(p, normal_quantiles(p, residual_sigma(self.y_.values, horizon)))
        hist = list(self.y_.values)
        last = self.y_.index[-1]
        fut_index = pd.period_range(last + 1, periods=horizon, freq="M")
        preds = []
        for i, per in enumerate(fut_index):
            row = {}
            for lag in LAGS:
                row[f"lag{lag}"] = hist[-lag] if len(hist) >= lag else np.nan
            row["roll3"] = np.mean(hist[-3:]); row["roll6"] = np.mean(hist[-6:])
            row["month"] = per.month; row["fyend"] = int(per.month == 6)
            if X_future is not None:
                for c in [c for c in self.feats_ if c not in row]:
                    row[c] = X_future[c].iloc[i] if c in X_future else 0.0
            x = pd.DataFrame([row])[self.feats_].fillna(0.0)
            yhat = float(max(self.m_.predict(x)[0], 0.0))
            preds.append(yhat); hist.append(yhat)
        p = np.asarray(preds)
        return Forecast(p, normal_quantiles(p, residual_sigma(self.y_.values, horizon)))
