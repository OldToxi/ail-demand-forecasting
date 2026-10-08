# State of project - read-only fact-finding (revision 5 facts)

Scope: answers verified from files under `planning-app/` and `planning-app/data/outputs/`. "NOT VERIFIED" =
could not be established from a file. No code/config/data/document was modified except the creation of this
file and the CSV tables under `data/outputs/forecast/state_check/`.

Key paths used:
- ingest run: `data/outputs/forecast/run_20261007T082713Z/{series.parquet,actuals.parquet,run_metadata.json,dq_gate.json}`
- backtest (corrected full run): `data/outputs/forecast/backtest/run_20261007T112751Z/{metrics.parquet,timings.json}`
- stage4: `data/outputs/forecast/stage4/run_20261007T120219Z/{forecasts.parquet,model_selection.json,external_variable_tests.json,holdout.json,intervals.json,reconciliation.json,accounts_top.json,sensitivity_2025.json,break_eid_variants.json}`
- extra reports: `data/outputs/forecast/report_extra.json`; diagnostics `data/outputs/forecast/diagnostics/`
- UI: `data/outputs/forecast/ui/forecast_ui.json`, `ui/planner_adjustments.json`
- config: `forecasting/config/{config.yaml,sbus.yaml,external_variables.yaml,models.yaml}`
- tables: `data/outputs/forecast/state_check/*.csv`

---

## A. DATA AND SERIES

**A1. Final-forecast series** (file `state_check/A1_series.csv`; from `series.parquet`).
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

**A2. Source & de-duplication.** Training series are built from the **raw xlsx via adapters** (not the DQ
parquet): `forecasting/adapters/base.py::read_raw` reads `Data/AIL/*.xlsx`; `to_standard` drops junk rows
(bad/1970 dates) and calls `drop_duplicates()`. Row counts (raw -> after junk+dedup), file
`series.parquet` / adapter code: Corporate **37,770 -> 37,766** (4 removed); Intercompany **1,041 -> 1,006**
(35 removed); Trade **31,038 -> 31,036** (2 removed). The removals combine the sentinel/junk rows (DQ-01)
and exact duplicates (DQ-05).

**A3. Pipeline vs DQ monthly totals** (`series.parquet` channel level vs
`Data/work/outputs/monthly_totals_by_channel.csv`, 45 months each). Max absolute difference:
Corporate **0.005 MT**, Intercompany **0.005 MT**, Trade **0.005 MT** (rounding of the DQ CSV to 1 dp).

**A4. 2026-09 (provisional).** Flagged only; **included in training**. `config.yaml:provisional_months=[2026-09]`;
`actuals.parquet` has 911 rows flagged `provisional_flag=True` for month 2026-09.

**A5. Slump intervention.** Step dummy (1 inside window, 0 elsewhere), configured in
`forecasting/config/config.yaml:interventions` for `AIL|channel|Trade`, `AIL|channel|Corporate`,
`AIL|sbu|external`, `AIL|company` = `slump: ["2024-07","2025-06"]` (12 months). Applied via
`external.intervention_frame` (0 in the forecast period). Months chosen from the DQ-31 structural-break
finding (slump mid-2024 to early-2025); see `docs/forecasting/decision_log.md` (#10) and
`01_model_report.md`.

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

**B4. Series x model, WAPE by bucket 1-3 / 4-6 / 7-12.** File `state_check/B4_metrics.csv`
(from `backtest/run_20261007T112751Z/metrics.parquet`).

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

**C1. Selection per series x bucket.** File `state_check/C1_selection.csv` (27 rows = 9 series x 3 buckets;
from `model_selection.json`). Columns: selected_models, weights (equal), best_model, fallback flag,
external_vars_used. Note: `model_selection.json` does **not store** which external variables a selected model
used -> recorded as "(not recorded)".

**C2. Corporate top-accounts path** (`stage4._top_accounts` and `report_extra.item7_top_accounts`): the
top-20 accounts are chosen **once on full history** (`groupby.sum().sort_values().head(20)`), i.e. **not**
re-selected per origin in the backtest nor in the final forecast. The residual (Corporate total minus the top
20) is forecast with **AutoETS** and **uses no external variable**.

**C3. Hierarchy reconciliation.** Bottom-up via `stage4._reconcile_forecasts`: Trade := sum(zones);
external := Corporate + Trade; company := external + Intercompany, applied to every quantile. For base
2026-10 (from `forecasts.parquet`): zones sum **=** Trade = 11,574.4 (diff 0.0000); Corporate+Trade **=**
external = 15,322.6 (diff -0.0000); external+Intercompany **=** company = 15,527.7 (diff 0.0000). MinT is
**not** implemented (reconciliation.json policy = bottom-up; MinT noted as optional).

**C4. Final forecast table.** File `state_check/C4_final_forecast.csv` (series x month 2026-10..2027-09 point
MT, total_12m_forecast, last12_actual, growth_pct). Totals/growth: Corporate 44,978.4 (**-1.83%**);
Intercompany 2,550.3 (+6.20%); Trade 138,194.6 (+7.32%); company 185,723.3 (+4.93%); external 183,173.0
(+4.92%); Dhaka 80,043.8 (+12.16%); North 22,020.9 (+4.19%); North East 13,837.0 (+11.31%); South 22,292.9
(-6.48%).

**C5. Final refit window.** Yes - the final models are refit on **all actuals through 2026-09**
(`fut_idx` starts 2026-10; `stage4._final_forecast` fits on the full series). The **holdout period
(2026-04..09) IS included** in the final refit (only excluded from selection/backtest).

## D. MODEL FIXES (from `forecasting/models/statistical.py`, `ml.py`)

**D1. Structural.** `UnobservedComponents(level="local level", seasonal=12)`, **no exog, no intervention**;
output clipped by `_clip` to [0, 3 x train max]. Number of clipping activations: **NOT VERIFIED** (no log
records activations).

**D2. SARIMAX.** Order **(1,1,1)**, seasonal **(0,1,1,12)**, enforce_stationarity/invertibility True; exog
whitelist `["eid_closure_days_total","working_days_6day","fy_end_flag","monsoon_flag","dry_season_flag","slump","disruption_days_full","flood_major_flag"]`, standardized on train. Clipping activations: **NOT VERIFIED**
(no log).

**D3. STL+ETS.** Bug: the future seasonal term was indexed `(len+i) % 12` instead of the calendar month of
the first observation. Fix: store `first_month_` and use `(future_month - first_month_) % 12`.

**D4. LightGBM.** Files `forecasting/models/ml.py`. Features: lags **[1,2,3,6,12]**, `roll3`, `roll6`,
`month`, `fyend`, plus any exog columns present. **Recursive** multi-step forecast (feeds each prediction back
as a lag). **Per-series** (one model per series), not pooled.

## E. EXTERNAL VARIABLES

**E1. Kept variables.** File `state_check/E1_external_tests.csv` (from `report_extra.json`). Keeps:
| series | feature | model tested | WAPE w/o | WAPE with | origins won |
|---|---|---|---|---|---|
| AIL\|channel\|Corporate | remittance_usd_mn_yoy | lightgbm | 0.3449 | 0.2737 | 11/15 |
| AIL\|zone\|Trade\|Dhaka | remittance_usd_mn | lightgbm | 0.4714 | 0.4510 | 11/15 |
| AIL\|zone\|Trade\|Dhaka | lc_open_raw_materials_usd_mn | lightgbm | 0.4714 | 0.4516 | 12/15 |
| AIL\|zone\|Trade\|North East | remittance_usd_mn | lightgbm | 0.5434 | 0.5115 | 11/15 |

**E2. Are kept variables used in a selected model?** **No (not recorded as used).** `model_selection.json`
has no `external_variables_used`; the selected base models for those series (from `forecasts.parquet` model
column) are non-exog or an exog model without the kept feature: Corporate `ma3,ma6,naive`; Trade|Dhaka
`ets,naive,ma3`; Trade|North East `ma3,ma6,structural`. So none of the 4 kept variables is wired into the
final ensemble.

**E3. Rainfall.** Yes - `data/outputs/forecast/external/ail_rainfall_monthly.csv` was generated by running
`Data/AIL/ail_external/fetch_rainfall.py` here (output written to the outputs folder to avoid modifying the
read-only external dir). Coverage **2023-01..2026-09 (45 months)**; columns = 8 divisions
(dhaka, chattogram, rajshahi, khulna, barishal, sylhet, rangpur, mymensingh), national mean,
1991-2020 normal, `rainfall_anomaly_pct`. Mapping of divisions to Trade zones: **NOT VERIFIED / not
implemented** (no division->zone code in `forecasting/external.py` or adapters).

## F. INTERVALS, SCENARIOS, SENSITIVITY, HOLDOUT

**F1. Conformal intervals.** Residuals used = **per series, pooled across all backtest origins within each
horizon bucket**, from the **best selected model** (stage4 `_conformal`). Coverage in `intervals.json` is
measured **on the same residuals used for calibration** (in-sample conformal) -> optimistic. Example
`AIL|company`: cov80/cov95 = short 0.762/0.905, medium 0.758/0.939, long 0.795/0.949. (The `method` string in
`intervals.json` is a stale placeholder; the offsets are stored numerically per series.)

**F2. Scenarios.** Computed by adding an **exog-capable model (SARIMAX) to the ensemble for scenario
runs** (`stage4._final_forecast`: if no selected model supports exog, append SARIMAX) and mutating the future
exog (`disruption_days_full = 5` in 2027-01/02; `flood_major_flag = 1` in 2027-05). File
`state_check/F2_scenarios.csv`. Examples: Corporate base 44,978.4 / disruption 47,172.2 (+4.88%) / flood
46,068.2 (+2.42%); Trade 138,194.6 / 146,084.3 (+5.71%) / 146,017.0 (+5.66%); Intercompany unchanged (0.00%).

**F3. Sensitivity (report_extra.json item3).** No series cut. (a) **Down-weight**: 2025 values replaced by
`0.5*actual + 0.5*seasonal_expectation`, where seasonal_expectation = mean of 2023-24 by calendar month.
(b) **Impute**: 2025 = `seasonal_norm(2023-24) x mean(2024 level)`. Trade 12m forecast: base 153,007.6 ->
down-weight 155,562.1 (**+1.7%**) -> impute 162,147.5 (**+6.0%**). (Note: the older `sensitivity_2025.json`
in stage4 is the superseded drop-2025 WAPE test.)

**F4. Holdout.** Setup = selected ensembles **refit at origin 2026-03**, evaluated on 2026-04..09 once
(`stage4._holdout`). Result `holdout.json`: origin 2026-03, **WAPE 0.222, n=54**. Per-series holdout WAPE and
holdout interval coverage: **NOT VERIFIED** (not stored). File `state_check/F4_holdout.csv`.

## G. CODE HEALTH AND REPRODUCIBILITY

**G1. Broken tokens / control characters.**
Cause: the two docs were appended with **PowerShell double-quoted here-strings** (`@"..."@`), where markdown
inline-code backticks were interpreted as PowerShell escapes: `` `a `` -> BEL (0x07), `` `f `` -> FF (0x0C),
`` `t `` -> TAB (0x09), `` `0 `` -> NUL (0x00), `` `r `` -> CR. Each escape consumed the following letter,
so e.g. `` `remittance `` became BEL + "emittance", `` `forecasting `` -> FF + "orecasting", `` `amazon `` ->
BEL + "mazon", `` `adp `` -> BEL + "dp", `` `test_holdout_guard `` -> TAB + "est_holdout_guard",
`` `01_model_report `` -> NUL + "1_model_report". The `write` tool and the Python-generated files are clean.
Tracked files genuinely affected (control chars or broken tokens):
- `docs/forecasting/01_model_report.md` - all listed tokens + control 0x7, 0x9, 0xC (BEL/TAB/FF).
- `docs/forecasting/README.md` - control 0x0 (NUL) before "1_model_report.md".
No `.py`, `.yaml`, `.json` file contains control characters (apparent matches there are substrings of correct
words such as "remittance", "forecasting", "amazon", "test_holdout_guard").

**G2. Determinism (full pipeline twice).** **NOT VERIFIED** - the full command
(`python -m forecasting.run_forecast`) currently **fails** (rc=1) at `forecasting/stage4.py::_select`
(`AttributeError: 'DataFrame' object has no attribute 'horizon_bucket'`) because stage4 reuses the *latest*
backtest metrics, which is the empty chronos-only run `backtest/run_20261007T120803Z`. Two runs were
attempted (172.0 s and 175.9 s wall, both rc=1). Per-stage times from the last successful stage4:
ingest ~15 s; stage4 (with reused metrics) output `run_20261007T120219Z`; the full aggregate backtest
`run_20261007T112751Z` took ETS 23.9s, SARIMAX 90.0s, structural 1.7s, LightGBM 8.0s, baselines ~0
(`backtest/run_20261007T112751Z/timings.json`).

**G3. Tests (12).** Files `forecasting/tests/`.
1. `test_adapter_schema` - adapter output has the standard columns, Period month, numeric y, no 1970 dates.
2. `test_hierarchy_sums` - child series sum to parents per month.
3. `test_no_duplicate_series_months` - no duplicate (series_id, month).
4. `test_monthly_totals_match_dq_layer` - channel monthly MT equals the DQ cleaned layer.
5. `test_external_leakage_guard` - leading vars usable only up to origin-lag; frozen (B6).
6. `test_registry_validation` - SBU and external registry entries have required keys.
7. `test_synthetic_cem_adapter_and_gate` - a synthetic CEM SBU (different layout) builds series and passes the gate.
8. `test_reduced_model_pool_for_18_months` - 24-month models excluded at 18 months of history.
9. `test_end_to_end_fixture` - synthetic SBU runs a small backtest end-to-end.
10. `test_holdout_guard_no_targets_after_cut` - no backtest target after 2026-03.
11. `test_forecast_reconciliation` - forecast children = parents per month/scenario/quantile.
12. `test_scenarios_differ_from_base` - at least one scenario differs from base.

**G4. Git.** `git status --short` = **clean** (nothing uncommitted). Branch `feature/demand-forecasting`,
7 commits (baseline + 6 feature). Tracked files = **81**; **no** `data/`, `*.xlsx`, `*.parquet`, weights or
`.venv` files tracked (gitignore enforces this).

## H. UI AND PLANNER

**H1. AIL Forecast page** (`frontend/src/app/ail-forecast/page.tsx`): PageHeader with title/label, run id and
generated-at, and a "download planner template" link; a filter card (series selector, scenario selector,
holdout WAPE); actuals-vs-forecast chart with the 80% band and a forecast reference line; accuracy table
(WAPE by bucket + selected models); external-variables-tested table; planner-adjustments table (when present);
collapsible "Corporate top accounts" table (account, last-12m actual, monthly point + band); caveats panel.
Series shown: the 9 aggregate series (accounts appear in the collapsible table only). Scenarios: base,
disruption, flood. Caveats: the 6 listed in `publish.py:CAVEATS`. Screenshots: **NOT VERIFIED** (no UI
screenshots were captured); diagnostic charts exist at `data/outputs/forecast/diagnostics/diag_{company,trade,dhaka}.png`.

**H2. Planner adjustments / FVA.** **No** adjustment has been ingested - `ui/planner_adjustments.json` =
`{adjustments: [], errors: [], note: "no upload present"}`. Forecast Value Added is **only planned**
(mentioned in `forecasting/planner.py` and `docs/forecasting/README.md`); **not computed** anywhere.

## I. ZERO-SHOT AND EXTERNAL CATALOG

**I1. Zero-shot status.** `torch` **installed** (2.14.1+cpu, CPU index) and `chronos` **installed**
(`chronos-forecasting`; `amazon/chronos-bolt-small` loads and forecasts in a clean process); `timesfm` and
`uni2ts`/Moirai **not installed**; Chronos-2 **NOT VERIFIED** (no such package present). Ran in the backtest:
**No** - Chronos-Bolt is reported `model_unavailable` (torch DLL `WinError 1114` conflict once
numpy/pandas load first). `TimesFM`/`Moirai` also skipped. Timing entry `chronos_bolt: 47.7s` reflects the
failed load attempts. File: `backtest/run_20261007T112751Z/{timings.json,notes.json}`, `data/outputs/forecast/zeroshot_results.json`.

**I2. Group catalog** (`Data/AIL/ail_external/anwar_group_external_variables.csv`, now present - 76 rows,
columns incl. var_id, feature_key, priority, phase, future_values, STEEL...). Validation vs
`forecasting/config/external_variables.yaml` (33 registry variables):
- **(a) feature_key match: only 3 of 33 registry keys exist in the catalog** - `ramadan_days` (CAL-03),
  `fy_end_flag` (CAL-05), `flood_event_flag` (WTH-02). **30 registry keys are mismatched** because the
  registry was authored from the *monthly-file column names*, not the catalog key names, e.g. registry
  `eid_fitr_closure_days` vs catalog `eid_fitr_days`; `working_days_6day/5day` vs `working_days`;
  `disruption_days_full/partial` vs `disruption_days`; `rainfall_anomaly_pct` vs `rainfall_anomaly`;
  `remittance_usd_mn` vs `remittance_inflow`; `usd_bdt_avg` vs `usd_bdt_rate`;
  `lc_open_raw_materials_usd_mn` vs `lc_open_raw_materials`; `cpi_inflation_p2p_pct` vs `cpi_inflation`;
  `rod_vat_tk_per_t` vs `rod_price_local`; `scrap_import_tax_tk_per_t` vs `scrap_price_import`;
  `adp_fy_revised_tk_cr/original` vs `adp_allocation_annual`; `election_month_flag/window_flag` vs
  `election_period_flag`. (Registry keys not in the catalog are listed in `state_check/I2_catalog.csv`.)
- **(b) catalog attributes for the 3 matched keys:** `ramadan_days` var_id CAL-03, Tier 2, Phase 1 (AIL),
  future_values "Known in advance"; `fy_end_flag` var_id CAL-05, Tier 1, Phase 1 (AIL), "Known in advance";
  `flood_event_flag` var_id WTH-02, Tier 2, Phase 1 (AIL), "Scenario only". (The other 30 registry keys have
  no var_id/priority/phase/future_values because their strings are not catalog keys.)
- **(c) Phase-1 (AIL) catalog variables NOT in the registry: 23** -
  eid_fitr_days, eid_adha_days, working_days, disruption_days, election_period_flag, intervention_<series>,
  rainfall_anomaly, adp_spend_monthly, adp_allocation_annual, mega_project_activity, rod_price_local,
  scrap_price_import, usd_bdt_rate, lc_open_raw_materials, remittance_inflow, private_credit_growth,
  cpi_inflation, harvest_season_flags, gas_supply_shortfall, load_shedding, duty_vat_changes,
  peer_sales_volumes, competitor_price_moves. File `state_check/I2_catalog_phase1_missing.csv`.

Files: `state_check/I2_catalog.csv`, `state_check/I2_catalog_phase1_missing.csv`.

## Tables produced (CSV)
`data/outputs/forecast/state_check/`:
`A1_series.csv`, `B4_metrics.csv`, `C1_selection.csv`, `C4_final_forecast.csv`, `E1_external_tests.csv`,
`F2_scenarios.csv`, `F4_holdout.csv`, `I2_catalog.csv`.
