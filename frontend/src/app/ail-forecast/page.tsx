"use client";
import { useEffect, useState, type CSSProperties } from "react";
import {
  ComposedChart, Bar, Line, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
  BarChart, Cell, LabelList, ReferenceLine, ReferenceDot,
} from "recharts";
import { apiGet, fmt } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { ErrorCard, PageSkeleton } from "@/components/States";

// ── Types ────────────────────────────────────────────────────────
type FPoint = { month: string; horizon: number; point: number; q025: number; q10: number; q50: number; q90: number; q975: number; value?: number };
type Act = { month: string; actual_mt: number; actual_value?: number; provisional: boolean; constrained: boolean };
type Selection = {
  selected_models: string[]; best_model: string; best_wape: number; reason: string; fallback_to_naive: boolean; weights?: number[];
};
type Detail = {
  series_id: string;
  price_per_mt?: number;
  actuals: Act[];
  forecasts: Record<string, FPoint[]>;
  selection: Record<string, Selection>;
  accuracy: Record<string, { wape: number } | null>;
  external_tested: { feature_key: string; decision: string; relative_change: Record<string, number> }[];
};
type LeaderboardEntry = {
  model: string; wape_short: number | null; wape_medium: number | null; wape_long: number | null;
  wape_all: number | null; bias_all: number | null; mase_all: number | null;
};
type PerSeriesHoldout = { wape: number; n: number; cov80: number; cov95: number };
type UIPayload = {
  generated_at: string; run_id: string; label: string; horizon_months: number;
  scenarios: string[]; caveats: string[];
  value_summary?: { currency: string; price_per_mt: number; forecast_value_12m: number; last12_value: number };
  holdout: {
    origin?: string; wape_all?: number; cov80_all?: number; cov95_all?: number;
    per_series?: Record<string, PerSeriesHoldout>; coverage?: Record<string, unknown>;
  };
  series: { series_id: string; level: string; channel: string; zone: string; label: string }[];
  detail: Record<string, Detail>;
  leaderboard?: LeaderboardEntry[];
  champion?: string | null;
  accounts_summary?: { bottom_up_wape_h1_6?: number; direct_wape_h1_6?: number; selected?: string };
  provisional?: Record<string, { pct_change?: number; flag_sensitive?: boolean }>;
  level_tracking_weight?: Record<string, number>;
  scenario_notes?: { series_id: string; feature: string; coef: number; ci95: number[]; verdict: string }[];
  sensitivity_selected?: Record<string, { downweight_pct?: number; impute_pct?: number }>;
};

// ── Constants / helpers ─────────────────────────────────────────
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const monthLabel = (m: string): string => `${MONTHS[+m.slice(5, 7) - 1]} '${m.slice(2, 4)}`;

const sumPoints = (arr: FPoint[]): number => arr.reduce((a, f) => a + f.point, 0);
const sumActuals = (arr: Act[]): number => arr.reduce((a, x) => a + x.actual_mt, 0);

// crore = 10,000,000 (1e7)
const crore = (v?: number | null): string => (v == null ? "—" : (v / 1e7).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 }));

// one row of the continuous past→forecast series
type TotalChartRow = {
  label: string;
  actual: number | null;
  fc: number | null;
  band: [number, number] | null;
  q10: number | null;
  q90: number | null;
};

// small inline 80%-coverage bar next to the % value
function Coverage({ cov }: { cov?: number | null }) {
  if (cov == null) return <span className="tabular-nums">—</span>;
  const v = Math.max(0, Math.min(100, cov * 100));
  return (
    <span className="inline-flex items-center justify-end gap-2">
      <span className="tabular-nums">{v.toFixed(0)}%</span>
      <span
        className="inline-block h-2 w-14 rounded-sm align-middle"
        style={{ background: "var(--surface-2)", border: "1px solid var(--grid)", overflow: "hidden" }}
        aria-hidden
      >
        <span style={{ display: "block", width: `${v}%`, height: "100%", background: "var(--good)" }} />
      </span>
    </span>
  );
}

function WapeBar({ value, max }: { value?: number | null; max: number }) {
  if (value == null || !isFinite(value)) return <span className="muted">—</span>;
  const w = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <span style={{ display: "flex", flexDirection: "column", gap: 3, alignItems: "flex-end", minWidth: 72 }}>
      <span style={{ width: "100%", height: 6, borderRadius: 3, background: "var(--surface-3)", overflow: "hidden" }}>
        <span style={{ display: "block", width: `${w}%`, height: 6, borderRadius: 3, background: wapeColor(value) }} />
      </span>
      <span className="tabular-nums" style={{ fontWeight: 600, color: "var(--ink)" }}>{(value * 100).toFixed(1)}%</span>
    </span>
  );
}

const SECTIONS = [
  { id: "summary", label: "Executive Summary" },
  { id: "demand", label: "Total Demand" },
  { id: "channel", label: "By Channel" },
  { id: "zone", label: "By Zone" },
  { id: "validation", label: "Model Performance" },
];

// categorical series palette (all design tokens — light/dark aware)
const CATS = [
  "var(--cat-1)", "var(--cat-2)", "var(--cat-3)", "var(--cat-4)", "var(--cat-5)", "var(--cat-6)",
  "var(--cat-7)", "var(--cat-8)", "var(--cat-9)", "var(--cat-10)", "var(--cat-11)", "var(--cat-12)",
];
const MODEL_COLORS: Record<string, string> = {
  "chronos_bolt": "var(--cat-3)", "naive": "var(--cat-1)", "seasonal_naive": "var(--cat-8)",
  "ma3": "var(--cat-2)", "ma6": "var(--cat-4)", "ets": "var(--cat-6)", "theta": "var(--cat-7)",
  "drift": "var(--cat-8)", "sarimax": "var(--cat-4)", "stl_ets": "var(--cat-2)",
  "structural": "var(--cat-9)", "lightgbm": "var(--cat-10)",
};
function mc(model: string, i: number) { return MODEL_COLORS[model] ?? CATS[i % CATS.length]; }

const pct = (n: number): string => `${n >= 0 ? "+" : ""}${n.toFixed(1)}%`;
const wapePct = (w: number | null | undefined): string => (w == null ? "—" : `${(w * 100).toFixed(1)}%`);
const biasPct = (b: number | null | undefined): string => (b == null ? "—" : `${b >= 0 ? "+" : ""}${(b * 100).toFixed(1)}%`);
const maseStr = (m: number | null | undefined): string => (m == null ? "—" : m.toFixed(2));
const wapeColor = (w: number | null | undefined): string =>
  w == null ? "var(--muted)" : w < 0.30 ? "var(--good)" : w < 0.40 ? "var(--ink)" : "var(--crit)";

// mix an accent token with the page background so unselected bars stay visible but clearly related
const tint = (token: string, pct: number) => `color-mix(in srgb, ${token} ${pct}%, var(--surface-1))`;

// last-12 actuals + 12 base-forecast points for a channel/zone drill-in
const drillRowsFor = (detail: Detail | undefined): Record<string, number | string | null>[] =>
  detail
    ? [
        ...detail.actuals.slice(-12).map((a) => ({ label: monthLabel(a.month), past: a.actual_mt, future: null, trend: null })),
        ...(detail.forecasts?.base ?? []).map((f) => ({ label: monthLabel(f.month), past: null, future: f.point, trend: f.point })),
      ]
    : [];

function DrillIn({ kind, name, share, annual, detail, accent, onClose }: {
  kind: string; name: string; share: number; annual: number; detail: Detail; accent: string; onClose: () => void;
}) {
  const drillFc = detail.forecasts?.base ?? [];
  const drillCombo = drillRowsFor(detail);
  return (
    <div className="grid gap-4 lg:grid-cols-2 mt-4">
      <div className="card">
        <div className="flex items-center justify-between mb-2">
          <div className="text-sm font-medium">{kind}: {name} — Monthly</div>
          <button className="chip text-xs" onClick={onClose}>close ✕</button>
        </div>
        <ResponsiveContainer width="100%" height={240}>
          <ComposedChart data={drillCombo} margin={{ left: 8, right: 8, top: 14, bottom: 18 }}>
            <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" />
            <XAxis dataKey="label" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }} minTickGap={18} interval="preserveStartEnd" />
            <YAxis stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }} tickFormatter={(v) => fmt(v)} width={48} />
            <Tooltip formatter={(v, n) => [`${fmt(v as number)} MT`, n === "past" ? "Actual" : n === "trend" ? "Trend" : "Forecast"]}
                     contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 10, fontSize: 12, boxShadow: "var(--shadow)" }} />
            <Legend verticalAlign="top" align="left" wrapperStyle={{ fontSize: 10 }} />
            <Bar dataKey="past" name="Actual" fill="var(--c-actual)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
            <Bar dataKey="future" name="Forecast" fill={accent} radius={[2, 2, 0, 0]} isAnimationActive={false} />
            <Line dataKey="trend" name="Trend" type="monotone" stroke="var(--ink-2)"
                  strokeWidth={2} dot={{ r: 3, fill: accent, strokeWidth: 2, stroke: "var(--surface-1)" }}
                  isAnimationActive={false} connectNulls={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="card">
        <div className="text-sm font-medium mb-2">{kind}: {name} — Forecast Table</div>
        <div className="overflow-x-auto max-h-64">
          <table className="tbl">
            <thead>
              <tr>
                <th style={{ position: "sticky", top: 0, background: "var(--surface-1)" }}>Month</th>
                <th className="num" style={{ position: "sticky", top: 0, background: "var(--surface-1)" }}>Forecast (MT)</th>
              </tr>
            </thead>
            <tbody>
              {drillFc.map((f) => (
                <tr key={f.month}>
                  <td className="font-medium">{monthLabel(f.month)}</td>
                  <td className="num">{fmt(f.point)}</td>
                </tr>
              ))}
              <tr style={{ borderTop: `2px solid ${accent}`, fontWeight: 600 }}>
                <td>Annual ({share.toFixed(1)}% share)</td>
                <td className="num" style={{ color: accent }}>{fmt(annual)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────
export default function AilForecast() {
  const [d, setD] = useState<UIPayload | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [active, setActive] = useState("summary");
  const [scenario, setScenario] = useState("base");
  const [selChannel, setSelChannel] = useState<string | null>(null);
  const [selZone, setSelZone] = useState<string | null>(null);

  useEffect(() => {
    apiGet<UIPayload>("/forecast/ui").then(setD).catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    const onScroll = () => {
      for (const s of [...SECTIONS].reverse()) {
        const el = document.getElementById(s.id);
        if (el && el.getBoundingClientRect().top < 240) { setActive(s.id); break; }
      }
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const scrollTo = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });

  if (err) return <ErrorCard error={err} />;
  if (!d) return <PageSkeleton />;

  // ── derived data ──────────────────────────────────────────────
  const company = d.series.find((s) => s.level === "company");
  const companyDetail = company ? d.detail[company.series_id] : undefined;
  const compFcBase = companyDetail?.forecasts?.base ?? [];
  const compFcScenario = companyDetail?.forecasts?.[scenario] ?? compFcBase;
  const compActuals = companyDetail?.actuals ?? [];
  const last12 = compActuals.slice(-12);
  const last12Sum = sumActuals(last12);
  const annualBase = sumPoints(compFcBase);
  const annualScenario = sumPoints(compFcScenario);
  const yoyPct = last12Sum > 0 ? ((annualBase - last12Sum) / last12Sum) * 100 : 0;
  const annualValueScenario = compFcScenario.reduce((a, f) => a + (f.value ?? 0), 0);
  const last12Value = last12.reduce((a, x) => a + (x.actual_value ?? 0), 0);

  const channelRows = d.series.filter((s) => s.level === "channel").map((s) => ({
    sid: s.series_id, name: s.channel, annual: sumPoints(d.detail[s.series_id]?.forecasts?.base ?? []),
    last12: sumActuals((d.detail[s.series_id]?.actuals ?? []).slice(-12)),
    detail: d.detail[s.series_id],
  }));
  const zoneRows = d.series.filter((s) => s.level === "zone").map((s) => ({
    sid: s.series_id, name: s.zone, annual: sumPoints(d.detail[s.series_id]?.forecasts?.base ?? []),
    last12: sumActuals((d.detail[s.series_id]?.actuals ?? []).slice(-12)),
    detail: d.detail[s.series_id],
  }));
  const channelTotal = channelRows.reduce((a, x) => a + x.annual, 0);
  const zoneTotal = zoneRows.reduce((a, x) => a + x.annual, 0);
  const channelBars = channelRows
    .map((r) => ({ ...r, share: channelTotal > 0 ? (r.annual / channelTotal) * 100 : 0 }))
    .sort((a, b) => b.annual - a.annual);
  const zoneBars = zoneRows
    .map((r) => ({ ...r, share: zoneTotal > 0 ? (r.annual / zoneTotal) * 100 : 0 }))
    .sort((a, b) => b.annual - a.annual);

  const topZone = zoneBars[0];
  const topChannel = channelBars[0];

  const champion = d.champion || companyDetail?.selection?.short?.best_model || "—";
  const wapeAll = d.holdout?.wape_all ?? null;
  const cov80All = d.holdout?.cov80_all ?? null;

  // ── continuous past→forecast series (one array, no break) ─────
  const totalChart: TotalChartRow[] = [
    ...compActuals.map((a) => ({
      label: monthLabel(a.month), actual: a.actual_mt, fc: null, band: null, q10: null, q90: null,
    })),
    ...compFcScenario.map((f) => {
      const hw = Math.max(f.point - f.q10, f.q90 - f.point);
      return {
        label: monthLabel(f.month), actual: null, fc: f.point,
        band: [f.point - hw, f.point + hw] as [number, number], q10: f.q10, q90: f.q90,
      };
    }),
  ];
  // anchor the forecast line to the last actual point so it is continuous
  if (compActuals.length > 0) {
    const anchorIdx = compActuals.length - 1;
    totalChart[anchorIdx] = { ...totalChart[anchorIdx], fc: compActuals[anchorIdx].actual_mt };
  }
  const boundaryLabel = compFcScenario[0] ? monthLabel(compFcScenario[0].month) : null;
  const lastAct = compActuals[compActuals.length - 1];
  const annualLo = compFcScenario.reduce((a, f) => a + f.q10, 0);
  const annualHi = compFcScenario.reduce((a, f) => a + f.q90, 0);
  const lastFcMonth = compFcBase[compFcBase.length - 1]?.month ?? "—";

  const leaderboard = d.leaderboard ?? [];
  const maxAll = Math.max(...leaderboard.map(r => r.wape_all ?? 0), 0.0001);

  const holdoutRows = [...d.series]
    .filter((s) => d.holdout?.per_series?.[s.series_id])
    .sort((a, b) => {
      const p: Record<string, number> = { company: 0, sbu: 1, channel: 2, zone: 3 };
      return (p[a.level] ?? 9) - (p[b.level] ?? 9) || a.label.localeCompare(b.label);
    });
  const maxH = Math.max(...holdoutRows.map(s => d.holdout?.per_series?.[s.series_id]?.wape ?? 0), wapeAll ?? 0, 0.0001);

  const selChannelRow = selChannel ? channelBars.find((r) => r.sid === selChannel) : null;
  const selZoneRow = selZone ? zoneBars.find((r) => r.sid === selZone) : null;

  type Kpi = { k: string; v: string; s: string; hi?: boolean; chip?: string; delta?: string; deltaColor?: string; accent: string };
  const kpis: Kpi[] = [
    { k: "12-Month Forecast", v: `${fmt(annualBase)} MT`, s: "MT steel", hi: true, chip: `${d.horizon_months}-mo horizon`, accent: "var(--acc-demand)" },
    { k: "Forecast Value", v: `৳ ${crore(d.value_summary?.forecast_value_12m)} cr`, s: `at ৳${fmt(d.value_summary?.price_per_mt)} / MT`, hi: true, accent: "var(--acc-demand)" },
    { k: "vs Last 12 Months", v: pct(yoyPct), s: `Last 12m: ${fmt(last12Sum)} MT`, delta: yoyPct >= 0 ? "▲" : "▼", deltaColor: yoyPct >= 0 ? "var(--good)" : "var(--crit)", accent: "var(--acc-demand)" },
    { k: "Model", v: champion, s: wapeAll != null ? `Holdout WAPE ${(wapeAll * 100).toFixed(1)}%` : "Holdout WAPE —", accent: "var(--acc-demand)" },
  ];

  return (
    <>
      <PageHeader
        title="Demand Forecast"
        subtitle="12-month statistical forecast for AIL steel (sales-based)."
      />

      {/* ── Nav — sticky scroll-spy tab bar ── */}
      <nav className="sticky top-[48px] z-[5] flex gap-1 overflow-x-auto rounded-xl p-1 mx-auto max-w-7xl px-4"
           aria-label="Page sections"
           style={{ background: "var(--surface-1)", border: "1px solid var(--grid)", boxShadow: "var(--shadow)" }}>
        {SECTIONS.map((s) => {
          const isActive = active === s.id;
          return (
            <button key={s.id} onClick={() => scrollTo(s.id)}
                    aria-label={s.label}
                    aria-current={isActive ? "location" : undefined}
                    data-active={isActive}
                    className="nav-tab text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
                    style={{ outlineColor: "var(--brand)" }}>
              {s.label}
            </button>
          );
        })}
      </nav>

      <div className="space-y-7">

      {/* ════════════════════════════════════════════════════════════
          SECTION: Executive Summary
          ════════════════════════════════════════════════════════════ */}
      <section id="summary" className="scroll-mt-32">
        <h2 className="section-h">
          <span className="section-bar" style={{ "--accent": "var(--acc-demand)" } as CSSProperties} />
          Executive Summary
        </h2>
        <p className="text-xs mb-4 mt-1 px-1" style={{ color: "var(--muted)" }}>
          Headline 12-month forecast, year-over-year movement, model champion and leading channel &amp; zone.
        </p>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {kpis.map((x) => (
            <div key={x.k} className="kpi" style={{ "--accent": x.accent } as CSSProperties}>
              <div className="flex items-start justify-between gap-2">
                <div className="kpi-label">{x.k}</div>
                {x.chip && <span className="chip">{x.chip}</span>}
              </div>
              <div className="kpi-value mt-1.5 flex items-center gap-1.5" style={{ color: "var(--ink)" }}>
                {x.v}
                {x.delta && (
                  <span className={x.deltaColor === "var(--good)" ? "badge badge-good" : "badge badge-crit"} aria-hidden>
                    {x.delta}
                  </span>
                )}
              </div>
              <div className="kpi-sub mt-1">{x.s}</div>
            </div>
          ))}
        </div>
        <p className="text-sm mt-4 px-1" style={{ color: "var(--ink-2)", lineHeight: 1.7 }}>
          The <b>{fmt(annualBase)} MT</b> 12-month forecast is a <b>{yoyPct >= 0 ? "increase" : "decrease"}</b> of {Math.abs(yoyPct).toFixed(1)}% over the trailing 12 months.
          <b> {topChannel?.name}</b> is the leading channel at {topChannel ? fmt(topChannel.annual) : "—"} MT and
          <b> {topZone?.name}</b> leads the zones at {topZone ? fmt(topZone.annual) : "—"} MT.
          The ranked ensemble is led by <b>{champion}</b> (holdout WAPE {wapeAll != null ? (wapeAll * 100).toFixed(1) : "—"}%
          {cov80All != null ? `, ${(cov80All * 100).toFixed(0)}% 80%-coverage` : ""}).
          Use the navigation bar above to jump to each section.
        </p>
      </section>

      {/* ════════════════════════════════════════════════════════════
          SECTION: Total Demand Forecast
          ════════════════════════════════════════════════════════════ */}
      <section id="demand" className="scroll-mt-32">
        <div className="flex flex-wrap items-start justify-between gap-3 mb-2">
          <div>
            <h2 className="section-h">
              <span className="section-bar" style={{ "--accent": "var(--acc-demand)" } as CSSProperties} />
              Total Demand Forecast
            </h2>
            <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>
              {compActuals.length} months of history plus the 12-month forecast as one continuous series with an 80% confidence band.
            </p>
            <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>
              Prices ≈ ৳{fmt(companyDetail?.price_per_mt)}/MT (trailing 12m).
            </p>
          </div>
          <div className="flex items-center gap-1.5" role="group" aria-label="Scenario">
            {(d.scenarios ?? []).map((sc) => (
              <button key={sc} onClick={() => setScenario(sc)}
                      aria-label={`Show ${sc} scenario`}
                      aria-pressed={scenario === sc}
                      className={`chip cursor-pointer capitalize focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${scenario === sc ? "chip-active" : ""}`}
                      style={{ outlineColor: "var(--brand)" }}>
                {sc}
              </button>
            ))}
          </div>
        </div>

        <div className="card mb-4">
          <div className="text-sm font-medium mb-2">Total Demand — {scenario}</div>
          <div className="mb-2 text-xs" style={{ color: "var(--muted)" }}>
            Annual total: {fmt(annualScenario)} MT · dashed line marks the start of the forecast.
          </div>
          <ResponsiveContainer width="100%" height={340}>
            <ComposedChart data={totalChart} margin={{ left: 8, right: 12, top: 14, bottom: 18 }}>
              <defs>
                <linearGradient id="bandGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--c-band)" stopOpacity={0.8} />
                  <stop offset="100%" stopColor="var(--c-band)" stopOpacity={0.2} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" />
              <XAxis dataKey="label" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }} minTickGap={22} interval="preserveStartEnd" />
              <YAxis stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 10 }} tickFormatter={(v) => fmt(v)} width={54} />
              <Tooltip
                formatter={(v, n) => {
                  const name = String(n ?? "");
                  if (Array.isArray(v)) return [`${fmt(v[0] as number)} – ${fmt(v[1] as number)} MT`, name];
                  return [`${fmt(v as number)} MT`, name];
                }}
                contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 10, fontSize: 12, boxShadow: "var(--shadow)" }}
              />
              <Legend verticalAlign="top" align="left" wrapperStyle={{ fontSize: 11, paddingBottom: 4 }} />
              {/* 80% band (range area over [q10, q90]) */}
              <Area dataKey="band" type="monotone" stroke="var(--c-band)" strokeWidth={1} fill="url(#bandGrad)"
                    connectNulls isAnimationActive={false} activeDot={false} name="80% range" />
              <Line dataKey="actual" name="Actual" stroke="var(--c-actual)" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line dataKey="fc" name="Forecast" stroke="var(--c-forecast)" strokeWidth={2.6}
                    dot={{ r: 3, fill: "var(--c-forecast)", stroke: "var(--surface-1)", strokeWidth: 2 }}
                    connectNulls isAnimationActive={false} />
              {boundaryLabel && (
                <ReferenceLine x={boundaryLabel} stroke="var(--axis)" strokeDasharray="4 4"
                               label={{ value: "Forecast ▸", position: "insideTopRight", fill: "var(--muted)", fontSize: 10 }} />
              )}
              {lastAct && (
                <ReferenceDot x={monthLabel(lastAct.month)} y={lastAct.actual_mt} r={4}
                              fill="var(--c-forecast)" stroke="var(--surface-1)" strokeWidth={2} />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <div className="card">
            <div className="text-sm font-medium mb-2">12-Month Forecast ({scenario})</div>
            <div className="overflow-auto max-h-80">
              <table className="tbl">
                <thead>
                  <tr>
                    <th style={{ position: "sticky", top: 0, background: "var(--surface-1)" }}>Month</th>
                    <th className="num" style={{ position: "sticky", top: 0, background: "var(--surface-1)" }}>Forecast (MT)</th>
                    <th className="num" style={{ position: "sticky", top: 0, background: "var(--surface-1)" }}>Value (৳ cr)</th>
                    <th className="num" style={{ position: "sticky", top: 0, background: "var(--surface-1)" }}>Lo 80</th>
                    <th className="num" style={{ position: "sticky", top: 0, background: "var(--surface-1)" }}>Hi 80</th>
                  </tr>
                </thead>
                <tbody>
                  {compFcScenario.map((f) => (
                    <tr key={f.month}>
                      <td className="font-medium" style={{ color: "var(--ink)" }}>{monthLabel(f.month)}</td>
                      <td className="num" style={{ color: "var(--c-forecast)" }}>{fmt(f.point)}</td>
                      <td className="num" style={{ color: "var(--c-forecast)" }}>{crore(f.value)}</td>
                      <td className="num" style={{ color: "var(--muted)" }}>{fmt(f.q10)}</td>
                      <td className="num" style={{ color: "var(--muted)" }}>{fmt(f.q90)}</td>
                    </tr>
                  ))}
                  <tr style={{ borderTop: "2px solid var(--c-forecast)", fontWeight: 600 }}>
                    <td>Annual Total</td>
                    <td className="num" style={{ color: "var(--c-forecast)" }}>{fmt(annualScenario)}</td>
                    <td className="num" style={{ color: "var(--c-forecast)" }}>{crore(annualValueScenario)}</td>
                    <td className="num" style={{ color: "var(--muted)" }}>{fmt(annualLo)}</td>
                    <td className="num" style={{ color: "var(--muted)" }}>{fmt(annualHi)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <div className="text-sm font-medium mb-2">Recent Actuals — Last 12 Months</div>
            <div className="overflow-auto max-h-80">
              <table className="tbl">
                <thead>
                  <tr>
                    <th style={{ position: "sticky", top: 0, background: "var(--surface-1)" }}>Month</th>
                    <th className="num" style={{ position: "sticky", top: 0, background: "var(--surface-1)" }}>Actual (MT)</th>
                    <th className="num" style={{ position: "sticky", top: 0, background: "var(--surface-1)" }}>Value (৳ cr)</th>
                  </tr>
                </thead>
                <tbody>
                  {last12.map((a) => (
                    <tr key={a.month}>
                      <td className="font-medium">{monthLabel(a.month)}</td>
                      <td className="num">{fmt(a.actual_mt)}</td>
                      <td className="num">{crore(a.actual_value)}</td>
                    </tr>
                  ))}
                  <tr style={{ borderTop: "2px solid var(--c-forecast)", fontWeight: 600 }}>
                    <td>Total</td>
                    <td className="num" style={{ color: "var(--ink)" }}>{fmt(last12Sum)}</td>
                    <td className="num" style={{ color: "var(--ink)" }}>{crore(last12Value)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </section>

      {/* ════════════════════════════════════════════════════════════
          SECTION: By Channel
          ════════════════════════════════════════════════════════════ */}
      <section id="channel" className="scroll-mt-32">
        <h2 className="section-h">
          <span className="section-bar" style={{ background: "var(--acc-region)" }} />
          By Channel
        </h2>
        <p className="text-xs mb-3" style={{ color: "var(--muted)" }}>
          {channelRows.length} channels totalling <b>{fmt(channelTotal)} MT</b>.
          Led by <b>{topChannel?.name}</b> at {topChannel ? fmt(topChannel.annual) : "—"} MT
          ({topChannel ? ((topChannel.annual / Math.max(channelTotal, 1)) * 100).toFixed(1) : "0.0"}% share).
          Click a bar to drill in.
        </p>

        <div className="card mb-4">
          <div className="text-sm font-medium mb-2">Annual Forecast by Channel</div>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={channelBars} layout="vertical" margin={{ left: 90, right: 14, top: 6, bottom: 8 }}>
              <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" horizontal={false} />
              <XAxis type="number" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }} tickFormatter={(v) => fmt(v)} />
              <YAxis type="category" dataKey="name" stroke="transparent" tick={{ fill: "var(--ink)", fontSize: 10 }} width={88} />
              <Tooltip formatter={(v, _n, item) => {
                const payload = item?.payload as { annual?: number; share?: number } | undefined;
                return [`${fmt(v as number)} MT (${payload?.share?.toFixed(1)}%)`, "Channel"];
              }} contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 10, fontSize: 12, boxShadow: "var(--shadow)" }} />
              <Bar dataKey="annual" radius={[0, 5, 5, 0]} barSize={20} isAnimationActive={false} cursor="pointer"
                   onClick={(entry) => setSelChannel(entry?.payload?.sid ?? null)}>
                <LabelList dataKey="share" position="right" formatter={(v: unknown) => (v != null && Number(v) > 0 ? `${Number(v).toFixed(1)}%` : "")}
                           fill="var(--ink-2)" fontSize={10} />
                {channelBars.map((s) => (
                  <Cell key={s.sid} fill={s.sid === selChannel ? "var(--acc-region)" : tint("var(--acc-region)", 55)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {selChannelRow && (
          <DrillIn kind="Channel" name={selChannelRow.name} share={selChannelRow.share} annual={selChannelRow.annual}
                   detail={selChannelRow.detail} accent="var(--acc-region)" onClose={() => setSelChannel(null)} />
        )}
      </section>

      {/* ════════════════════════════════════════════════════════════════
          SECTION: By Zone
          ════════════════════════════════════════════════════════════════ */}
      <section id="zone" className="scroll-mt-32">
        <h2 className="section-h">
          <span className="section-bar" style={{ background: "var(--acc-model)" }} />
          By Zone
        </h2>
        <p className="text-xs mb-3" style={{ color: "var(--muted)" }}>
          {zoneRows.length} Trade zones totalling <b>{fmt(zoneTotal)} MT</b>.
          Led by <b>{topZone?.name}</b> at {topZone ? fmt(topZone.annual) : "—"} MT
          ({topZone ? ((topZone.annual / Math.max(zoneTotal, 1)) * 100).toFixed(1) : "0.0"}% share).
          Click a bar to drill in.
        </p>

        <div className="card mb-4">
          <div className="text-sm font-medium mb-2">Annual Forecast by Zone</div>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={zoneBars} layout="vertical" margin={{ left: 90, right: 14, top: 6, bottom: 8 }}>
              <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" horizontal={false} />
              <XAxis type="number" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }} tickFormatter={(v) => fmt(v)} />
              <YAxis type="category" dataKey="name" stroke="transparent" tick={{ fill: "var(--ink)", fontSize: 10 }} width={88} />
              <Tooltip formatter={(v, _n, item) => {
                const payload = item?.payload as { annual?: number; share?: number } | undefined;
                return [`${fmt(v as number)} MT (${payload?.share?.toFixed(1)}%)`, "Zone"];
              }} contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 10, fontSize: 12, boxShadow: "var(--shadow)" }} />
              <Bar dataKey="annual" radius={[0, 5, 5, 0]} barSize={20} isAnimationActive={false} cursor="pointer"
                   onClick={(entry) => setSelZone(entry?.payload?.sid ?? null)}>
                <LabelList dataKey="share" position="right" formatter={(v: unknown) => (v != null && Number(v) > 0 ? `${Number(v).toFixed(1)}%` : "")}
                           fill="var(--ink-2)" fontSize={10} />
                {zoneBars.map((s) => (
                  <Cell key={s.sid} fill={s.sid === selZone ? "var(--acc-model)" : tint("var(--acc-model)", 55)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {selZoneRow && (
          <DrillIn kind="Zone" name={selZoneRow.name} share={selZoneRow.share} annual={selZoneRow.annual}
                   detail={selZoneRow.detail} accent="var(--acc-model)" onClose={() => setSelZone(null)} />
        )}
      </section>

      {/* ════════════════════════════════════════════════════════════
          SECTION: Model Performance
          ════════════════════════════════════════════════════════════ */}
      <section id="validation" className="scroll-mt-32">
        <h2 className="section-h">
          <span className="section-bar" style={{ "--accent": "var(--acc-model)" } as CSSProperties} />
          Model Performance
        </h2>
        <p className="text-xs mb-3" style={{ color: "var(--muted)" }}>
          Ranked by overall holdout WAPE across the {d.series.filter((s) => s.level === "zone" || s.level === "channel").length} aggregate series (models must cover all series to be ranked).
          Champion: <b>{champion}</b>.
        </p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          {[
            { k: "Champion", v: champion, s: "best overall WAPE" },
            { k: "Champion WAPE", v: wapePct(leaderboard[0]?.wape_all), s: "holdout (lower is better)" },
            { k: "80% Coverage", v: cov80All != null ? `${(cov80All * 100).toFixed(0)}%` : "—", s: "out-of-sample" },
            { k: "Models scored", v: String(leaderboard.length), s: "15 origins each" },
          ].map((x) => (
            <div key={x.k} className="kpi" style={{ "--accent": "var(--acc-model)" } as CSSProperties}>
              <div className="kpi-label">{x.k}</div>
              <div className="kpi-value">{x.v}</div>
              <div className="kpi-sub">{x.s}</div>
            </div>
          ))}
        </div>
        <div className="card">
          <div className="text-sm font-medium mb-2">Model Leaderboard — Holdout WAPE (lower is better)</div>
          <div className="max-h-[460px] overflow-auto">
            <table className="tbl">
              <thead>
                <tr style={{ position: "sticky", top: 0, background: "var(--surface-1)", zIndex: 1 }}>
                  <th>#</th>
                  <th>Model</th>
                  <th className="num">Short</th>
                  <th className="num">Medium</th>
                  <th className="num">Long</th>
                  <th className="num">Overall</th>
                  <th className="num">Bias</th>
                  <th className="num">MASE</th>
                </tr>
              </thead>
              <tbody>
                {leaderboard.map((r, idx) => {
                  const isChamp = r.model === champion;
                  return (
                    <tr key={r.model} style={isChamp ? { boxShadow: "inset 3px 0 0 var(--acc-model)", background: "color-mix(in srgb, var(--acc-model) 8%, transparent)" } : undefined}>
                      <td style={{ color: "var(--muted)" }}>{idx + 1}</td>
                      <td className="font-medium">
                        <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: mc(r.model, idx), marginRight: 5 }} />
                        {r.model}{isChamp && <span className="chip" style={{ marginLeft: 6 }}>champion</span>}
                      </td>
                      <td className="num" style={{ color: "var(--ink-2)" }}>{wapePct(r.wape_short)}</td>
                      <td className="num" style={{ color: "var(--ink-2)" }}>{wapePct(r.wape_medium)}</td>
                      <td className="num" style={{ color: "var(--ink-2)" }}>{wapePct(r.wape_long)}</td>
                      <td className="num"><WapeBar value={r.wape_all} max={maxAll} /></td>
                      <td className="num" style={{ color: r.bias_all != null && Math.abs(r.bias_all) >= 0.10 ? "var(--crit)" : "var(--ink-2)" }}>{biasPct(r.bias_all)}</td>
                      <td className="num">{maseStr(r.mase_all)}</td>
                    </tr>
                  );
                })}
                {leaderboard.length === 0 && (
                  <tr><td colSpan={8} className="py-3 text-center" style={{ color: "var(--muted)" }}>No leaderboard available.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
        <div className="card mt-4">
          <div className="text-sm font-medium mb-2">Holdout Accuracy by Series</div>
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Series</th>
                  <th className="num">Holdout WAPE</th>
                  <th className="num">80% Coverage</th>
                </tr>
              </thead>
              <tbody>
                {holdoutRows.map((s, i) => {
                  const h = d.holdout?.per_series?.[s.series_id];
                  return (
                    <tr key={s.series_id}>
                      <td style={{ color: "var(--muted)" }}>{i + 1}</td>
                      <td className="font-medium">{s.label}</td>
                      <td className="num"><WapeBar value={h?.wape} max={maxH} /></td>
                      <td className="num"><Coverage cov={h?.cov80} /></td>
                    </tr>
                  );
                })}
                <tr style={{ boxShadow: "inset 3px 0 0 var(--acc-model)", background: "var(--surface-2)", fontWeight: 600 }}>
                  <td style={{ color: "var(--muted)" }}>—</td>
                  <td>Overall</td>
                  <td className="num"><WapeBar value={wapeAll} max={maxH} /></td>
                  <td className="num"><Coverage cov={cov80All} /></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* ── Notes & Caveats ── */}
      <div className="card">
        <div className="text-sm font-medium mb-2">Notes &amp; Caveats</div>
        <ul className="text-xs space-y-1.5 list-disc pl-4" style={{ color: "var(--ink-2)", lineHeight: 1.6 }}>
          {(d.caveats ?? []).length > 0
            ? d.caveats.map((c, i) => <li key={i}>{c}</li>)
            : <>
                <li>Forecast horizon: {d.horizon_months} months ({lastFcMonth}).</li>
                <li>Holdout WAPE {wapeAll != null ? (wapeAll * 100).toFixed(1) : "—"}% and {cov80All != null ? (cov80All * 100).toFixed(0) : "—"}% 80%-coverage (out-of-sample validation).</li>
                <li>Figures are statistical and should be combined with commercial judgment.</li>
              </>}
        </ul>
      </div>

      {/* ── Footer ── */}
      <footer className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 mt-8 pt-4 px-1"
              style={{ borderTop: "1px solid var(--grid)", color: "var(--muted)", fontSize: 11 }}>
        <div>
          <div>Data as of {d.generated_at} · run {d.run_id ?? "—"} · source: AIL monthly sales</div>
          <div>AIL steel forecast</div>
        </div>
        <div>
          Demand Forecast — 12-month statistical forecast for AIL steel (sales-based).
        </div>
      </footer>

      </div>
    </>
  );
}
