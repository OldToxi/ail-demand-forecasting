# Model report (interim) - Stages 2-3
Status: Stage 2 (evaluation framework) and Stage 3 (model pool, non-zero-shot) implemented and run.
Stages 4-6 (selection/external-variable tests/scenarios/UI/extensibility) are **pending**.

## Evaluation framework (Stage 2)
- Horizon 12 months; buckets short 1-3 / medium 4-6 / long 7-12 (`backtest.buckets`).
- Rolling origins monthly **2024-12 .. 2026-02**; any target month after the backtest cut **2026-03**
  is discarded. Final holdout (2026-04..09 from origin 2026-03) reserved, evaluated once in Stage 4.
- Metrics: WAPE (headline), MASE (seasonal-naive scale), bias, 12-month cumulative volume error;
  reported by series, model and bucket with `n_origins`.
- Lag-aware exogenous data: known-in-advance features use actual future values; leading features are
  frozen at `origin - lag` (`external.lagged_frame`), verified by the leakage test.
- Minimum-history gate: models declare `min_history_months`; a series below it is skipped for that model.

## Model pool (Stage 3)
Common interface `fit(train, exog) / predict(horizon, exog) -> Forecast(point, q025,q10,q50,q90,q975)`.
- Baselines: naive, seasonal naive, MA3, MA6, drift.
- Statistical: AutoETS (AICc grid), STL+ETS (robust), Theta, SARIMAX(1,1,1)(0,1,1,12) with exog,
  Structural (UnobservedComponents, local trend + seasonality + exog). Exog standardized on train stats.
- ML: LightGBM per series (lags 1/2/3/6/12, rolling means, calendar), recursive multi-step.
- Intermittent (top-accounts, account level only): Croston-SBA, TSB, hurdle (P(order) x median size).
- Zero-shot: TimesFM, Chronos-Bolt, Moirai wired behind the interface; **skipped gracefully** this run
  (backends/weights not installed on this CPU box) - logged in `notes.json`.

## Backtest result - aggregate series (company, external, channels, 4 Trade zones)
Run `run_20261007T085731Z` (metrics in `data/outputs/forecast/backtest/`). Mean overall WAPE by model:

| model | mean WAPE (all) |
|---|---|
| naive | 0.3773 |
| ets | 0.3779 |
| ma3 | 0.3789 |
| ma6 | 0.4031 |
| theta | 0.4544 |
| lightgbm | 0.4638 |
| drift | 0.5019 |
| seasonal_naive | 0.5158 |
| stl_ets | 0.6396 |
| sarimax | 0.7454 |
| structural | 0.9915 |

Per-series winners were mixed (e.g., ETS best on company at WAPE 0.319; naive/MA competitive on zones).
This is expected pre-selection: Stage 4 selects per series x bucket with top-k ensembling and fallbacks.

## Run times (seconds, whole backtest)
`ets 24.2 · stl_ets 0.9 · theta 0.9 · sarimax 497.4 · structural 111.0 · lightgbm 8.4 · baselines ~0`
Total **~10.7 min** (target < 30 min). SARIMAX dominates; it is a candidate to drop per series if it does
not win.

## Known limitations / next
- Zero-shot models not exercised (CPU, weights not cached). Install + cache in Stage 3E follow-up.
- Quantiles currently use a residual-sigma band; empirical 80/95% coverage and conformal recalibration
  are Stage 4.8.
- External-variable tests, Eid-variant comparison, structural-break comparison, sensitivity (DQ-30),
  scenarios, hierarchy reconciliation (MinT), final holdout, UI wiring and the new-SBU demonstration
  remain (Stages 4-6).

## Stage 4 results (run 20261007T092722Z)
- **External-variable screening (LightGBM, one at a time, rule: >=3% better in a bucket and <=1% worse elsewhere):**
  - emittance_usd_mn -> **keep** for Corporate, Trade, company, external and all Trade zones.
  - lc_open_raw_materials_usd_mn -> **keep** for Intercompany, Trade, Trade|Dhaka.
  - disruption_days_full/partial, dp_fy_revised_tk_cr -> **drop** (no bucket-level gain).
  - ainfall_anomaly_pct -> **not screened** (lives in a separate rainfall file; load path pending).
- **Selection:** top-3 per series x bucket by WAPE (bias tie-break), fallback to seasonal naive when nothing beats it (none triggered on aggregate).
- **Structural-break / Eid variants:** compared (ets / stl_ets / structural + intervention; eid total vs last10 vs month-flag) - see break_eid_variants.json.
- **Reconciliation:** aggregate series reconcile by construction; bottom-up for company (external channels + intercompany).
- **Sensitivity (DQ-30):** Trade ETS WAPE 0.3704 full vs **1.0548** when 2025-01..11 are dropped -> the 2025 regime is material; flagged.
- **Final forecast:** 12 months **2026-10..2027-09** x 9 aggregate series x 3 scenarios (base/disruption/flood).
- **Final holdout (2026-04..09 from origin 2026-03): WAPE 0.2217** (evaluated once, not used for selection).

### Stage 4 limitations to carry forward
- Scenario shocks are currently placeholder multipliers; they must be re-expressed as exog (disruption days /
  flood flag) for exog-capable models.
- Interval calibration uses a residual-sigma band; empirical 80/95% coverage + conformal adjustment pending
  (needs persisted signed residuals).
- Account-level (top-accounts) path is implemented but not yet run end-to-end.
- Rainfall variable needs to be loaded from its own file in the screening.
