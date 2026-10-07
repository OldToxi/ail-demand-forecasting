# Onboarding a new SBU

Adding an SBU requires **only a registry entry** (and, for a new file layout, a registry entry - the
generic `tabular` adapter already handles column renames, separator, sheet, header row). No model,
selection or UI code changes.

## Steps
1. **Add an entry to `config/sbus.yaml`** under `sbus:`:
   ```yaml
   - sbu_id: ACME
     name: Anwar Cement Ltd.
     segment_code: CEM              # pulls external variables tagged CEM from the catalog/registry
     min_history_months: 18
     top_accounts: {enabled: false} # switch on for lumpy project demand
     sources:
       - name: Cement
         adapter: tabular
         file: Data/AIL/acme_cement_monthly.csv     # repo-root relative (csv or xlsx)
         sheet: Data                                # ignored for csv
         header_row: 1
         key_style: name_plus_district              # or "name"
         column_map:
           date: TrxDate
           channel: Channel
           zone: Territory
           client: Buyer
           district: District
           quantity: Volume_MT
           value: Value
           opening: OpenBal
           collection: Receipt
           closing: CloseBal
   ```
2. Add the SBU to `hierarchy` if it is a new top-level company (or reuse the existing company roll-up).
3. If the segment code needs new external variables, add them to `config/external_variables.yaml`
   (the catalog `anwar_group_external_variables.csv` is the primary source of relevance by segment).
4. Run: `python -m forecasting.run_forecast --sbu ACME` (in the forecasting venv).
5. Review the DQ gate (`data/outputs/forecast/run_*/dq_gate.json`) and the selection output.

## What happens automatically
- **Same data checks**: adapters -> standard long frame -> DQ gate (duplicates, grain, null/zero,
  negatives, value-without-qty, date gaps, hierarchy sums, history length, external freshness).
- **Same model pool with minimum-history gating**:
  - >= 24 months: full pool (ETS, STL+ETS, Theta, SARIMAX, Structural, LightGBM, ...).
  - 12-23 months: two-seasonal-cycle models auto-disabled (their `min_history_months = 24`); baselines,
    seasonal naive (12) and non-seasonal models remain.
  - < 12 months: baselines + zero-shot only (low confidence).
- **Same external variables** by segment (calendar for all; STEEL/CEM specifics by `segments`).
- **Same selection** (top-3 per series x bucket, fallback to seasonal naive), reconciliation, scenarios.
- **UI**: the new SBU appears because artifacts carry an `sbu` column and the page filters from data.

## Removing a test SBU
Delete its registry entry and its run outputs under `data/outputs/forecast/`; no code to revert.
