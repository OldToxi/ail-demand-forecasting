"use client";
import { useEffect, useMemo, useState } from "react";
import {
  ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, ReferenceLine,
} from "recharts";
import { apiGet, fmt } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { ErrorCard, PageSkeleton } from "@/components/States";

type FPoint = { month: string; horizon: number; point: number; q025: number; q10: number; q50: number; q90: number; q975: number };
type Act = { month: string; actual_mt: number; provisional: boolean; constrained: boolean };
type Detail = {
  actuals: Act[];
  forecasts: Record<string, FPoint[]>;
  selection: Record<string, { selected_models: string[]; best_model: string; best_wape: number; reason: string; fallback_to_naive: boolean }>;
  accuracy: Record<string, { wape: number } | null>;
  external_tested: { feature_key: string; decision: string; relative_change: Record<string, number> }[];
};
type UIPayload = {
  generated_at: string; run_id: string; label: string; horizon_months: number;
  scenarios: string[]; caveats: string[];
  holdout: { wape_all?: number; origin?: string; targets?: string[] };
  series: { series_id: string; level: string; channel: string; zone: string; label: string }[];
  detail: Record<string, Detail>;
  accounts?: { account: string; series_id: string; last12: { month: string; actual_mt: number }[]; forecast: { month: string; point: number; q10: number; q90: number }[] }[];
  accounts_summary?: { bottom_up_12m_total?: number; direct_12m_total?: number; pct_difference?: number; selection?: string };
};

export default function AilForecast() {
  const [d, setD] = useState<UIPayload | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sid, setSid] = useState<string>("AIL|sbu|external");
  const [scenario, setScenario] = useState<string>("base");
  const [adjust, setAdjust] = useState<{ series_id: string; month: string; statistical_forecast_mt: number | null; adjusted_forecast_mt: number; reason: string; entered_by: string }[]>([]);
  const [showAcct, setShowAcct] = useState(false);

  useEffect(() => {
    apiGet<UIPayload>("/forecast/ui").then(setD).catch((e) => setErr(String(e)));
    apiGet<{ adjustments: typeof adjust }>("/forecast/planner").then((x) => setAdjust(x.adjustments || [])).catch(() => {});
  }, []);

  const detail = d?.detail?.[sid];
  const chart = useMemo(() => {
    if (!detail) return [];
    const rows: Record<string, number | string | null>[] = [];
    for (const a of detail.actuals) rows.push({ month: a.month, actual: a.actual_mt });
    const fc = detail.forecasts?.[scenario] || [];
    for (const f of fc) rows.push({ month: f.month, point: f.point, lo: f.q10, band: Math.max(f.q90 - f.q10, 0), q90: f.q90 });
    return rows;
  }, [detail, scenario]);
  const fstart = detail?.forecasts?.[scenario]?.[0]?.month;

  if (err) return <ErrorCard error={err} />;
  if (!d) return <PageSkeleton />;

  const sel = detail?.selection || {};

  return (
    <div className="space-y-5">
      <PageHeader
        title={`AIL demand forecast - ${d.label}`}
        subtitle={`12-month horizon (2026-10 to 2027-09) - run ${d.run_id} - generated ${d.generated_at.slice(0, 16)}`}
        right={<a className="chip" href="/api/forecast/template" style={{ borderColor: "var(--s1)", color: "var(--s1)" }}>download planner template</a>}
      />

      {/* filters */}
      <div className="card" style={{ borderColor: "var(--s3)" }}>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <label className="flex items-center gap-2 text-sm">
            <span style={{ color: "var(--muted)" }}>Series</span>
            <select value={sid} onChange={(e) => setSid(e.target.value)}
                    className="rounded border px-2 py-1 text-sm"
                    style={{ background: "var(--surface-1)", borderColor: "var(--grid)", color: "var(--ink)" }}>
              {d.series.map((s) => <option key={s.series_id} value={s.series_id}>{s.label}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <span style={{ color: "var(--muted)" }}>Scenario</span>
            <select value={scenario} onChange={(e) => setScenario(e.target.value)}
                    className="rounded border px-2 py-1 text-sm"
                    style={{ background: "var(--surface-1)", borderColor: "var(--grid)", color: "var(--ink)" }}>
              {d.scenarios.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <span className="text-xs" style={{ color: "var(--muted)" }}>
            holdout WAPE {d.holdout?.wape_all ?? "—"} (origin {d.holdout?.origin ?? "—"})
          </span>
        </div>
      </div>

      {/* chart */}
      <div className="card">
        <div className="text-sm font-medium mb-2">Actuals vs forecast ({scenario}) - MT</div>
        <ResponsiveContainer width="100%" height={340}>
          <ComposedChart data={chart} margin={{ left: 8, right: 12, top: 8, bottom: 4 }}>
            <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" />
            <XAxis dataKey="month" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }} minTickGap={18} tickFormatter={(m: string) => m.slice(2)} />
            <YAxis stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 10 }} width={54} tickFormatter={(v) => fmt(v)} />
            <Tooltip formatter={(v, n) => [fmt(v as number), String(n)]} contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 8, fontSize: 12 }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {fstart && <ReferenceLine x={fstart} stroke="var(--muted)" strokeDasharray="3 3" />}
            <Area dataKey="lo" stackId="band" stroke="none" fill="transparent" legendType="none" />
            <Area dataKey="band" name="80% band (q10-q90)" stackId="band" stroke="none" fill="color-mix(in srgb, var(--s1) 16%, transparent)" />
            <Line dataKey="actual" name="Actual" stroke="var(--ink-2)" strokeWidth={2} dot={false} connectNulls />
            <Line dataKey="point" name={`Forecast (${scenario})`} stroke="var(--s1)" strokeWidth={2} dot={false} connectNulls />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* accuracy + selection */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card">
          <div className="text-sm font-medium mb-2">Accuracy (WAPE by horizon bucket)</div>
          <table className="tbl w-full text-sm">
            <thead><tr><th>bucket</th><th className="text-right">WAPE</th><th>selected models</th></tr></thead>
            <tbody>
              {["short", "medium", "long"].map((b) => (
                <tr key={b}>
                  <td>{b} ({b === "short" ? "1-3" : b === "medium" ? "4-6" : "7-12"})</td>
                  <td className="text-right font-mono">{detail?.accuracy?.[b]?.wape ?? "—"}</td>
                  <td className="text-xs">{(sel[b]?.selected_models || []).join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs" style={{ color: "var(--muted)" }}>
            Fallback to seasonal naive: {["short", "medium", "long"].some((b) => sel[b]?.fallback_to_naive) ? "yes (some buckets)" : "no"}.
            Intervals widen with horizon; months 7-12 evidence is thin.
          </p>
        </div>
        <div className="card">
          <div className="text-sm font-medium mb-2">External variables tested (round 1)</div>
          <table className="tbl w-full text-xs">
            <thead><tr><th>feature</th><th>decision</th><th className="text-right">rel. change</th></tr></thead>
            <tbody>
              {(detail?.external_tested || []).map((t) => (
                <tr key={t.feature_key}>
                  <td>{t.feature_key}</td>
                  <td style={{ color: t.decision === "keep" ? "var(--good)" : "var(--muted)" }}>{t.decision}</td>
                  <td className="text-right">{Object.entries(t.relative_change || {}).map(([k, v]) => `${k}:${(v * 100).toFixed(1)}%`).join(" ")}</td>
                </tr>
              ))}
              {(!detail?.external_tested || detail.external_tested.length === 0) && <tr><td colSpan={3} style={{ color: "var(--muted)" }}>none for this series</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      {/* planner adjustments */}
      {adjust.filter((a) => a.series_id === sid).length > 0 && (
        <div className="card">
          <div className="text-sm font-medium mb-2">Planner adjustments (statistical vs adjusted)</div>
          <table className="tbl w-full text-xs">
            <thead><tr><th>month</th><th className="text-right">statistical</th><th className="text-right">adjusted</th><th>reason</th><th>by</th></tr></thead>
            <tbody>
              {adjust.filter((a) => a.series_id === sid).map((a) => (
                <tr key={a.month}>
                  <td>{a.month}</td><td className="text-right">{fmt(a.statistical_forecast_mt)}</td>
                  <td className="text-right font-semibold">{fmt(a.adjusted_forecast_mt)}</td>
                  <td>{a.reason}</td><td>{a.entered_by}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* corporate top accounts (collapsible) */}
      {d.accounts && d.accounts.length > 0 && (
        <div className="card">
          <button className="flex items-center gap-2 text-sm font-medium"
                  onClick={() => setShowAcct(!showAcct)}>
            <span style={{ transform: showAcct ? "rotate(90deg)" : "none", display: "inline-block" }}>▶</span>
            Corporate top accounts ({d.accounts.length})
            {d.accounts_summary && (
              <span className="chip" style={{ marginLeft: 8 }}>
                bottom-up vs direct: {d.accounts_summary.pct_difference}% · selected {d.accounts_summary.selection}
              </span>
            )}
          </button>
          {showAcct && (
            <div className="overflow-x-auto mt-3">
              <table className="tbl w-full text-xs">
                <thead>
                  <tr>
                    <th>account</th>
                    <th className="text-right">last 12m actual (MT)</th>
                    {d.accounts[0].forecast.map((f) => <th key={f.month} className="text-right">{f.month}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {d.accounts.map((a) => (
                    <tr key={a.series_id}>
                      <td>{a.account}</td>
                      <td className="text-right font-mono">{fmt(a.last12.reduce((s, x) => s + x.actual_mt, 0))}</td>
                      {a.forecast.map((f) => (
                        <td key={f.month} className="text-right font-mono">{fmt(f.point)}
                          <div className="text-[10px]" style={{ color: "var(--muted)" }}>{fmt(f.q10)}–{fmt(f.q90)}</div>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-xs" style={{ color: "var(--muted)" }}>
                Intermittent models (Croston-SBA / TSB / hurdle) per account; band is a residual estimate.
                Planner adjustments may target an account {`series_id`} via the template.
              </p>
            </div>
          )}
        </div>
      )}

      {/* caveats */}
      <div className="card" style={{ borderColor: "color-mix(in srgb, var(--crit) 30%, var(--grid))" }}>
        <div className="text-sm font-medium mb-1" style={{ color: "var(--crit)" }}>Caveats</div>
        <ul className="list-disc ml-5 text-xs" style={{ color: "var(--ink-2)" }}>
          {d.caveats.map((c) => <li key={c}>{c}</li>)}
        </ul>
      </div>
    </div>
  );
}
