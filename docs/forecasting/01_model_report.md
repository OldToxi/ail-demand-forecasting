# Model report - AIL demand forecasting

Current results only in the main sections; superseded results are in the Revision history at the end.

## Evaluation framework
12-month horizon; buckets 1-3 / 4-6 / 7-12. Metrics: WAPE (headline), MASE, bias, cumulative volume error.
Rolling origins 2024-12..2026-02 (targets after 2026-03 discarded). Final holdout 2026-04..09 evaluated once
from origin 2026-03, never used for selection/tuning/variables. Lag-aware exog (known-in-advance uses actual
future values; leading frozen at origin-lag). Minimum-history gating per model.

## Model pool and fixes
Interface `fit/predict -> Forecast(point, q025,q10,q50,q90,q975)`. Baselines, AutoETS, STL+ETS, Theta,
SARIMAX, Structural(UC), LightGBM, intermittent (Croston-SBA/TSB/hurdle), zero-shot (Chronos-Bolt).
Fixes applied after diagnostics:
- STL+ETS: future seasonal indexed by calendar month (was `(len+i)%12`).
- Structural: local level + monthly seasonality, no exog, clipped to [0, 3x train max] (was local linear
  trend with slope extrapolation producing 31,636 / 205,095 / 0).
- SARIMAX: order (1,1,1)(0,1,1,12), small standardized exog set (eid total, working_days_6day, fy_end,
  monsoon, dry, slump, disruption, flood), clipped.
- Intervention: per-series slump dummy 2024-07..2025-06 (0 in the forecast period), for Trade, Corporate,
  external and company.
Corrected backtest leaderboard (mean overall WAPE): naive 0.377, ets 0.378, ma3 0.379, ma6 0.403,
structural 0.412, lightgbm 0.440, theta 0.454, drift 0.502, seasonal_naive 0.516, sarimax 0.528, stl_ets 0.649.
STL+ETS remains the weakest (level break) and is not selected. Recent-origin WAPE (2025-07..2026-02) is
reported alongside in `stage4/run_*/recent_origin_wape.json` (report only; not an automatic switch).

## External variables
Tested against the best **exog-capable** base model; keep only if pooled WAPE improves >= 3% AND wins in >= 2/3
origins; all Intercompany external variables dropped; remittance also tested detrended (YoY). Kept
combinations are registered as candidate models (`lightgbm+<var>`). Selection decides whether they enter the
ensemble; `model_selection.json` stores `external_variables_used` per selected model. In the current run no
external-variable candidate was selected, so none is used in the final ensemble.

## Intervals and holdout
Conformal offsets from the selected best model's backtest residuals per series x bucket. Holdout per-series
WAPE and 80%/95% coverage in `holdout.json`. Current run: mean holdout WAPE 0.263, mean 80% coverage 0.704
(>= 0.65, no widening factor needed). The `intervals.json` method string is current (conformal), not a
placeholder.

## Scenarios
Computed as `delta = SARIMAX(scenario exog) - SARIMAX(base exog)` on the same fit, added to the selected base
forecast; the ensemble composition is identical for base and scenario runs. Coefficients for
`disruption_days_full` and `flood_major_flag` (95% CI) are in `scenarios.json`; positive or zero-spanning
coefficients are reported as "not estimable from history".

## Top accounts
The top-20 Corporate accounts are re-selected **per origin** (trailing 24m as of the origin) in the backtest
(`select_top_accounts`), and on data through the last actual month for the final forecast. Corrected
bottom-up vs direct Corporate WAPE(1-6): 0.230 vs 0.306 -> bottom-up selected.

## Clipping audit
Every clipping activation is logged (model, series, origin, raw/clipped values, bound). Current run: 54
backtest events, 3 stage4 events (`clipping.json`).

## Zero-shot
torch is installed from the CPU index (2.14.1+cpu) and Chronos-Bolt (`amazon/chronos-bolt-small`) loads and
forecasts in a clean process. In the pipeline it is skipped because torch's DLL conflicts with other native
libraries once numpy/pandas load first (Windows WinError 1114). TimesFM and Moirai are not installed.
Recommend running the zero-shot step in WSL or a torch-first subprocess.

## Known limitations
See README.md. Main ones: sales-as-demand proxy; 2024-25 break; 2025 Trade regime; provisional 2026-09 and
2027 holidays; thin evidence months 7-12; zero-shot not run in-pipeline.

## Revision history (superseded)
- structural 0.992 and sarimax 0.745 (pre-fix) - replaced by 0.412 / 0.528.
- "mean overall WAPE" is the simple mean across the 9 aggregate series of each model's all-horizon WAPE
  (not volume-weighted).
- Earlier holdout figure 0.222 was an unweighted pooled value; the current per-series mean is 0.263.
- Earlier scenarios used placeholder multipliers and could be identical to base; now SARIMAX-delta.
- Earlier sensitivity cut 2025 out (WAPE 1.055); now down-weight + impute without cutting.
