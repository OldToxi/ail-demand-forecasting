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

---

# CHECKPOINT-2 REVISION (diagnostics + fixes)

## 1. Model diagnostics & fixes
Diagnostics (orecasting/diagnostics.py, data/outputs/forecast/diagnostics/*): actual-vs-forecast for
every model at origins 2024-12, 2025-06, 2026-02 for Corporate, Trade and Trade|Dhaka, plus exog-alignment
and intervention checks. Findings and fixes:
- **Structural** was producing 31,636 / 205,095 / 0 (local-linear-trend slope extrapolation on a series with
  a level break). **Fixed**: local level (no slope) + monthly seasonality, no exog, clipped to [0, 3x train max].
  WAPE **0.992 -> 0.412**.
- **SARIMAX** was unstable on the full collinear calendar exog. **Fixed**: a small exog whitelist
  (eid total, working_days_6day, fy_end, monsoon, dry, slump, disruption, flood) + clipping. WAPE **0.745 -> 0.528**.
- **STL+ETS** had a seasonal-indexing bug ((len+i)%12 instead of calendar-month alignment). **Fixed**; it
  remains the weakest model (0.649) because the ETS trend struggles with the 2024-25 level break - a genuine
  result, not a bug; selection does not pick it.
- **Intervention dummies** added per series (slump 2024-07..2025-06) via external.intervention_frame,
  **0 in the forecast period** (never extended). Applied to company too.
- Exog alignment verified: calendar features align to the target month; known-in-advance future values only.

**Corrected leaderboard (mean overall WAPE, aggregate series):**
naive 0.377 | ets 0.378 | ma3 0.379 | ma6 0.403 | **structural 0.412** | lightgbm 0.440 | theta 0.454 |
drift 0.502 | seasonal_naive 0.516 | **sarimax 0.528** | stl_ets 0.649.

## 2. External-variable tests (strict)
Tested against the **best exog-capable base model** (SARIMAX/LightGBM) per series; keep only if pooled WAPE
improves >= 3% **and** the variable wins in >= 2/3 of individual origins. **All Intercompany external
variables dropped.** remittance also tested detrended (YoY %).
Result - 4 keeps: Corporate **remittance_usd_mn_yoy** (0.345 -> 0.274), Trade|Dhaka **remittance_usd_mn**
(0.471 -> 0.451) and **lc_open_raw_materials_usd_mn** (0.471 -> 0.452), Trade|North East **remittance_usd_mn**
(0.543 -> 0.512). Everything else drops. (The Corporate result on the **YoY** form shows remittance is not
merely acting as a trend proxy there.)

## 3. Sensitivity (DQ-30) - no series cut
Trade 12-month forecast changed by **+1.7% (down-weighted 2025, soft blend)** and **+6.0% (2025 imputed from
the 2023-24 seasonal pattern scaled to level)** vs the base 153,008 MT. Seasonality preserved.

## 4. Backtest vs holdout
Best-model backtest WAPE for **horizons 1-6 (same window as the holdout) = 0.272**; horizons 1-12 = 0.339;
holdout (origin 2026-03) = 0.222. The "0.38 vs 0.22" gap is because the aggregate 1-12 backtest spans the
2024-25 slump and includes thin months 7-12. **Confirmed in writing: holdout months 2026-04..09 were never
used for selection, tuning or variable choice** (the backtest discards any target after 2026-03; enforced by
	est_holdout_guard_no_targets_after_cut).

## 5. Scenarios
Scenario runs now route through an exog-capable model (SARIMAX with disruption/flood regressors); base vs
disruption vs flood are reported per series (MT and %) in eport_extra.json. Series whose selected models
are non-exog still receive the scenario via the added SARIMAX member; scenarios are no longer identical to
base (validated by 	est_scenarios_differ_from_base). Note the estimated disruption/flood effect is small
for the aggregate series.

## 6. Forecast shape
Trade ETS forecast is **not flat** (coefficient of variation 0.138) and preserves the seasonal pattern in
months 7-12; training from 2025-01 gives a similar seasonal path (eport_extra.json: item6_shape).

## 7. Top accounts
Bottom-up Corporate (top-20 intermittent + residual) backtest **WAPE 0.291** vs direct Corporate total
**0.378** -> **bottom-up selected**. Surfaced on the UI as a collapsible **"Corporate top accounts"** table
(account, monthly point + band, last-12m actual); the planner template accepts account-level series_id.

## 8. Tests
orecasting/tests/ now has **12 tests**: existing 9 plus 	est_stage8.py (holdout guard; forecast
reconciliation children=parents per month/scenario/quantile; scenario != base). All pass.

## 9. Zero-shot
Microsoft Visual C++ runtime present; **torch CPU wheel installed from https://download.pytorch.org/whl/cpu
(2.14.1+cpu)**; **Chronos-Bolt (mazon/chronos-bolt-small) loads and forecasts successfully in a clean
process** (verified: predict_quantiles returns (1,12) mean and (1,12,5) quantiles). However, **within the
pipeline process the torch DLL fails (WinError 1114)** once numpy/pandas (and other native libs) load first -
a Windows DLL-conflict. **Recommendation: run the zero-shot step in WSL** (works there), or in a dedicated
process that imports torch before numpy. TimesFM and Moirai are not installed.
