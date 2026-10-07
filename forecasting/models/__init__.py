"""Model registry: build a model instance from a config name. New models register here."""
from __future__ import annotations

from . import baselines, intermittent, ml, statistical, zeroshot

_BUILDERS = {
    "naive": lambda p: baselines.Naive(),
    "seasonal_naive": lambda p: baselines.SeasonalNaive(),
    "ma3": lambda p: baselines.MovingAverage(3),
    "ma6": lambda p: baselines.MovingAverage(6),
    "drift": lambda p: baselines.Drift(),
    "ets": lambda p: statistical.AutoETS(),
    "stl_ets": lambda p: statistical.STLETS(),
    "theta": lambda p: statistical.Theta(),
    "sarimax": lambda p: statistical.SARIMAX(),
    "structural": lambda p: statistical.Structural(),
    "lightgbm": lambda p: ml.LightGBM(p.get("params")),
    "croston_sba": lambda p: intermittent.CrostonSBA(),
    "tsb": lambda p: intermittent.TSB(),
    "hurdle": lambda p: intermittent.Hurdle(),
    "timesfm": lambda p: zeroshot.TimesFM(),
    "chronos_bolt": lambda p: zeroshot.ChronosBolt(),
    "moirai": lambda p: zeroshot.Moirai(),
}


def build_model(name: str, params: dict | None = None):
    if name not in _BUILDERS:
        raise KeyError(f"unknown model '{name}' (have {sorted(_BUILDERS)})")
    return _BUILDERS[name](params or {})


def available_models():
    return sorted(_BUILDERS)
