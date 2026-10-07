"use client";
import { Fragment, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, ReferenceLine,
} from "recharts";
import { apiGet, fmt } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { ErrorCard, PageSkeleton } from "@/components/States";

type SeriesPt = { month: string; p10: number; p50: number; p90: number; p10_wc: number | null; p90_wc: number | null };
type HistPt = { month: string; actual: number };
type ByType = { cement_type: string; annual_p50: number };
type Material = {
  material: string; category: string; uom: string;
  annual_p10: number; annual_p50: number; annual_p90: number;
  annual_p10_wc: number | null; annual_p90_wc: number | null;
  series: SeriesPt[]; history: HistPt[]; by_type: ByType[];
};
type Plan = {
  unit: number; unit_name: string; months: string[];
  cement_demand_tons_p50: number | null; note: string; band_rho: number | null;
  stale: boolean | null; stale_reason: string; built_at: string | null; materials: Material[];
};

// ---- scenario: adjust demand, re-derive production (production = demand x recipe, so scaling demand
// scales the material plan identically). Growth = uniform level change; Seasonality = reshape the flat
// forecast using the material's own historical monthly profile. ----
function seasonalIndex(history: HistPt[]): Record<number, number> {
  if (history.length < 12) return {};
  const byMonth: Record<number, number[]> = {};
  for (const h of history) {
    const mm = Number(h.month.slice(5, 7));
    (byMonth[mm] ??= []).push(h.actual);
  }
  const overall = history.reduce((a, h) => a + h.actual, 0) / history.length;
  if (overall <= 0) return {};
  const idx: Record<number, number> = {};
  for (const mm of Object.keys(byMonth).map(Number)) {
    const arr = byMonth[mm];
    idx[mm] = arr.reduce((a, b) => a + b, 0) / arr.length / overall;
  }
  return idx;
}
function scenarioMult(month: string, idx: Record<number, number>, growthPct: number, seasonalOn: boolean): number {
  const g = 1 + growthPct / 100;
  const s = seasonalOn ? (idx[Number(month.slice(5, 7))] ?? 1) : 1;
  return g * s;
}
type UnitRow = { unit_id: number; name: string };

const CAT_LABEL: Record<string, string> = {
  clinker: "Clinker", raw_material: "Raw material", packaging: "Packaging",
};
const CAT_COLOR: Record<string, string> = {
  clinker: "var(--s1)", raw_material: "var(--s3)", packaging: "var(--muted)",
};
const cleanUnit = (u: string) =>
  u.replace(/ (Ltd\.?|Limited|Company Ltd\.?|Industries Ltd\.?|Mills Ltd\.?)$/i, "");

// build a procurement-ready CSV (month x material, Low/Expected/High + worst-case + annual) and download it.
// honors the active scenario (growth / seasonality) so the exported plan matches what's on screen.
function downloadPlanCsv(plan: Plan, growthPct: number, seasonalOn: boolean) {
  const scen = growthPct !== 0 || seasonalOn;
  const rows: (string | number)[][] = [[
    "month", "category", "material", "uom", "low", "expected", "high", "low_worstcase", "high_worstcase"]];
  const r0 = (n: number | null) => (n == null ? "" : Math.round(n));
  for (const m of plan.materials) {
    const idx = seasonalIndex(m.history);
    let aL = 0, aE = 0, aH = 0, aWl = 0, aWh = 0;
    for (const s of m.series) {
      const k = scenarioMult(s.month, idx, growthPct, seasonalOn);
      const lo = s.p10 * k, ex = s.p50 * k, hi = s.p90 * k;
      const wl = s.p10_wc == null ? null : s.p10_wc * k, wh = s.p90_wc == null ? null : s.p90_wc * k;
      rows.push([s.month, m.category, m.material, m.uom, r0(lo), r0(ex), r0(hi), r0(wl), r0(wh)]);
      aL += lo; aE += ex; aH += hi; aWl += wl ?? 0; aWh += wh ?? 0;
    }
    rows.push(["ANNUAL TOTAL", m.category, m.material, m.uom, r0(aL), r0(aE), r0(aH), r0(aWl), r0(aWh)]);
  }
  const csv = rows.map((r) => r.map((c) => (typeof c === "string" && c.includes(",") ? `"${c}"` : c)).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const tag = scen ? `_scenario_g${growthPct}${seasonalOn ? "_seasonal" : ""}` : "";
  a.download = `procurement_material_plan_unit${plan.unit}${tag}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function ProductionPlanning() {
  const [units, setUnits] = useState<UnitRow[]>([]);
  const [unit, setUnit] = useState<string>("");           // "" = no plant chosen yet (show the picker)
  const [plan, setPlan] = useState<Plan | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sel, setSel] = useState<string | null>(null);    // selected material for the chart
  const [expanded, setExpanded] = useState<string | null>(null);  // material whose monthly rows are open
  const [growthPct, setGrowthPct] = useState(0);          // scenario: uniform demand growth %
  const [seasonalOn, setSeasonalOn] = useState(false);    // scenario: apply historical seasonal shape
  const scenarioOn = growthPct !== 0 || seasonalOn;

  useEffect(() => {
    apiGet<{ units: UnitRow[] }>("/production/units")
      .then((d) => setUnits(d.units))
      .catch((e) => setErr(String(e)));
  }, []);
  useEffect(() => {
    if (!unit) { setPlan(null); return; }
    setPlan(null); setSel(null);
    apiGet<Plan>(`/production/materials?unit=${unit}`)
      .then((d) => { setPlan(d); setSel(d.materials[0]?.material ?? null); })
      .catch((e) => setErr(String(e)));
  }, [unit]);

  const selMat = useMemo(
    () => plan?.materials.find((m) => m.material === sel) ?? null, [plan, sel]);

  const selIdx = useMemo(() => (selMat ? seasonalIndex(selMat.history) : {}), [selMat]);

  // one continuous series: actual (past) then forecast band (future). Scenario re-derives the forecast
  // by scaling each month's demand-driven value (base stays as a dashed reference).
  const chartData = useMemo(() => {
    if (!selMat) return [] as Record<string, number | string | null>[];
    const hist = selMat.history.map((h) => ({
      month: h.month, actual: h.actual as number | null,
      p50: null as number | null, sc: null as number | null, lo: null as number | null, band: null as number | null,
    }));
    if (hist.length) { hist[hist.length - 1].p50 = hist[hist.length - 1].actual; hist[hist.length - 1].sc = hist[hist.length - 1].actual; }
    const fut = selMat.series.map((s) => {
      const m = scenarioMult(s.month, selIdx, growthPct, seasonalOn);
      return {
        month: s.month, actual: null as number | null,
        p50: s.p50, sc: s.p50 * m, lo: s.p10 * m, band: (s.p90 - s.p10) * m,
      };
    });
    return [...hist, ...fut];
  }, [selMat, selIdx, growthPct, seasonalOn]);
  const forecastStart = selMat?.series[0]?.month;

  // scenario annual per material (for KPI tiles + delta), = sum of scaled monthly p50
  const scenAnnual = (m: Material) => {
    const idx = seasonalIndex(m.history);
    return m.series.reduce((a, s) => a + s.p50 * scenarioMult(s.month, idx, growthPct, seasonalOn), 0);
  };

  if (err) return <ErrorCard error={err} />;

  const clinker = plan?.materials.find((m) => m.category === "clinker");
  const rmTotal = plan?.materials
    .filter((m) => m.category === "raw_material")
    .reduce((a, m) => a + m.annual_p50, 0) ?? 0;
  const bags = plan?.materials.find((m) => m.category === "packaging");

  return (
    <div className="space-y-5">
      <PageHeader
        title="Production Planning — materials"
        subtitle="What to produce and buy to meet the demand forecast: clinker + raw materials, exploded through the cement BOM."
        right={
          unit && plan ? (
            <>
              <button className="chip" onClick={() => { setUnit(""); setPlan(null); }}
                      title="Choose a different plant">↺ change plant</button>
              <button className="chip" onClick={() => downloadPlanCsv(plan, growthPct, seasonalOn)}
                      title="Download the 12-month material plan (month × material, Low/Expected/High) as CSV"
                      style={{ borderColor: "var(--s1)", color: "var(--s1)" }}>
                ⬇ Download CSV{scenarioOn ? " (scenario)" : " (procurement)"}
              </button>
            </>
          ) : undefined
        }
      />

      {/* STEP 1 — pick a plant (button) */}
      {!unit && (
        <div className="card">
          <div className="font-medium" style={{ borderLeft: "3px solid var(--s1)", paddingLeft: 8 }}>Select a plant</div>
          <div className="mb-3 text-xs" style={{ color: "var(--muted)" }}>
            Choose a production unit to see its material plan — past actuals and the next 12-month forecast.
          </div>
          {units.length === 0 ? (
            <PageSkeleton />
          ) : (
            <div className="flex flex-wrap gap-3">
              {units.map((u) => (
                <button
                  key={u.unit_id}
                  onClick={() => setUnit(String(u.unit_id))}
                  className="flex items-center gap-3 rounded-xl border px-5 py-4 text-left transition hover:-translate-y-0.5 hover:shadow-sm"
                  style={{ borderColor: "color-mix(in srgb, var(--s1) 35%, var(--grid))", background: "color-mix(in srgb, var(--s1) 6%, var(--surface-1))" }}
                >
                  <span className="flex h-11 w-11 items-center justify-center rounded-xl text-xl"
                        style={{ background: "color-mix(in srgb, var(--s1) 14%, transparent)" }}>🏭</span>
                  <span>
                    <span className="block font-semibold" style={{ color: "var(--ink)" }}>{cleanUnit(u.name)}</span>
                    <span className="block text-xs" style={{ color: "var(--muted)" }}>view material forecast →</span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* STEP 2 — the plan */}
      {unit && !plan && <PageSkeleton />}
      {unit && plan && (
        <>
          <div className="text-sm" style={{ color: "var(--muted)" }}>
            Plant: <b style={{ color: "var(--ink)" }}>{cleanUnit(plan.unit_name)}</b> · next {plan.months.length} months
          </div>

          {/* staleness guard — the demand->production coupling check */}
          {plan.stale && (
            <div className="card" style={{ borderColor: "var(--crit)", background: "color-mix(in srgb, var(--crit) 8%, var(--surface-1))" }}>
              <div className="font-medium" style={{ color: "var(--crit)" }}>⚠ Production plan may be out of date</div>
              <p className="mt-1 text-sm" style={{ color: "var(--ink-2)" }}>{plan.stale_reason}</p>
            </div>
          )}

          {/* derivation note */}
          <div className="card" style={{ background: "color-mix(in srgb, var(--s1) 5%, var(--surface-1))", borderColor: "color-mix(in srgb, var(--s1) 22%, var(--grid))" }}>
            <div className="text-sm" style={{ color: "var(--ink-2)" }}>
              <b>Derived, not separately forecast.</b> {plan.note}{" "}
              Based on the published demand for <b>{cleanUnit(plan.unit_name)}</b> over the next{" "}
              {plan.months.length} months (≈ <b>{fmt(plan.cement_demand_tons_p50 ?? 0)}</b> tons of cement).
            </div>
          </div>

          {/* scenario controls — inject a demand adjustment, production re-derives live */}
          <div className="card" style={{ borderColor: scenarioOn ? "var(--s3)" : "var(--grid)" }}>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
              <div className="font-medium" style={{ borderLeft: "3px solid var(--s3)", paddingLeft: 8 }}>
                Scenario — adjust demand
              </div>
              <label className="flex items-center gap-2 text-sm">
                <span style={{ color: "var(--muted)" }}>Demand growth</span>
                <input type="range" min={-30} max={50} step={1} value={growthPct}
                       onChange={(e) => setGrowthPct(Number(e.target.value))} />
                <b style={{ color: growthPct === 0 ? "var(--ink-2)" : "var(--s1)", minWidth: 44 }}>
                  {growthPct > 0 ? "+" : ""}{growthPct}%
                </b>
              </label>
              <label className="flex items-center gap-2 text-sm" style={{ cursor: "pointer" }}>
                <input type="checkbox" checked={seasonalOn} onChange={(e) => setSeasonalOn(e.target.checked)} />
                <span style={{ color: "var(--muted)" }}>Apply historical seasonality</span>
              </label>
              {scenarioOn && (
                <button className="chip" onClick={() => { setGrowthPct(0); setSeasonalOn(false); }}>reset to base</button>
              )}
              <span className="text-xs" style={{ color: "var(--muted)" }}>
                {scenarioOn
                  ? "Scenario active — production is re-derived from the adjusted demand (dashed = base)."
                  : "Move the slider or tick seasonality to see production re-derive from a changed demand."}
              </span>
            </div>
          </div>

          {/* KPI tiles (scenario-aware) */}
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            {[
              { k: "Cement demand", base: plan.cement_demand_tons_p50 ?? 0, scen: (plan.cement_demand_tons_p50 ?? 0) * (1 + growthPct / 100), u: "Ton" },
              { k: "Clinker required", base: clinker?.annual_p50 ?? 0, scen: clinker ? scenAnnual(clinker) : 0, u: "Ton", hi: true },
              { k: "Other raw materials", base: rmTotal, scen: plan.materials.filter((m) => m.category === "raw_material").reduce((a, m) => a + scenAnnual(m), 0), u: "Ton" },
              { k: "Empty cement bags", base: bags?.annual_p50 ?? 0, scen: bags ? scenAnnual(bags) : 0, u: "Bag" },
            ].map((t) => {
              const val = scenarioOn ? t.scen : t.base;
              const dPct = t.base ? (t.scen - t.base) / t.base * 100 : 0;
              return (
                <div key={t.k} className="card">
                  <div className="text-sm" style={{ color: "var(--muted)" }}>{t.k}</div>
                  <div className="text-2xl font-semibold" style={{ color: t.hi ? "var(--s1)" : "var(--ink)" }}>{fmt(val)}</div>
                  <div className="text-xs" style={{ color: "var(--muted)" }}>
                    {t.u} · next 12 months
                    {scenarioOn && Math.abs(dPct) >= 0.5 && (
                      <b style={{ color: dPct >= 0 ? "var(--good)" : "var(--crit)", marginLeft: 6 }}>
                        {dPct >= 0 ? "▲" : "▼"} {Math.abs(dPct).toFixed(0)}% vs base
                      </b>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            {/* item-wise material table — ANNUAL totals */}
            <div className="card overflow-x-auto">
              <div className="flex flex-wrap items-center gap-2">
                <div className="font-medium" style={{ borderLeft: "3px solid var(--s1)", paddingLeft: 8 }}>
                  Material requirement — item-wise
                </div>
                <span className="chip" style={{ borderColor: "var(--s1)", color: "var(--s1)" }}>ANNUAL · next 12 months</span>
              </div>
              <div className="mb-3 mt-1 text-xs" style={{ color: "var(--muted)" }}>
                <b>Annual totals</b> (whole 12-month horizon){scenarioOn ? ", scenario-adjusted" : ""}. <b>Click a row</b> to
                expand its <b>month-by-month</b> Low/Expected/High and chart it. Annual Expected = the monthly Expected summed over 12 months.
              </div>
              <table className="tbl w-full text-sm">
                <thead><tr>
                  <th>material</th>
                  <th className="text-right">Low<span style={{ color: "var(--muted)", fontWeight: 400 }}> /yr</span></th>
                  <th className="text-right">Expected<span style={{ color: "var(--muted)", fontWeight: 400 }}> /yr</span></th>
                  <th className="text-right">High<span style={{ color: "var(--muted)", fontWeight: 400 }}> /yr</span></th>
                  <th>UoM</th>
                </tr></thead>
                <tbody>
                  {plan.materials.map((m) => {
                    const ex = scenarioOn ? scenAnnual(m) : m.annual_p50;
                    const f = scenarioOn && m.annual_p50 ? ex / m.annual_p50 : 1;   // scale band with scenario
                    const open = expanded === m.material;
                    const idx = seasonalIndex(m.history);
                    return (
                    <Fragment key={m.material}>
                    <tr onClick={() => { setSel(m.material); setExpanded(open ? null : m.material); }}
                        style={{ cursor: "pointer", background: sel === m.material ? "var(--surface-2)" : undefined }}>
                      <td>
                        <span style={{ display: "inline-block", width: 12, color: "var(--muted)" }}>{open ? "▾" : "▸"}</span>
                        <span className="chip" style={{ marginRight: 6, borderColor: CAT_COLOR[m.category], color: CAT_COLOR[m.category] }}>
                          {CAT_LABEL[m.category] ?? m.category}
                        </span>
                        <b>{m.material}</b>
                      </td>
                      <td className="text-right" style={{ color: "var(--muted)" }}>{fmt(m.annual_p10 * f)}</td>
                      <td className="text-right font-semibold">{fmt(ex)}</td>
                      <td className="text-right" style={{ color: "var(--muted)" }}>{fmt(m.annual_p90 * f)}</td>
                      <td>{m.uom}</td>
                    </tr>
                    {open && (
                      <tr>
                        <td colSpan={5} style={{ padding: 0, background: "var(--surface-2)" }}>
                          <div style={{ padding: "6px 10px" }}>
                            <div className="mb-1 text-xs" style={{ color: "var(--muted)" }}>
                              Monthly forecast — {m.material} ({m.uom}){scenarioOn ? " · scenario-adjusted" : ""}
                            </div>
                            <table className="tbl w-full text-xs">
                              <thead><tr>
                                <th>month</th><th className="text-right">Low</th>
                                <th className="text-right">Expected</th><th className="text-right">High</th>
                              </tr></thead>
                              <tbody>
                                {m.series.map((s) => {
                                  const k = scenarioMult(s.month, idx, growthPct, seasonalOn);
                                  return (
                                    <tr key={s.month}>
                                      <td>{s.month}</td>
                                      <td className="text-right" style={{ color: "var(--muted)" }}>{fmt(s.p10 * k)}</td>
                                      <td className="text-right font-semibold">{fmt(s.p50 * k)}</td>
                                      <td className="text-right" style={{ color: "var(--muted)" }}>{fmt(s.p90 * k)}</td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        </td>
                      </tr>
                    )}
                    </Fragment>
                    );
                  })}
                </tbody>
              </table>
              <p className="mt-2 text-xs" style={{ color: "var(--muted)" }}>
                Clinker is called out separately — it is the make-vs-buy driver. Ratios embed process wastage
                (BOM sums to ~1.03 t input per 1 t cement). <b>Low–High</b> is diversification-aware (the
                inventory √-law) and <b>asymmetric</b> — downside and upside are pooled separately, so the
                limited downside doesn&apos;t get dragged to 0 by these lumpy items&apos; large upside. A wider
                all-move-together worst-case band is in the CSV.
              </p>
            </div>

            {/* past + future chart for the selected material — MONTHLY */}
            <div className="card">
              <div className="flex flex-wrap items-center gap-2">
                <div className="font-medium" style={{ borderLeft: "3px solid var(--s3)", paddingLeft: 8 }}>
                  {selMat ? `${selMat.material} — past & forecast` : "Past & forecast"}
                </div>
                <span className="chip" style={{ borderColor: "var(--s3)", color: "var(--s3)" }}>MONTHLY</span>
                {selMat && (
                  <span className="text-xs" style={{ color: "var(--muted)" }}>
                    annual total <b style={{ color: "var(--ink-2)" }}>{fmt(scenarioOn ? scenAnnual(selMat) : selMat.annual_p50)} {selMat.uom}</b> (= sum of the line)
                  </span>
                )}
              </div>
              <div className="mb-3 mt-1 text-xs" style={{ color: "var(--muted)" }}>
                Actual requirement (past, derived from sales × BOM) flowing into the Expected forecast with its
                Low–High band. {selMat ? `In ${selMat.uom}.` : ""}
              </div>
              {selMat && (
                <ResponsiveContainer width="100%" height={300}>
                  <ComposedChart data={chartData} margin={{ left: 8, right: 12, top: 6, bottom: 4 }}>
                    <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" />
                    <XAxis dataKey="month" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 10 }}
                           tickFormatter={(m: string) => m.slice(2)} minTickGap={16} />
                    <YAxis stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 10 }}
                           tickFormatter={(v) => fmt(v)} width={54} />
                    <Tooltip formatter={(v, n) => {
                      const label = n === "actual" ? "Actual (past)"
                        : n === "sc" ? (scenarioOn ? "Scenario" : "Expected")
                        : n === "p50" ? "Base" : n === "band" ? "band width" : n;
                      return [fmt(v as number), label];
                    }}
                             contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 8, fontSize: 12 }} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    {forecastStart && (
                      <ReferenceLine x={forecastStart} stroke="var(--muted)" strokeDasharray="3 3"
                                     label={{ value: "forecast", position: "insideTopRight", fill: "var(--muted)", fontSize: 9 }} />
                    )}
                    {/* band: transparent base at (scaled) p10, then (p90-p10) filled -> spans [p10, p90] */}
                    <Area dataKey="lo" stackId="band" stroke="none" fill="transparent" isAnimationActive={false} connectNulls legendType="none" />
                    <Area dataKey="band" name="Low–High band" stackId="band" stroke="none" fill="color-mix(in srgb, var(--s1) 16%, transparent)" isAnimationActive={false} connectNulls legendType="rect" />
                    <Line dataKey="actual" name="Actual (past)" stroke="var(--ink-2)" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
                    {scenarioOn && (
                      <Line dataKey="p50" name="Base (no scenario)" stroke="var(--muted)" strokeWidth={1.5} strokeDasharray="4 3" dot={false} isAnimationActive={false} connectNulls />
                    )}
                    <Line dataKey="sc" name={scenarioOn ? "Scenario (forecast)" : "Expected (forecast)"} stroke="var(--s1)" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
                  </ComposedChart>
                </ResponsiveContainer>
              )}
              {selMat && selMat.by_type.length > 0 && (
                <div className="mt-2 text-xs" style={{ color: "var(--muted)" }}>
                  Forecast driven by:{" "}
                  {selMat.by_type.map((t, i) => (
                    <span key={t.cement_type}>
                      {i > 0 && " · "}<b style={{ color: "var(--ink-2)" }}>{t.cement_type}</b> {fmt(t.annual_p50)} {selMat.uom}
                    </span>
                  ))}
                </div>
              )}
              <p className="mt-2 text-xs" style={{ color: "var(--muted)" }}>
                <b>Reading it:</b> this chart is <b>per month</b>; the table is the <b>annual total</b>. The Expected
                reconciles — the 12 monthly Expected values sum to the annual figure. The <b>band does not sum</b>:
                the annual Low–High is pooled across all months (diversification), so it is tighter than stacking
                the monthly bands — don&apos;t add the monthly Lows/Highs.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap gap-3 text-sm">
            <Link href="/demand-planning" className="chip">← demand planning</Link>
            <Link href="/demand-forecast-planning" className="chip">demand forecast →</Link>
          </div>

          <p className="text-xs" style={{ color: "var(--muted)" }}>
            Scope: cement pilot (ACCL). The past line is the actual material requirement derived from cement
            sales × BOM (the reliable anchor; the raw production file is under reconciliation). Clinker shown as
            a requirement; a clinker→raw-meal (kiln) recipe and plant-capacity limits are the next extensions.
          </p>
        </>
      )}
    </div>
  );
}
