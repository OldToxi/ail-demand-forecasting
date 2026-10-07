"""Phase A: 6-model bake-off on the national ACCL cement series.

Compares AutoETS, AutoARIMA, Theta, Holt-Winters, Seasonal Naive, and the current
damped-trend method on two withheld 6-month test windows. Produces a leaderboard
with WAPE / BIAS / MASE scores and a JSON output the web app reads directly.

Run: python scripts/demand_planning/bakeoff.py
"""
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]                # planning-app/
SRC = ROOT / "data" / "raw" / "National Sales Data_Cement.xlsx"
OUT_DIR = ROOT / "data" / "outputs" / "demand_planning"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SEASONAL_PERIOD = 12
ACCL_GROUP = "Akij"


# ═══════════════════════════════════════════════════════════════
# DATA
# ═══════════════════════════════════════════════════════════════

def load_accl_monthly():
    """Monthly ACCL cement MT from the national brand panel. Returns a Series with PeriodIndex."""
    d = pd.read_excel(SRC, sheet_name="Cement Sales Master Data")
    d["Date"] = pd.to_datetime(d["Date"], errors="coerce")
    accl = d[d["Company_Group"] == ACCL_GROUP]
    s = accl.groupby(accl["Date"].dt.to_period("M"))["Sales_In_MT"].sum()
    s = s[s > 0]
    s.index = pd.PeriodIndex(s.index, freq="M")
    return s.sort_index()


# ═══════════════════════════════════════════════════════════════
# SEASONALITY
# ═══════════════════════════════════════════════════════════════

def seasonal_index(series, period=12):
    """Multiplicative seasonal index (mean=1.0)."""
    if len(series) < period:
        return np.ones(period)
    vals = series.values.astype(float)
    n = len(vals) // period * period
    if n < period:
        return np.ones(period)
    mat = vals[:n].reshape(-1, period)
    idx = mat.mean(axis=0)
    idx = idx / idx.mean()
    return idx


def deseasonalise(series, s_idx):
    """Remove multiplicative seasonality."""
    n = len(series)
    idx_arr = np.tile(s_idx, (n // len(s_idx)) + 1)[:n]
    return series.values / idx_arr


def reseasonalise(values, s_idx, offset=0):
    """Apply multiplicative seasonality."""
    n = len(values)
    idx_arr = np.tile(np.roll(s_idx, -offset), (n // len(s_idx)) + 1)[:n]
    return values * idx_arr


# ═══════════════════════════════════════════════════════════════
# METRICS
# ═══════════════════════════════════════════════════════════════

def wape(actual, forecast):
    """Volume-weighted absolute percentage error."""
    return np.sum(np.abs(forecast - actual)) / np.sum(actual)

def bias(actual, forecast):
    """Systematic directional error. Negative = under-forecast."""
    return np.sum(forecast - actual) / np.sum(actual)

def mase(actual, forecast, naive_forecast):
    """Mean absolute scaled error vs seasonal naive."""
    return np.mean(np.abs(forecast - actual)) / np.mean(np.abs(naive_forecast - actual))


# ═══════════════════════════════════════════════════════════════
# MODEL 1: Seasonal Naive (benchmark)
# ═══════════════════════════════════════════════════════════════

def forecast_seasonal_naive(train, horizon, period=12):
    """Forecast(t+h) = Actual(t+h-period)."""
    vals = train.values
    fc = np.zeros(horizon)
    for h in range(horizon):
        idx = len(vals) - period + h
        fc[h] = vals[idx] if idx >= 0 else vals[-1]  # fallback: last value
    return fc


# ═══════════════════════════════════════════════════════════════
# MODEL 2: Current damped-trend (the incumbent)
# ═══════════════════════════════════════════════════════════════

def forecast_current(train, horizon, s_idx, period=12):
    """Port of analyze.py: deseasonalise -> level(tail 6) -> damped trend -> reseasonalise."""
    y = train.values.astype(float)
    de = deseasonalise(pd.Series(y), s_idx)
    n = len(de)
    level = de[-6:].mean() if n >= 6 else de.mean()
    if n >= 8:
        slope = (de[-4:].mean() - de[-8:-4].mean()) / 4.0
    else:
        slope = 0.0
    slope = np.clip(slope, -0.05 * level, 0.05 * level)
    offset = len(train) % period
    fc = np.zeros(horizon)
    for i in range(horizon):
        base = max(level + slope * (i + 1) * 0.5, 0.0)  # damped trend
        m_idx = (offset + i) % period
        fc[i] = base * s_idx[m_idx]
    return fc


# ═══════════════════════════════════════════════════════════════
# MODEL 3: AutoETS
# ═══════════════════════════════════════════════════════════════

def forecast_autoets(train, horizon, period=12):
    """Search ETS error/trend/seasonal combos by AICc. Pick best. Forecast.

    train must be a pd.Series with PeriodIndex (freq='M') so statsmodels infers freq.
    """
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel

    best_aicc = np.inf
    best_model = None

    errors = ["add", "mul"]
    trends = ["add", None]
    seasonals = ["add", "mul"]
    dampeds = [True, False]

    for e in errors:
        for t in trends:
            for s in seasonals:
                for d in dampeds:
                    if t is None and d:
                        continue  # can't damp no trend
                    try:
                        m = ETSModel(
                            train, error=e, trend=t, seasonal=s,
                            damped_trend=d, seasonal_periods=period,
                        )
                        fit = m.fit(disp=False, maxiter=500)
                        if fit.aicc < best_aicc:
                            best_aicc = fit.aicc
                            best_model = fit
                    except Exception:
                        continue

    if best_model is None:
        return forecast_seasonal_naive(train, horizon, period)  # fallback

    fc = best_model.forecast(horizon)
    return np.maximum(fc, 0.0)


# ═══════════════════════════════════════════════════════════════
# MODEL 4: AutoARIMA
# ═══════════════════════════════════════════════════════════════

def forecast_autoarima(train, horizon, period=12):
    """pmdarima auto_arima with seasonal support."""
    from pmdarima import auto_arima as pm_auto_arima

    y = train.values.astype(float)
    try:
        model = pm_auto_arima(
            y, seasonal=True, m=period, stepwise=True,
            max_p=3, max_q=3, max_P=1, max_Q=1,
            max_d=2, max_D=1,
            trace=False, error_action="ignore",
            suppress_warnings=True, n_jobs=1,
            maxiter=100,
        )
        fc, _ = model.predict(n_periods=horizon, return_conf_int=True, alpha=0.20)
    except Exception:
        return forecast_seasonal_naive(train, horizon, period)

    return np.maximum(fc, 0.0)


# ═══════════════════════════════════════════════════════════════
# MODEL 5: Theta
# ═══════════════════════════════════════════════════════════════

def forecast_theta(train, horizon, period=12, theta_param=2):
    """Standard Theta method (Assimakopoulos & Nikolopoulos, 2000).

    Decompose multiplicative -> fit linear trend (theta=0) + SES with drift
    (theta=2) -> average -> reseasonalise.
    """
    from statsmodels.tsa.holtwinters import SimpleExpSmoothing

    y = train.values.astype(float)
    n = len(y)
    s_idx = seasonal_index(train, period)
    de = deseasonalise(pd.Series(y), s_idx)

    # --- Theta(0): linear trend on deseasonalised ---
    t_vals = np.arange(n)
    slope, intercept, _, _, _ = sp_stats.linregress(t_vals, de)
    trend_line = intercept + slope * t_vals

    # --- Theta(theta): double the curvature ---
    # theta_line = theta * de - (theta - 1) * trend_line
    # For theta=2: theta_line = 2*de - trend_line
    if theta_param == 2:
        theta_line = 2.0 * de - trend_line
    else:
        theta_line = theta_param * de - (theta_param - 1) * trend_line

    # SES on theta line
    ses_model = SimpleExpSmoothing(theta_line).fit(optimized=True)
    drift = (theta_line[-1] - theta_line[0]) / (n - 1) if n > 1 else 0

    # Forecast theta line
    theta_fc = np.zeros(horizon)
    theta_fc[0] = ses_model.level[0] + drift if hasattr(ses_model, 'level') else ses_model.fittedvalues[-1] + drift
    for i in range(horizon):
        # Simpler: SES forecast with drift
        theta_fc[i] = ses_model.fittedvalues[-1] + drift * (i + 1)

    # --- Theta(0) forecast: extrapolate linear trend ---
    trend_fc = intercept + slope * (np.arange(n, n + horizon))

    # --- Combine ---
    combined = 0.5 * (theta_fc + trend_fc)

    # Reseasonalise
    offset = len(train) % period
    fc = reseasonalise(combined, s_idx, offset)
    return np.maximum(fc, 0.0)


# ═══════════════════════════════════════════════════════════════
# MODEL 6: Holt-Winters (multiplicative, damped)
# ═══════════════════════════════════════════════════════════════

def forecast_hw(train, horizon, period=12):
    """Multiplicative Holt-Winters with damped trend.

    train must be a pd.Series with PeriodIndex (freq='M') so statsmodels infers freq.
    """
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    try:
        model = ExponentialSmoothing(
            train, seasonal_periods=period, trend="add",
            seasonal="mul", damped_trend=True,
        )
        fit = model.fit(optimized=True)
        fc = fit.forecast(horizon)
    except Exception:
        return forecast_current(train, horizon, seasonal_index(train, period), period)

    return np.maximum(fc, 0.0)


# ═══════════════════════════════════════════════════════════════
# BACKTEST ENGINE
# ═══════════════════════════════════════════════════════════════

MODELS = {
    "Seasonal Naive": forecast_seasonal_naive,
    "Current (damped trend)": None,  # needs s_idx — handled specially
    "AutoETS": forecast_autoets,
    "AutoARIMA": forecast_autoarima,
    "Theta": forecast_theta,
    "Holt-Winters": forecast_hw,
}


def run_backtest(series, train_end_idx, test_len=6):
    """Run all 6 models on one backtest origin. Returns list of score dicts."""
    train = series.iloc[: train_end_idx + 1]
    test = series.iloc[train_end_idx + 1 : train_end_idx + 1 + test_len]
    actual = test.values.astype(float)

    s_idx = seasonal_index(train)
    period = SEASONAL_PERIOD

    # seasonal naive (needed for MASE)
    naive_fc = forecast_seasonal_naive(train, test_len, period)

    results = []
    for name, fn in MODELS.items():
        try:
            if fn is None:  # Current method
                fc = forecast_current(train, test_len, s_idx, period)
            else:
                fc = fn(train, test_len, period)

            fc = np.nan_to_num(fc, nan=0.0)

            results.append({
                "model": name,
                "wape": round(float(wape(actual, fc)), 4),
                "bias": round(float(bias(actual, fc)), 4),
                "mase": round(float(mase(actual, fc, naive_fc)), 4),
                "forecast": [round(float(v), 1) for v in fc],
                "actual": [round(float(v), 1) for v in actual],
                "naive_forecast": [round(float(v), 1) for v in naive_fc],
            })
        except Exception as exc:
            results.append({
                "model": name,
                "wape": None,
                "bias": None,
                "mase": None,
                "error": str(exc),
            })

    return results


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    series = load_accl_monthly()
    print(f"ACCL monthly series: {len(series)} months, {series.index[0]} to {series.index[-1]}")
    print(f"Mean: {series.mean():.0f} MT,  Min: {series.min():.0f} MT,  Max: {series.max():.0f} MT")
    print()

    # Backtest origins: look up index positions for the cut months
    months = list(series.index)

    # Origin 1: train up to May 2025, test Jun-Nov 2025
    o1_cut = months.index(pd.Period("2025-05", freq="M"))
    # Origin 2: train up to Nov 2024, test Dec 2024-May 2025
    o2_cut = months.index(pd.Period("2024-11", freq="M"))

    print(f"Origin 1: train through {months[o1_cut]}, test {months[o1_cut+1]} to {months[o1_cut+6]}")
    print(f"Origin 2: train through {months[o2_cut]}, test {months[o2_cut+1]} to {months[o2_cut+6]}")
    print()

    o1_results = run_backtest(series, o1_cut, 6)
    o2_results = run_backtest(series, o2_cut, 6)

    # Merge: average WAPE/BIAS/MASE across origins
    o1_by_model = {r["model"]: r for r in o1_results}
    o2_by_model = {r["model"]: r for r in o2_results}

    leaderboard = []
    for name in MODELS:
        r1 = o1_by_model.get(name, {})
        r2 = o2_by_model.get(name, {})

        w1 = r1.get("wape")
        w2 = r2.get("wape")
        b1 = r1.get("bias")
        b2 = r2.get("bias")
        m1 = r1.get("mase")
        m2 = r2.get("mase")

        avg_wape = round((w1 + w2) / 2, 4) if (w1 is not None and w2 is not None) else None
        avg_bias = round((b1 + b2) / 2, 4) if (b1 is not None and b2 is not None) else None
        avg_mase = round((m1 + m2) / 2, 4) if (m1 is not None and m2 is not None) else None

        bias_pass = abs(avg_bias) < 0.05 if avg_bias is not None else False

        leaderboard.append({
            "model": name,
            "wape_o1": w1, "wape_o2": w2, "wape_avg": avg_wape,
            "bias_o1": b1, "bias_o2": b2, "bias_avg": avg_bias,
            "mase_o1": m1, "mase_o2": m2, "mase_avg": avg_mase,
            "bias_pass": bias_pass,
        })

    # Sort: best WAPE first
    leaderboard.sort(key=lambda x: x["wape_avg"] if x["wape_avg"] is not None else 999)

    # Determine champion
    champion = None
    for lb in leaderboard:
        if lb["wape_avg"] is not None and lb["bias_pass"]:
            champion = lb
            break

    # Print leaderboard
    print("=" * 90)
    print(f"{'Model':<24} {'WAPE O1':>8} {'WAPE O2':>8} {'WAPE Avg':>9} {'BIAS Avg':>9} {'MASE':>7} {'BiasOK':>6}")
    print("-" * 90)
    for lb in leaderboard:
        w1 = f"{lb['wape_o1']:.4f}" if lb["wape_o1"] is not None else "FAIL"
        w2 = f"{lb['wape_o2']:.4f}" if lb["wape_o2"] is not None else "FAIL"
        wa = f"{lb['wape_avg']:.4f}" if lb["wape_avg"] is not None else "FAIL"
        ba = f"{lb['bias_avg']:+.4f}" if lb["bias_avg"] is not None else "FAIL"
        ma = f"{lb['mase_avg']:.3f}" if lb["mase_avg"] is not None else "FAIL"
        bp = "PASS" if lb["bias_pass"] else "FAIL"
        flag = " <-- CHAMPION" if lb is champion else ""
        print(f"{lb['model']:<24} {w1:>8} {w2:>8} {wa:>9} {ba:>9} {ma:>7} {bp:>6}{flag}")
    print("=" * 90)

    if champion:
        print(f"\nChampion: {champion['model']}  (WAPE {champion['wape_avg']:.4f}, BIAS {champion['bias_avg']:+.4f})")
    else:
        print("\nNo model passed the BIAS gate. Falling back to Seasonal Naive.")

    # Save leaderboard JSON for the web app
    champion_name = champion["model"] if champion else "Seasonal Naive"
    payload = {
        "series": "ACCL (all units) from National Sales Data_Cement.xlsx",
        "n_months": len(series),
        "period": f"{series.index[0]} to {series.index[-1]}",
        "backtest_origins": [
            {"train_through": "2025-05", "test_window": "Jun 2025 – Nov 2025"},
            {"train_through": "2024-11", "test_window": "Dec 2024 – May 2025"},
        ],
        "champion": champion_name,
        "champion_wape": champion["wape_avg"] if champion else None,
        "champion_bias": champion["bias_avg"] if champion else None,
        "leaderboard": leaderboard,
        "origin1_details": o1_results,
        "origin2_details": o2_results,
    }

    # Generate champion 12-month forward forecast on full data
    full_train = series
    full_s_idx = seasonal_index(full_train)
    horizon = 12
    champion_fc = None

    if champion:
        champ_fn = MODELS.get(champion_name)
        if champ_fn is None:
            full_fc = forecast_current(full_train, horizon, full_s_idx)
        else:
            full_fc = champ_fn(full_train, horizon)

        last_month = series.index[-1]
        fc_months = pd.period_range(last_month + 1, periods=horizon, freq="M")
        champion_fc = [
            {"month": str(m), "forecast_mt": round(float(v), 1)}
            for m, v in zip(fc_months, full_fc)
        ]
        payload["champion_forecast"] = champion_fc

        print(f"\n12-month champion forecast ({champion_name}), starting {fc_months[0]}:")
        for m, v in zip(fc_months, full_fc):
            print(f"  {m}: {v:,.0f} MT")

    leaderboard_path = OUT_DIR / "bakeoff_leaderboard.json"
    leaderboard_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nSaved: {leaderboard_path}")

    return leaderboard, champion


if __name__ == "__main__":
    main()
