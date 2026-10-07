"""Statistical models via statsmodels: AutoETS, STL+ETS, Theta, SARIMAX, Structural (UnobservedComponents).

Quantiles use the model point forecast with a residual-sigma band (widening with horizon); empirical
coverage is checked and recalibrated in Stage 4.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from .base import BaseModel, Forecast, normal_quantiles, residual_sigma

warnings.filterwarnings("ignore")


def _band(point, y):
    return normal_quantiles(point, residual_sigma(np.asarray(y, float), len(point)))


class AutoETS(BaseModel):
    name = "ets"; supports_exog = False; min_history_months = 24

    def _fit_best(self, y):
        from statsmodels.tsa.exponential_smoothing.ets import ETSModel
        best = None; best_aicc = np.inf
        for trend in ("add", None):
            for damped in ((True, False) if trend == "add" else (False,)):
                for seasonal in ("add", "mul"):
                    try:
                        m = ETSModel(y, error="add", trend=trend, damped_trend=damped,
                                     seasonal=seasonal, seasonal_periods=12)
                        r = m.fit(disp=False, maxiter=500)
                        if np.isfinite(r.aicc) and r.aicc < best_aicc:
                            best, best_aicc = r, r.aicc
                    except Exception:
                        continue
        return best

    def fit(self, y, X=None):
        super().fit(y, X)
        yv = self.y_.values
        self.model_ = self._fit_best(yv) if len(yv) >= 24 else None
        return self

    def predict(self, horizon, X_future=None):
        if self.model_ is None:
            p = np.repeat(self.y_.values[-1], horizon)
        else:
            p = np.maximum(np.asarray(self.model_.forecast(horizon), float), 0.0)
        return Forecast(p, _band(p, self.y_.values))


class STLETS(BaseModel):
    name = "stl_ets"; supports_exog = False; min_history_months = 24

    def fit(self, y, X=None):
        super().fit(y, X)
        from statsmodels.tsa.seasonal import STL
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
        yv = self.y_.values
        try:
            stl = STL(pd.Series(yv, index=pd.period_range("2000-01", periods=len(yv), freq="M")),
                      period=12, robust=True).fit()
            self.seasonal_ = stl.seasonal.values
            sa = yv - self.seasonal_
            self.ets_ = ExponentialSmoothing(sa, trend="add", damped_trend=True).fit(optimized=True)
        except Exception:
            self.seasonal_ = None; self.ets_ = None
        return self

    def predict(self, horizon, X_future=None):
        yv = self.y_.values
        if self.ets_ is None:
            p = np.repeat(yv[-1], horizon)
        else:
            sa_fc = np.asarray(self.ets_.forecast(horizon), float)
            seas = np.array([self.seasonal_[(len(yv) + i) % 12] for i in range(horizon)]) if self.seasonal_ is not None else 0.0
            p = np.maximum(sa_fc + seas, 0.0)
        return Forecast(p, _band(p, self.y_.values))


class Theta(BaseModel):
    name = "theta"; min_history_months = 24

    def fit(self, y, X=None):
        super().fit(y, X)
        from statsmodels.tsa.forecasting.theta import ThetaModel
        try:
            self.m_ = ThetaModel(self.y_.values, period=12, deseasonalize=True).fit()
        except Exception:
            self.m_ = None
        return self

    def predict(self, horizon, X_future=None):
        if self.m_ is None:
            p = np.repeat(self.y_.values[-1], horizon)
        else:
            p = np.maximum(np.asarray(self.m_.forecast(horizon), float), 0.0)
        return Forecast(p, _band(p, self.y_.values))


class SARIMAX(BaseModel):
    name = "sarimax"; supports_exog = True; min_history_months = 24

    def fit(self, y, X=None):
        super().fit(y, X)
        from statsmodels.tsa.statespace.sarimax import SARIMAX as SM
        Xv = None
        if X is not None and X.shape[1]:
            self.mu_ = X.mean(); self.sd_ = X.std().replace(0, 1)
            Xv = ((X - self.mu_) / self.sd_).values
        try:
            self.m_ = SM(self.y_.values, exog=Xv, order=(1, 1, 1), seasonal_order=(0, 1, 1, 12),
                         enforce_stationarity=True, enforce_invertibility=True).fit(disp=False, maxiter=200)
        except Exception:
            self.m_ = None
        return self

    def predict(self, horizon, X_future=None):
        if self.m_ is None:
            p = np.repeat(self.y_.values[-1], horizon)
        else:
            Xf = None
            if X_future is not None and hasattr(self, "mu_"):
                Xf = ((X_future - self.mu_) / self.sd_).values
            p = np.asarray(self.m_.forecast(horizon, exog=Xf), float)
            p = np.maximum(np.where(np.isfinite(p), p, self.y_.values[-1]), 0.0)
        return Forecast(p, _band(p, self.y_.values))


class Structural(BaseModel):
    name = "structural"; supports_exog = True; min_history_months = 24

    def fit(self, y, X=None):
        super().fit(y, X)
        from statsmodels.tsa.statespace.structural import UnobservedComponents as UC
        Xv = None
        if X is not None and X.shape[1]:
            self.mu_ = X.mean(); self.sd_ = X.std().replace(0, 1)
            Xv = ((X - self.mu_) / self.sd_).values
        try:
            self.m_ = UC(self.y_.values, level="local linear trend", seasonal=12, exog=Xv).fit(disp=False, maxiter=300)
        except Exception:
            try:
                self.m_ = UC(self.y_.values, level="local level", seasonal=12, exog=Xv).fit(disp=False, maxiter=300)
            except Exception:
                self.m_ = None
        return self

    def predict(self, horizon, X_future=None):
        if self.m_ is None:
            p = np.repeat(self.y_.values[-1], horizon)
        else:
            Xf = None
            if X_future is not None and hasattr(self, "mu_"):
                Xf = ((X_future - self.mu_) / self.sd_).values
            p = np.asarray(self.m_.forecast(horizon, exog=Xf), float)
            p = np.maximum(np.where(np.isfinite(p), p, self.y_.values[-1]), 0.0)
        return Forecast(p, _band(p, self.y_.values))
