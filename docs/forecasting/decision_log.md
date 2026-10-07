# Decision log - AIL demand forecasting
Business confirmation is not available yet. These are the working decisions the pipeline enforces,
each tied to the data-quality issue it addresses (see `Data/work/outputs/DATA_QUALITY_REPORT.md`, rev5).
Any change here must be recorded with a date and reason.

| # | Decision | Reason | DQ issue ID |
|---|----------|--------|-------------|
| 1 | **Target = monthly invoiced sales volume (MT) as a proxy for demand.** All outputs labelled "Demand forecast (based on sales)". | No order-book/product-shipment feed is available; invoiced sales is the closest consistent monthly demand signal. | WHAT WE ARE FORECASTING |
| 2 | **Drop exact duplicate rows; aggregate the remaining rows to party x month.** | Grain is not unique (carry-forward + activity rows); exact duplicates would double-count. | DQ-03 / DQ-05 |
| 3 | **Null and zero MT both mean "no sale" for aggregate volume** (sum treats null and zero as 0). The distinction is retained only as a flag. | The 2025 Trade regime records missing values as zero and other periods as null, so the two are not comparable across periods. | DQ-07 / DQ-30 |
| 4 | **Rows with a value but null/zero MT are excluded from MT** (kept for value analysis only). | These are financial ledger entries with no quantity. | DQ-14 / DQ-28 |
| 5 | **2026-09 is provisional; flagged in `actuals.provisional_flag`; results tested with and without it.** | Extracted in early Oct 2026; month-end closing entries may be missing. | DQ-09 |
| 6 | **2025 Trade MT is assumed real; a sensitivity run down-weights/excludes it.** | The 2025 null-vs-zero regime (DQ-30) and the volume break (DQ-31) could be reporting artefacts; tested in Stage 4, not assumed away. | DQ-30 / DQ-31 |
| 7 | **Use the rebuilt client key** (hyphen-safe; Trade = name + District). The approved case-only merge (ABIR/Abir) is applied. Merges marked "needs business review" are **not** applied. | The old canonicalisation merged distinct businesses. | DQ-20 / DQ-22 |
| 8 | **Intercompany is forecast separately as internal demand and excluded from the external-demand total.** | Counterparties are group companies (internal transfers). | DQ-23 |
| 9 | **Balances and credit features (OPB/CLB, collection) are not used as model inputs.** | Sign convention unconfirmed and 2025 CLB completeness regime; not needed at the recommended level. | DQ-12 / DQ-25 / DQ-29 |
| 10 | **Structural-break intervention (slump) is configurable per series** (default mid-2024..mid-2025 for Trade/Corporate/external). | The 2024-25 slump is a level shift, not seasonality. | DQ-31 |
| 11 | **Forecast at Channel / Channel x Zone; Corporate top-accounts layer only for the top-N accounts.** | Client series are sparse (intermittent). | DQ-10 / DQ-24 |

## Implementation notes (Stage 1)
- Volume rule (decision 3) is applied in `series.py` (`y.fillna(0)` before aggregation).
- Exact de-duplication (decision 2) is applied in `adapters/base.py` (`drop_duplicates`).
- Provisional flag (decision 5) is written to `actuals` from `config.yaml:provisional_months`.
- Constraint flag is set for months with `disruption_days_full > 0` or `flood_major_flag = 1`.
- The external catalog `anwar_group_external_variables.csv` is **not yet present**; the registry is
  authored in `config/external_variables.yaml` and will be validated against the catalog when supplied.
