"""Seasonality-capable candidate models for the model bake-off.

New models (all `BaseModel` subclasses, min_history_months = 24):

  * auto_arima  - statsforecast AutoARIMA(season_length=12)
  * auto_ets    - statsforecast AutoETS(season_length=12)
  * auto_theta  - statsforecast AutoTheta(season_length=12)
  * mstl        - statsforecast MSTL(season_length=12, trend_forecaster=AutoETS(model="ZZN"))
  * tbats       - statsforecast AutoTBATS(season_length=12)  (skips gracefully if not importable)
  * fourier_ols - deterministic OLS on trend + Fourier terms + slump step dummy
  * ets_mul     - statsmodels ExponentialSmoothing (mul seasonality, add fallback)

Statsforecast models take a 1-D ``np.ndarray`` in ``fit`` and return a dict from
``predict(h=H, level=[80, 95])`` with keys ``mean``, ``lo-80``, ``hi-80``, ``lo-95``, ``hi-95``.
The 80% band maps to q10/q90, the 95% band to q025/q975, and q50 = mean.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import BaseModel, Forecast, normal_quantiles, residual_sigma
from .zeroshot import ModelUnavailable


def _naive(y, horizon):
    y = np.asarray(y, float)
    return np.repeat(y[-1], horizon)


def _finite(p, y):
    """Replace non-finite with the recent mean and clip at 0 (no negative volumes)."""
    p = np.asarray(p, float)
    y = np.asarray(y, float)
    fallback = float(np.nanmean(y[-min(len(y), 6):]))
    out = np.where(np.isfinite(p), p, fallback)
    return np.maximum(out, 0.0)


def _band(point, y, horizon):
    return normal_quantiles(point, residual_sigma(np.asarray(y, float), horizon))


# ----------------------------------------------------------------------------------
# statsforecast season_length=12 family
# ----------------------------------------------------------------------------------
class _StatsForecastSeasonal(BaseModel):
    """Shared plumbing for the statsforecast seasonal models."""

    min_history_months = 24
    level = "aggregate"

    def _make_model(self):
        raise NotImplementedError

    def fit(self, y, X=None):
        super().fit(y, X)
        try:
            model = self._make_model()
        except ModelUnavailable:
            raise
        except Exception as e:
            raise ModelUnavailable(f"{self.name}: statsforecast unavailable: {e}")
        try:
            model.fit(self.y_.values.astype(float))
            self.model_ = model
        except Exception:
            self.model_ = None
        return self

    def predict(self, horizon, X_future=None):
        yv = self.y_.values
        if getattr(self, "model_", None) is None:
            p = _naive(yv, horizon)
            return Forecast(p, _band(p, yv, horizon))
        try:
            fc = self.model_.predict(h=horizon, level=[80, 95])
        except Exception:
            p = _naive(yv, horizon)
            return Forecast(p, _band(p, yv, horizon))
        p = _finite(np.asarray(fc["mean"], float), yv)
        quants = {
            "q025": _finite(np.asarray(fc["lo-95"], float), yv),
            "q10": _finite(np.asarray(fc["lo-80"], float), yv),
            "q50": p.copy(),
            "q90": _finite(np.asarray(fc["hi-80"], float), yv),
            "q975": _finite(np.asarray(fc["hi-95"], float), yv),
        }
        return Forecast(p, quants)


class AutoARIMA(_StatsForecastSeasonal):
    name = "auto_arima"

    def _make_model(self):
        try:
            from statsforecast.models import AutoARIMA
        except ImportError as e:
            raise ModelUnavailable(f"statsforecast not installed: {e}")
        return AutoARIMA(season_length=12)


class AutoETS(_StatsForecastSeasonal):
    name = "auto_ets"

    def _make_model(self):
        try:
            from statsforecast.models import AutoETS
        except ImportError as e:
            raise ModelUnavailable(f"statsforecast not installed: {e}")
        return AutoETS(season_length=12)


class AutoTheta(_StatsForecastSeasonal):
    name = "auto_theta"

    def _make_model(self):
        try:
            from statsforecast.models import AutoTheta
        except ImportError as e:
            raise ModelUnavailable(f"statsforecast not installed: {e}")
        return AutoTheta(season_length=12)


class MSTL(_StatsForecastSeasonal):
    name = "mstl"

    def _make_model(self):
        try:
            from statsforecast.models import MSTL as _MSTL
            from statsforecast.models import AutoETS
        except ImportError as e:
            raise ModelUnavailable(f"statsforecast not installed: {e}")
        # MSTL handles the seasonality; the trend forecaster must be NON-seasonal
        # (model="ZZN") or MSTL refuses to construct.
        return _MSTL(season_length=12, trend_forecaster=AutoETS(model="ZZN"))


class AutoTBATS(_StatsForecastSeasonal):
    name = "tbats"

    def _make_model(self):
        try:
            from statsforecast.models import AutoTBATS
        except ImportError as e:
            raise ModelUnavailable(f"statsforecast AutoTBATS not importable: {e}")
        return AutoTBATS(season_length=12)


# ----------------------------------------------------------------------------------
# OLS on trend + Fourier terms (deterministic, seasonality explicit)
# ----------------------------------------------------------------------------------
class FourierOLS(BaseModel):
    name = "fourier_ols"
    min_history_months = 24
    level = "aggregate"
    K = 2  # number of Fourier harmonic pairs (k=1,2)

    def _slump_window(self):
        """Configured slump window (config.yaml:interventions). Defaults to the company window."""
        try:
            from .. import config
            iv = config.load_config().get("interventions", {})
            for key in ("AIL|company", "default"):
                w = (iv.get(key) or {}).get("slump")
                if w:
                    return pd.Period(w[0], "M"), pd.Period(w[1], "M")
        except Exception:
            pass
        return pd.Period("2024-07", "M"), pd.Period("2025-06", "M")

    def _design(self, periods, t0):
        """Fourier design matrix for the given monthly periods (trend + sin/cos terms + slump)."""
        t = np.arange(t0, t0 + len(periods), dtype=float)
        cols = [t]
        for k in range(1, self.K + 1):
            cols.append(np.sin(2 * np.pi * k * t / 12.0))
            cols.append(np.cos(2 * np.pi * k * t / 12.0))
        start, end = self._slump_window()
        slump = np.zeros(len(periods), dtype=float)
        for i, p in enumerate(periods):
            if start <= p <= end:
                slump[i] = 1.0
        cols.append(slump)
        return np.column_stack(cols)

    def fit(self, y, X=None):
        super().fit(y, X)
        yv = self.y_.values.astype(float)
        self.coef_ = None
        try:
            Xm = self._design(self.y_.index, 0)
            coef, *_ = np.linalg.lstsq(Xm, yv, rcond=None)
            if np.all(np.isfinite(coef)):
                self.coef_ = coef
        except Exception:
            self.coef_ = None
        return self

    def predict(self, horizon, X_future=None):
        yv = self.y_.values
        if self.coef_ is None:
            p = _naive(yv, horizon)
        else:
            last = self.y_.index[-1]
            fut = pd.period_range(last + 1, periods=horizon, freq="M")
            Xf = self._design(fut, len(yv))
            p = Xf @ self.coef_
        p = _finite(p, yv)
        return Forecast(p, _band(p, yv, horizon))


# ----------------------------------------------------------------------------------
# statsmodels Holt-Winters (multiplicative seasonality with additive fallback)
# ----------------------------------------------------------------------------------
class ETSMul(BaseModel):
    name = "ets_mul"
    min_history_months = 24
    level = "aggregate"

    def fit(self, y, X=None):
        super().fit(y, X)
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
        yv = self.y_.values.astype(float)
        self.model_ = None
        for seasonal in ("mul", "add"):
            try:
                m = ExponentialSmoothing(yv, trend="add", damped_trend=True,
                                         seasonal=seasonal, seasonal_periods=12)
                self.model_ = m.fit(optimized=True)
                break
            except Exception:
                continue
        return self

    def predict(self, horizon, X_future=None):
        yv = self.y_.values
        if self.model_ is None:
            p = _naive(yv, horizon)
        else:
            try:
                p = _finite(np.asarray(self.model_.forecast(horizon), float), yv)
            except Exception:
                p = _naive(yv, horizon)
        return Forecast(p, _band(p, yv, horizon))
