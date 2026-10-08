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


def _clip(p, y):
    """Guard against state-space explosions: finite, within [0, 3x train max]. Logs every activation."""
    p = np.asarray(p, float)
    hi = max(3.0 * np.nanmax(y), 1.0)
    fallback = np.nanmean(y[-min(len(y), 6):])
    out = np.where(np.isfinite(p), p, fallback)
    out = np.clip(out, 0.0, hi)
    n = int(np.sum((out != p) | ~np.isfinite(p)))
    if n:
        CLIP_LOG.append({"context": dict(CLIP_CONTEXT), "n_clipped": n,
                         "raw_max": float(np.nanmax(p)) if np.isfinite(p).any() else None,
                         "raw_min": float(np.nanmin(p)) if np.isfinite(p).any() else None,
                         "clipped_max": float(np.nanmax(out)), "bound_hi": float(hi)})
    return out


# clipping audit log (populated by _clip; context set by backtest/stage4 loops)
CLIP_LOG: list = []
CLIP_CONTEXT: dict = {}


def reset_clip_log():
    CLIP_LOG.clear()


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
        self.first_month_ = self.y_.index[0].month
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
            if self.seasonal_ is not None:
                last = self.y_.index[-1]
                seas = np.array([self.seasonal_[(last + i).month - self.first_month_] % 12
                                 for i in range(1, horizon + 1)])
            else:
                seas = 0.0
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
    EXOG = ["eid_closure_days_total", "working_days_6day", "fy_end_flag", "monsoon_flag",
            "dry_season_flag", "slump", "disruption_days_full", "flood_major_flag"]

    def fit(self, y, X=None):
        super().fit(y, X)
        from statsmodels.tsa.statespace.sarimax import SARIMAX as SM
        Xs = self._small(X)
        Xv = None
        if Xs is not None and Xs.shape[1]:
            self.mu_ = Xs.mean(); self.sd_ = Xs.std().replace(0, 1)
            Xv = ((Xs - self.mu_) / self.sd_).values
        try:
            self.m_ = SM(self.y_.values, exog=Xv, order=(1, 1, 1), seasonal_order=(0, 1, 1, 12),
                         enforce_stationarity=True, enforce_invertibility=True).fit(disp=False, maxiter=100)
        except Exception:
            self.m_ = None
        return self

    def _small(self, X):
        if X is None:
            return None
        cols = [c for c in self.EXOG if c in X.columns]
        return X[cols] if cols else X

    def predict(self, horizon, X_future=None):
        if self.m_ is None:
            p = np.repeat(self.y_.values[-1], horizon)
        else:
            Xf = None
            if X_future is not None and hasattr(self, "mu_"):
                Xf = ((self._small(X_future) - self.mu_) / self.sd_).values
            p = np.asarray(self.m_.forecast(horizon, exog=Xf), float)
            p = _clip(p, self.y_.values)
        return Forecast(p, _band(p, self.y_.values))


class Structural(BaseModel):
    name = "structural"; supports_exog = False; min_history_months = 24

    def fit(self, y, X=None):
        super().fit(y, X)
        from statsmodels.tsa.statespace.structural import UnobservedComponents as UC
        # stable seasonal state-space (local level + monthly seasonality); exog omitted to avoid instability
        try:
            self.m_ = UC(self.y_.values, level="local level", seasonal=12).fit(disp=False, maxiter=200)
        except Exception:
            self.m_ = None
        return self

    def predict(self, horizon, X_future=None):
        if self.m_ is None:
            p = np.repeat(self.y_.values[-1], horizon)
        else:
            p = np.asarray(self.m_.forecast(horizon), float)
            p = _clip(p, self.y_.values)
        return Forecast(p, _band(p, self.y_.values))
