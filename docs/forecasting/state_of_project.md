# State of project - read-only fact-finding (revision 6 facts)

Scope: answers verified from files under `planning-app/` and `planning-app/data/outputs/`. "NOT VERIFIED" =
could not be established from a file. No code/config/data/document was modified except the creation of this
file (the earlier CSV tables under `data/outputs/forecast/state_check/` have been removed; only
`PC2_catalog.csv` remains).

Key paths used:
- ingest run: `data/outputs/forecast/run_20261010T084919Z/{series.parquet,actuals.parquet,run_metadata.json,dq_gate.json}`
- backtest (corrected full run): `data/outputs/forecast/backtest/run_20261010T084920Z/{metrics.parquet,timings.json,manifest.json,clipping.json}`
- stage4: `data/outputs/forecast/stage4/run_20261010T090706Z/{forecasts.parquet,model_selection.json,external_variable_tests.json,holdout.json,intervals.json,scenarios.json,top_accounts.json,clipping.json,sensitivity_selected.json,provisional_sensitivity.json,recent_origin_wape.json}`
- zero-shot: `data/outputs/forecast/zeroshot/{preds.parquet,series.parquet}`; external: `data/outputs/forecast/external/ail_rainfall_monthly.csv`
- UI: `data/outputs/forecast/ui/forecast_ui.json`, `ui/planner_adjustments.json`
- config: `forecasting/config/{config.yaml,sbus.yaml,external_variables.yaml,models.yaml}`
- (removed from this revision's scope: `report_extra.json`, `data/outputs/forecast/diagnostics/`, `zeroshot_results.json`, `state_check/*.csv` except `PC2_catalog.csv`.)

---

## A. DATA AND SERIES

**A1. Final-forecast series** (from `series.parquet`).
| series_id | first month | last actual month | n months | last-12 actual MT |
|---|---|---|---|---|
| AIL\|channel\|Corporate | 2023-01 | 2026-09 | 45 | 45,816.0 |
| AIL\|channel\|Intercompany | 2023-01 | 2026-09 | 44 | 2,401.5 |
| AIL\|channel\|Trade | 2023-01 | 2026-09 | 45 | 128,771.8 |
| AIL\|company | 2023-01 | 2026-09 | 45 | 176,989.3 |
| AIL\|sbu\|external | 2023-01 | 2026-09 | 45 | 174,587.8 |
| AIL\|zone\|Trade\|Dhaka | 2023-01 | 2026-09 | 45 | 71,367.1 |
| AIL\|zone\|Trade\|North | 2023-01 | 2026-09 | 45 | 21,135.5 |
| AIL\|zone\|Trade\|North East | 2023-01 | 2026-09 | 45 | 12,430.8 |
| AIL\|zone\|Trade\|South | 2023-01 | 2026-09 | 45 | 23,838.4 |

Intercompany has 44 months because 2024-08 is genuinely missing (not junk).

**A2. Source & de-duplication.** Training series are built from **one consolidated raw xlsx** via the
generic `tabular` adapter (`forecasting/adapters/base.py::read_raw`), not from a DQ parquet. The file
`data/raw/AIL-Total_Monthly-2023 to 2026.xlsx` (sheet `Data`, header row 1) holds **11,069 rows**; it is
split into the three named sources by `filter: {column: Channel, value: ...}` in
`forecasting/config/sbus.yaml`. `to_standard` drops junk rows (bad/1970 dates) and calls `drop_duplicates()`.
Channel totals MT after cleaning: Corporate **193,008**, Trade **389,955**, Intercompany **7,112**.

**A3. DQ monthly-totals cross-check.** The old DQ layer has been **retired**. There is no longer a
`monthly_totals_by_channel.csv` comparison; the corresponding test `test_monthly_totals_match_dq_layer` is
now **skipped** (reason: "DQ layer not available"). Cleanliness is enforced by the DQ gate instead (see A6).

**A4. 2026-09 (provisional).** Flagged only; **included in training**. `config.yaml:provisional_months=[2026-09]`;
`actuals.parquet` has **150 rows** flagged `provisional_flag=True` for month 2026-09.

**A5. Slump intervention.** Step dummy (1 inside window, 0 elsewhere), configured in
`forecasting/config/config.yaml:interventions` for `AIL|channel|Trade`, `AIL|channel|Corporate`,
`AIL|sbu|external`, `AIL|company` = `slump: ["2024-07","2025-06"]` (12 months). Applied via
`external.intervention_frame` (0 in the forecast period). Months chosen from the DQ-31 structural-break
finding (slump mid-2024 to early-2025); see `docs/forecasting/decision_log.md` (#10) and
`01_model_report.md`.

**A6. DQ gate** (`run_20261010T084919Z/dq_gate.json`): **PASS with warnings** — Corporate 2 grain-duplicate
warnings, Intercompany 4 grain-duplicate warnings, Intercompany 1 missing-month warning (2024-08, genuine);
`hard_failures` = none. series_types: account **719**, channel **3**, company **1**, sbu **1**, zone **4**;
total **728** series.

## B. BACKTEST MECHANICS

**B1. Origins.** `config.yaml:backtest_origins = ["2024-12","2026-02"]` -> 15 monthly origins.
n_origins per horizon (targets capped at cut 2026-03): h1:15, h2:14, h3:13, h4:12, h5:11, h6:10, h7:9, h8:8,
h9:7, h10:6, h11:5, h12:4. File: computed from `config.yaml` + `backtest.py`.

**B2. Refit.** Yes - expanding-window refit at **every origin**; `backtest.backtest_series` builds a fresh,
unfitted model per origin (`build_model(...)` inside the origin loop). No parameter is tuned once and reused.

**B3. "Mean overall WAPE".** Each model's per-series *overall* WAPE is `sum|err| / sum|actual|` over all
evaluated origin x horizon rows for that series (`backtest.summarize`, bucket `all`); the leaderboard is the
**simple (unweighted) mean of that value across the 9 aggregate series** (`run_backtest.py`:
`metrics[horizon_bucket=='all'].groupby('model')['wape'].mean()`). Not volume-weighted.

**B4. Leaderboard & metrics.** File `backtest/run_20261010T084920Z/metrics.parquet` (432 rows = 12 models x
9 series x 4 buckets). Mean overall WAPE: chronos_bolt **0.2841**, naive **0.3773**, ma3 **0.3789**, ets
**0.3789**, ma6 **0.4031**, structural **0.4122**, lightgbm **0.4394**, theta **0.4544**, drift **0.5019**,
seasonal_naive **0.5158**, sarimax **0.5436**, stl_ets **0.6489**.

**B5. Future external values & lags.** `external.lagged_frame`: known-in-advance use their **actual future
values**; leading variables are **frozen at the last observed value (origin - lag)**; forecast-needed = n/a;
scenario/constraint not base features. Lags (`external_variables.yaml`): remittance_usd_mn **2**;
lc_open_raw_materials_usd_mn **1**; lc_open_capital_machinery_usd_mn **1**; usd_bdt_avg **1**;
cpi_inflation_p2p_pct **1**; rainfall_anomaly_pct **1**. (Calendar/budget/ADP lag 0.)

**B6. Leakage test.** `forecasting/tests/test_stage1.py::test_external_leakage_guard`: (i) for every leading
variable, `external.last_available_month(var, origin) == origin - lag`; (ii) `lagged_frame` for the future
produces, for each leading column, at most **one distinct value** (i.e., the feature is frozen at the
origin-lag observation and does not peek at future actuals).

## C. SELECTION AND FINAL FORECAST

**C1. Selection per series x bucket.** File `model_selection.json` (27 rows = 9 series x 3 buckets). Columns:
selected_models, weights (equal), best_model, fallback flag, external_vars_used. `chronos_bolt` is the
selected best model for most series x buckets. `external_variables_used` is now recorded per selected model
(empty arrays in this run — see E2).

**C2. Corporate top-accounts path** (`stage4._top_accounts_backtest`): the top-20 accounts are **re-selected
per origin** (trailing 24m as of the origin) in the backtest, and on data through the last actual month for
the final forecast. Bottom-up vs direct Corporate WAPE(1-6): **0.2296 vs 0.3193 -> bottom-up selected**
(`top_accounts.json`). (The earlier `report_extra.py::item7_top_accounts`, which selected once on full
history, is superseded.)

**C3. Hierarchy reconciliation.** Bottom-up via `stage4._reconcile_forecasts`: Trade := sum(zones);
external := Corporate + Trade; company := external + Intercompany, applied to every quantile. For base
2026-10 (from `forecasts.parquet`): zones sum **=** Trade = 11,782.4 (diff 0.0000); Corporate+Trade **=**
external = 15,530.6 (diff -0.0000); external+Intercompany **=** company = 15,744.1 (diff 0.0000). MinT is
**not** implemented (reconciliation is bottom-up in `stage4._reconcile_forecasts`; MinT noted as optional).

**C4. Final forecast table** (series x month 2026-10..2027-09 point MT; from `forecasts.parquet`).
Totals/growth: Corporate 44,978.4 (**-1.83%**); Intercompany 2,695.2 (**+12.23%**); Trade 139,696.4
(**+8.48%**); company 187,370.0 (**+5.87%**); external 184,674.8 (**+5.78%**); Dhaka 82,641.2 (**+15.80%**);
North 22,309.2 (**+5.55%**); North East 12,987.6 (**+4.48%**); South 21,758.4 (**-8.73%**).

**C5. Final refit window.** Yes - the final models are refit on **all actuals through 2026-09**
(`fut_idx` starts 2026-10; `stage4._final_forecast` fits on the full series). The **holdout period
(2026-04..09) IS included** in the final refit (only excluded from selection/backtest).

## D. MODEL FIXES (from `forecasting/models/statistical.py`, `ml.py`)

**D1. Structural.** `UnobservedComponents(level="local level", seasonal=12)`, **no exog, no intervention**;
output clipped by `_clip` to [0, 3 x train max]. Clipping activations are now logged in
`backtest/run_20261010T084920Z/clipping.json` (`backtest_by_model`): structural **4** backtest activations.

**D2. SARIMAX.** Order **(1,1,1)**, seasonal **(0,1,1,12)**, enforce_stationarity/invertibility True; exog
whitelist `["eid_closure_days_total","working_days_6day","fy_end_flag","monsoon_flag","dry_season_flag","slump","disruption_days_full","flood_major_flag"]`, standardized on train. Clipping activations (`clipping.json`): SARIMAX **125** backtest activations.

**D3. STL+ETS.** Bug: the future seasonal term was indexed `(len+i) % 12` instead of the calendar month of
the first observation. Fix: store `first_month_` and use `(future_month - first_month_) % 12`.

**D4. LightGBM.** Files `forecasting/models/ml.py`. Features: lags **[1,2,3,6,12]**, `roll3`, `roll6`,
`month`, `fyend`, plus any exog columns present. **Recursive** multi-step forecast (feeds each prediction back
as a lag). **Per-series** (one model per series), not pooled.

**D5. Chronos-Bolt (zero-shot).** Now runs **in-pipeline** (see I1) via a torch-first subprocess, leading the
leaderboard at 0.2841.

## E. EXTERNAL VARIABLES

**E1. Kept variables.** File `external_variable_tests.json` (48 rows = 8 series x 6 features; 5 keeps):
| series | feature | model tested | WAPE w/o | WAPE with | origins won |
|---|---|---|---|---|---|
| AIL\|channel\|Corporate | remittance_usd_mn_yoy | lightgbm | 0.3449 | 0.2737 | 11/15 |
| AIL\|channel\|Trade | remittance_usd_mn | lightgbm | 0.4171 | 0.3830 | 11/15 |
| AIL\|zone\|Trade\|Dhaka | remittance_usd_mn | lightgbm | 0.4717 | 0.4513 | 10/15 |
| AIL\|zone\|Trade\|Dhaka | lc_open_raw_materials_usd_mn | lightgbm | 0.4717 | 0.4516 | 12/15 |
| AIL\|zone\|Trade\|North East | remittance_usd_mn | lightgbm | 0.5434 | 0.5115 | 11/15 |

**E2. Are kept variables used in a selected model?** **No.** `model_selection.json` now records
`external_variables_used` per selected model (empty arrays in this run) — none of the 5 kept external-variable
candidate models entered the final ensemble, so no external variable is used in the final forecast.

**E3. Rainfall.** Yes - `data/outputs/forecast/external/ail_rainfall_monthly.csv` was generated by running
`Data/AIL/ail_external/fetch_rainfall.py` here (output written to the outputs folder to avoid modifying the
read-only external dir). Coverage **2023-01..2026-09 (45 months)**; columns = 8 divisions
(dhaka, chattogram, rajshahi, khulna, barishal, sylhet, rangpur, mymensingh), national mean,
1991-2020 normal, `rainfall_anomaly_pct`. The registry uses only the single national `rainfall_anomaly_pct`
(catalog_var_id WTH-01); mapping of divisions to Trade zones: **NOT VERIFIED / not implemented** (no
division->zone code in `forecasting/external.py` or adapters).

## F. INTERVALS, SCENARIOS, SENSITIVITY, HOLDOUT

**F1. Conformal intervals.** Residuals used = **per series, pooled across all backtest origins within each
horizon bucket**, from the **best selected model** (stage4 `_conformal`). Coverage in `intervals.json` is
measured **on the same residuals used for calibration** (in-sample conformal) -> optimistic. The `method`
string is now descriptive ("conformal on backtest residuals of the selected best model per series x bucket;
offsets = -quantile(pred-actual)"), not a placeholder. Example `AIL|channel|Corporate`: cov80/cov95 =
short 0.762/0.905, medium 0.758/0.939, long 0.795/0.949. (Some aggregate series — company, Trade — have empty
offsets/coverage entries in this run.)

**F2. Scenarios.** Computed by adding an **exog-capable model (SARIMAX) to the ensemble for scenario
runs** (`stage4._final_forecast`: if no selected model supports exog, append SARIMAX) and mutating the future
exog (`disruption_days_full = 5` in 2027-01/02; `flood_major_flag = 1` in 2027-05). File `scenarios.json`
(coefficients + notes; 13 series/feature pairs "not estimable from history"). Examples (12m MT, from
`forecasts.parquet`): company base 187,370.0 / disruption 189,708.1 (+1.25%) / flood 185,914.5 (-0.78%);
Corporate 44,978.4 / 47,046.4 (+4.60%) / 43,595.2 (-3.08%); Trade 139,696.4 / 139,840.0 (+0.10%) /
139,569.1 (-0.09%); Intercompany 2,695.2 / 2,821.7 (+4.69%) / 2,750.2 (+2.04%).

**F3. Sensitivity (DQ-30).** No series cut. File `sensitivity_selected.json`. (a) **Down-weight**: 2025 values
replaced by `0.5*actual + 0.5*seasonal_expectation`. (b) **Impute**: 2025 = seasonal_norm x mean(2024 level).
Intercompany is the most sensitive: base 2,695.1 -> down-weight 2,161.6 (**-19.79%**) -> impute 2,010.8
(**-25.39%**); all other series move ~0-3% (Dhaka impute +3.37%). (The older `sensitivity_2025.json` is no
longer emitted.)

**F4. Holdout.** Setup = selected ensembles **refit at origin 2026-03**, evaluated on 2026-04..09 once
(`stage4._holdout`). Result `holdout.json`: origin 2026-03, **mean per-series WAPE 0.256**, **mean 80%
coverage 0.815** (>= 0.65, no widening factor needed). Per-series WAPE and coverage are stored in
`holdout.json`.

## G. CODE HEALTH AND REPRODUCIBILITY

**G1. Broken tokens / control characters.** **Resolved.** The docs no longer contain control characters
(BEL/TAB/FF/NUL/CR) from the earlier PowerShell double-quoted here-string append bug (markdown backticks
interpreted as PowerShell escapes). A repository-hygiene test
(`test_stage9.py::test_repository_has_no_control_characters`) now guards against regression. No `.py`,
`.yaml`, `.json` file contains control characters.

**G2. Determinism.** The full pipeline now runs end-to-end (one command in the pinned venv). Three ingest
runs are present (`run_20261010T065939Z`, `run_20261010T070037Z`, `run_20261010T084919Z`); the first two are
**bit-identical** (4,192 rows / 2,343,178.18 MT each), confirming ingest determinism. Two full runs are
present (stage4 `run_20261010T071233Z` and `run_20261010T090706Z`) but they **differ** (e.g. company
181,945.5 vs 187,370.0) because the earlier run predates the Intercompany 2023 backfill — so a clean
same-code double-run is NOT directly re-confirmed from the current artifacts. The named `run_DET_A` /
`run_DET_B` determinism pair is **NOT PRESENT**; the README's "reproduces within 0.005%" claim is asserted,
not independently re-verified here.

**G3. Tests (17 = 16 passed, 1 skipped).** Files `forecasting/tests/`.
1. `test_stage1.py::test_adapter_schema` - adapter output has the standard columns, Period month, numeric y, no 1970 dates.
2. `test_stage1.py::test_hierarchy_sums` - child series sum to parents per month.
3. `test_stage1.py::test_no_duplicate_series_months` - no duplicate (series_id, month).
4. `test_stage1.py::test_monthly_totals_match_dq_layer` - **SKIPPED** (DQ layer retired; "DQ layer not available").
5. `test_stage1.py::test_external_leakage_guard` - leading vars usable only up to origin-lag; frozen (B6).
6. `test_stage6.py::test_registry_validation` - SBU and external registry entries have required keys.
7. `test_stage6.py::test_synthetic_cem_adapter_and_gate` - a synthetic CEM SBU (different layout) builds series and passes the gate.
8. `test_stage6.py::test_reduced_model_pool_for_18_months` - 24-month models excluded at 18 months of history.
9. `test_stage6.py::test_end_to_end_fixture` - synthetic SBU runs a small backtest end-to-end.
10. `test_stage8.py::test_holdout_guard_no_targets_after_cut` - no backtest target after 2026-03.
11. `test_stage8.py::test_forecast_reconciliation` - forecast children = parents per month/scenario/quantile.
12. `test_stage8.py::test_scenarios_differ_from_base` - at least one scenario differs from base.
13. `test_stage9.py::test_account_selection_uses_only_past` - top-account selection at an origin uses only past data.
14. `test_stage9.py::test_scenario_uses_same_ensemble_as_base` - scenario rows carry the same ensemble as base.
15. `test_stage9.py::test_forecast_value_added` - FVA compares statistical vs adjusted WAPE (synthetic).
16. `test_stage9.py::test_registry_validates_against_catalog` - every catalog_var_id exists in the group catalog.
17. `test_stage9.py::test_repository_has_no_control_characters` - no tracked text file has control characters.

**G4. Git.** `git status --short` = **NOT clean**: 3 modified code files (`forecasting/adapters/base.py`,
`forecasting/config/sbus.yaml`, `forecasting/stage4.py`) plus 3 modified docs (this README/state_of_project/
01_model_report), and untracked `.venv-forecast-pinned/`. Branch `feature/demand-forecasting`, **9 commits**
(was 7). `data/`, `*.xlsx`, `*.parquet`, weights and `.venv` are gitignored.

## H. UI AND PLANNER

**H1. AIL Forecast page** (`frontend/src/app/ail-forecast/page.tsx`): PageHeader with title/label, run id and
generated-at, and a "download planner template" link; a filter card (series selector, scenario selector,
holdout WAPE); actuals-vs-forecast chart with the 80% band and a forecast reference line; accuracy table
(WAPE by bucket + selected models); external-variables-tested table; planner-adjustments table (when present);
collapsible "Corporate top accounts" table (account, last-12m actual, monthly point + band); caveats panel.
Series shown: the 9 aggregate series (accounts appear in the collapsible table only). Scenarios: base,
disruption, flood. Caveats: the 6 listed in `publish.py:CAVEATS`. Screenshots: **NOT VERIFIED** (no UI
screenshots were captured); the earlier `data/outputs/forecast/diagnostics/` charts are no longer present.

**H2. Planner adjustments / FVA.** **No** adjustment has been ingested - `ui/planner_adjustments.json` =
`{adjustments: [], errors: [], note: "no upload present"}`. Forecast Value Added is **implemented** in
`forecasting/fva.py::forecast_value_added` (statistical vs adjusted WAPE per series/planner once actuals
exist) and **tested synthetically** (`test_stage9.py::test_forecast_value_added`); no real adjustment has
been ingested, so no FVA has been computed on live data.

## I. ZERO-SHOT AND EXTERNAL CATALOG

**I1. Zero-shot status.** `torch` **installed** (2.13.0+cpu, CPU index) and `chronos` **installed**
(`chronos-forecasting`; `amazon/chronos-bolt-small`); `timesfm` and `uni2ts`/Moirai **not installed**. Ran in
the backtest: **Yes** - Chronos-Bolt now runs **in-pipeline** at all 15 origins via a torch-first subprocess
(torch imported before pandas to avoid the Windows `WinError 1114` DLL conflict), leading the leaderboard at
WAPE 0.2841. Files: `data/outputs/forecast/zeroshot/{preds.parquet (1,620 rows), series.parquet (404 rows)}`,
`backtest/run_20261010T084920Z/timings.json`.

**I2. Group catalog.** `forecasting/validate_registry.py` validates `external_variables.yaml` against the
group catalog by `catalog_var_id` -> **PASS (43 registry variables, 0 mismatches)**. The registry was
re-authored to use catalog keys (the earlier "30 of 33 mismatched" result is superseded). Remaining file:
`state_check/PC2_catalog.csv`.

## Tables produced (CSV)
`data/outputs/forecast/state_check/` now contains only `PC2_catalog.csv`. The other tables
(`A1_series.csv`, `B4_metrics.csv`, `C1_selection.csv`, `C4_final_forecast.csv`, `E1_external_tests.csv`,
`F2_scenarios.csv`, `F4_holdout.csv`, `I2_catalog.csv`) have been removed; the equivalent facts are read
directly from the parquet/json artifacts listed in "Key paths used".
