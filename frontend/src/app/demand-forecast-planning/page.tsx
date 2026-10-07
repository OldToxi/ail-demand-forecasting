"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  ComposedChart, Bar, Line, LineChart, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
  BarChart, Cell, LabelList,
} from "recharts";
import { apiGet, fmt } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { ErrorCard, PageSkeleton } from "@/components/States";
import { PlantPicker, ChangePlantChip } from "@/components/PlantGate";

// ── Types ────────────────────────────────────────────────────────
type FcRow = { month: string; label: string; forecast_mt: number; lo80: number; hi80: number };
type HistRow = { month: string; label: string; actual_mt: number; fitted_mt?: number };
type MatRow = { month: string; label: string; mt: number };
type Material = { material: string; ratio_kg_per_ton: number; annual_mt: number; future: MatRow[]; past: MatRow[] };
type DistRow = { month: string; label: string; mt: number };
type District = { district: string; rank: number; annual_mt: number; share_pct: number; future: DistRow[]; past: DistRow[] };
type SupplyMonth = { month: string; label: string; trucks: number; peak_day_trucks: number; daily: { date: string; day: string; mt: number; trucks: number }[] };

type FcV2 = {
  meta: { model: string; model_wape: number; model_bias: number };
  executive_summary: { annual_forecast_mt: number; last_12m_actual_mt: number; yoy_change_pct: number; top_district: string; top_material: string; annual_truckloads: number; model_name: string; model_wape_pct: number };
  national: { annual_forecast_mt: number; last_12m_actual_mt: number; model: string; model_order: string; model_wape: number; model_bias: number; last_data_month: string; n_months: number; forecast: FcRow[]; history: HistRow[] };
  materials: { materials: Material[]; type_mix: Record<string, number> };
  districts: { top_districts: District[]; other_districts_annual_mt: number; total_districts_mapped: number; method: string };
  supply_chain: { truck_mt: number; annual_loads: number; avg_day_loads: number; peak_day_loads: number; monthly: SupplyMonth[] };
  seasonality: Record<string, number>;
  yearly_context: { years: number[]; market_mmt: number[]; accl_mmt: number[]; share_pct: number[] };
};

// ── Bakeoff types ─────────────────────────────────────────────────
type LBEntry = {
  model: string; wape_o1: number | null; wape_o2: number | null; wape_avg: number | null;
  bias_o1: number | null; bias_o2: number | null; bias_avg: number | null;
  mase_o1: number | null; mase_o2: number | null; mase_avg: number | null; bias_pass: boolean;
};
type OriginDetail = {
  model: string; wape: number; bias: number; mase: number;
  forecast: number[]; actual: number[]; naive_forecast: number[]; error?: string;
};
type Bakeoff = {
  champion: string; champion_wape: number; champion_bias: number;
  leaderboard: LBEntry[];
  origin1_details: OriginDetail[];
  origin2_details: OriginDetail[];
  backtest_origins: { train_through: string; test_window: string }[];
};

const MODEL_COLORS: Record<string, string> = {
  "AutoARIMA": "#2E7D32", "Holt-Winters": "#1565C0", "Seasonal Naive": "#6D4C41",
  "AutoETS": "#E65100", "Theta": "#8E24AA", "Current (damped trend)": "#C62828",
};
const FALLBACKS = ["#2E7D32", "#1565C0", "#6D4C41", "#E65100", "#8E24AA", "#C62828"];
function mc(model: string, i: number) { return MODEL_COLORS[model] ?? FALLBACKS[i % FALLBACKS.length]; }

const MAT_COLOR: Record<string, string> = { Clinker: "#e8833a", Gypsum: "#a0aec0", Limestone: "#68a678", Slag: "#7c6f64" };

const SECTIONS = [
  { id: "summary", label: "Executive Summary", color: "#4f8fc9" },
  { id: "demand", label: "Total Demand", color: "#4f8fc9" },
  { id: "materials", label: "Raw Materials", color: "#5a9e6f" },
  { id: "districts", label: "By District", color: "#c98f4f" },
  { id: "supply", label: "Supply Chain", color: "#9e5a6f" },
  { id: "validation", label: "Model Performance", color: "#2E7D32" },
];

const barLbl = (v: unknown): string => {
  if (v == null || typeof v === "boolean") return "";
  const n = typeof v === "number" ? v : Number(v);
  if (!isFinite(n) || n === 0) return "";
  const a = Math.abs(n);
  if (a >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return `${Math.round(n)}`;
};

// ── Page ─────────────────────────────────────────────────────────
export default function DemandForecastV2() {
  const [entered, setEntered] = useState(false);
  const [d, setD] = useState<FcV2 | null>(null);
  const [bake, setBake] = useState<Bakeoff | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [active, setActive] = useState("summary");
  const [selMat, setSelMat] = useState("Clinker");
  const [selDist, setSelDist] = useState<string | null>(null);
  const [openSupply, setOpenSupply] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  function loadData() {
    setRefreshing(true);
    setErr(null);
    Promise.all([
      apiGet<FcV2>("/demand-planning/demand-forecast-v2"),
      apiGet<Bakeoff>("/demand-planning/bakeoff"),
    ]).then(([fc, bk]) => { setD(fc); setBake(bk); setRefreshing(false); })
      .catch((e) => { setErr(String(e)); setRefreshing(false); });
  }

  useEffect(() => { loadData(); }, []);

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
  if (!entered) {
    return (
      <div className="space-y-5">
        <PageHeader title="Demand Forecast" subtitle="12-month statistical forecast for ACCL cement operations." />
        <PlantPicker subtitle="AutoARIMA forecast → materials → districts → supply chain. All derived from a single forecast pass."
                     onEnter={() => setEntered(true)} />
      </div>
    );
  }
  if (!d) return <PageSkeleton />;

  const { national, materials, districts, supply_chain: sc, executive_summary: ex } = d;
  const fitData = national.history.slice(-36);
  const fc12 = national.forecast;
  const annualMmt = national.annual_forecast_mt / 1e6;

  // ── Bakeoff chart builders ────────────────────────────────────
  const MONTHS_O1 = ["Jun", "Jul", "Aug", "Sep", "Oct", "Nov"];
  const MONTHS_O2 = ["Dec", "Jan", "Feb", "Mar", "Apr", "May"];

  function backtestChart(origin: OriginDetail[], months: string[]) {
    const actual = origin.find((o) => o.model === bake!.champion)?.actual ?? [];
    const rows: Record<string, number | string>[] = [];
    for (let i = 0; i < months.length; i++) {
      const row: Record<string, number | string> = { month: months[i] };
      row["Actual"] = actual[i] ?? 0;
      for (const o of origin) {
        if (o.error) continue;
        row[o.model] = o.forecast[i] ?? 0;
      }
      rows.push(row);
    }
    return rows;
  }

  const topModels = bake ? bake.leaderboard.filter((l) => l.wape_avg != null).slice(0, 3).map((l) => l.model) : [];

  return (
    <>
      <PageHeader
        title="Demand Forecast"
        subtitle="12-month statistical forecast for ACCL cement operations."
        right={
          <div className="flex items-center gap-3">
            <button onClick={loadData} disabled={refreshing} className="chip text-xs"
                    style={{ display: "flex", alignItems: "center", gap: 4, opacity: refreshing ? 0.5 : 1 }}>
              {refreshing ? "⟳ Refreshing..." : "⟳ Refresh"}
            </button>
            <ChangePlantChip onExit={() => setEntered(false)} />
          </div>
        }
      />

      {/* ── Nav — full-width tab bar, sticks below main menu ── */}
      <nav className="sticky top-[48px] z-[5] grid grid-cols-6 rounded-xl p-1 mx-auto max-w-7xl px-4"
           style={{ background: "var(--surface-1)", border: "1px solid var(--grid)", boxShadow: "0 2px 12px rgba(0,0,0,0.06)" }}>
        {SECTIONS.map((s) => {
          const isActive = active === s.id;
          return (
            <button key={s.id} onClick={() => scrollTo(s.id)}
                    className="py-2.5 px-1.5 rounded-lg text-center transition-all duration-200"
                    style={{
                      background: isActive ? `color-mix(in srgb, ${s.color} 12%, var(--surface-1))` : "transparent",
                      borderBottom: isActive ? `2.5px solid ${s.color}` : "2.5px solid transparent",
                      color: isActive ? s.color : "var(--muted)",
                    }}>
              <span className="text-sm font-semibold">{s.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="space-y-6">

      {/* ════════════════════════════════════════════════════════════
          SECTION: Executive Summary
          ════════════════════════════════════════════════════════════ */}
      <section id="summary" className="scroll-mt-32">
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <span className="w-1 h-5 rounded-full inline-block" style={{ background: "var(--s1)" }} />
          Executive Summary
        </h2>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {[
            { k: "12-Month Forecast", v: `${annualMmt.toFixed(2)}M`, s: "MT cement", hi: true },
            { k: "vs Last 12 Months", v: `${ex.yoy_change_pct >= 0 ? "+" : ""}${ex.yoy_change_pct}%`, s: `Last 12m: ${(ex.last_12m_actual_mt / 1e6).toFixed(2)}M` },
            { k: "Model", v: ex.model_name, s: `WAPE ${ex.model_wape_pct}% · near-zero bias` },
            { k: "Annual Trucks", v: `${(ex.annual_truckloads / 1000).toFixed(0)}k`, s: `${sc.avg_day_loads ? fmt(sc.avg_day_loads) : "—"} avg/day` },
          ].map((x) => (
            <div key={x.k} className="card" style={{ borderColor: "var(--grid)" }}>
              <div className="text-xs font-medium uppercase tracking-wider" style={{ color: "var(--muted)" }}>{x.k}</div>
              <div className="text-2xl font-bold mt-1.5" style={{ color: x.hi ? "var(--s1)" : "var(--ink)" }}>{x.v}</div>
              <div className="text-xs mt-1" style={{ color: "var(--muted-2)" }}>{x.s}</div>
            </div>
          ))}
        </div>
        <p className="text-sm mt-4 px-1" style={{ color: "var(--ink-2)", lineHeight: 1.7 }}>
          The <b>{annualMmt.toFixed(2)}M MT</b> forecast is a {ex.yoy_change_pct >= 0 ? "slight increase" : "decrease"} over the trailing 12 months.
          <b> {districts.top_districts[0]?.district}</b> leads at {districts.top_districts[0]?.annual_mt ? fmt(districts.top_districts[0].annual_mt) : "—"} MT,
          <b> {materials.materials[0]?.material}</b> is the largest raw material at {materials.materials[0]?.annual_mt ? fmt(materials.materials[0].annual_mt) : "—"} MT required.
          {bake && <> Model validated via 2-origin backtest against 5 alternatives — <b>{bake.champion}</b> champion at WAPE {(bake.champion_wape * 100).toFixed(1)}%.</>}
          Use the navigation bar above to jump to each section.
        </p>
      </section>

      {/* ════════════════════════════════════════════════════════════
          SECTION: Total Demand Forecast
          ════════════════════════════════════════════════════════════ */}
      <section id="demand" className="scroll-mt-32">
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <span className="w-1 h-5 rounded-full inline-block" style={{ background: "#4f8fc9" }} />
          Total Demand Forecast
        </h2>
        <div className="grid gap-4 lg:grid-cols-2">
          {/* chart: forecast bars + curve */}
          <div className="card" style={{ borderColor: "var(--grid)" }}>
            <div className="text-sm font-medium mb-2">12-Month Forecast</div>
            <div className="mb-2 text-xs" style={{ color: "var(--muted)" }}>Annual total: {fmt(national.annual_forecast_mt)} MT</div>
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={fc12} margin={{ left: 8, right: 8, top: 14, bottom: 18 }}>
                <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" />
                <XAxis dataKey="label" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 10 }} />
                <YAxis stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 10 }} tickFormatter={(v) => fmt(v)} width={54} />
                <Tooltip formatter={(v, n) => [`${fmt(v as number)} MT`, n === "forecast_line" ? "Trend" : "Forecast"]}
                         contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 8, fontSize: 12 }} />
                <Legend wrapperStyle={{ fontSize: 10 }} />
                <Bar dataKey="forecast_mt" name="Forecast" fill="#4f8fc9" radius={[4, 4, 0, 0]} isAnimationActive={false}>
                  <LabelList dataKey="forecast_mt" position="top" formatter={(v: unknown) => v != null && Number(v) > 0 ? barLbl(v) : ""}
                             fill="var(--ink)" fontSize={9} fontWeight={600} />
                </Bar>
                <Line dataKey="forecast_mt" name="Trend" type="monotone" stroke="#1a3a5c"
                      strokeWidth={2.5} dot={{ r: 4, fill: "#1a3a5c", strokeWidth: 2, stroke: "#fff" }}
                      isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          {/* chart: historical fit */}
          <div className="card" style={{ borderColor: "var(--grid)" }}>
            <div className="text-sm font-medium mb-2">Historical Fit — Last 36 Months</div>
            <div className="mb-2 text-xs" style={{ color: "var(--muted)" }}>Actual bars + AutoARIMA fitted line</div>
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={fitData} margin={{ left: 8, right: 8, top: 14, bottom: 4 }}>
                <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" />
                <XAxis dataKey="label" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }} minTickGap={30} interval="preserveStartEnd" />
                <YAxis stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }} tickFormatter={(v) => fmt(v)} width={54} />
                <Tooltip formatter={(v, n) => [`${fmt(v as number)} MT`, n === "fitted_mt" ? "Fitted" : "Actual"]}
                         contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 8, fontSize: 12 }} />
                <Legend wrapperStyle={{ fontSize: 10 }} />
                <Bar dataKey="actual_mt" name="Actual" fill="#bccfde" radius={[2, 2, 0, 0]} isAnimationActive={false} />
                <Line dataKey="fitted_mt" name="Fitted" stroke="#4f8fc9" strokeWidth={2.5} dot={{ r: 1.5 }} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
        {/* table */}
        <div className="card mt-4" style={{ borderColor: "var(--grid)" }}>
          <div className="text-sm font-medium mb-2">Monthly Forecast — Table</div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm" style={{ borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "2px solid var(--grid)" }}>
                  <th className="text-left py-2 px-3" style={{ color: "var(--muted)" }}>Month</th>
                  <th className="text-right py-2 px-3" style={{ color: "var(--muted)" }}>Forecast (MT)</th>
                  <th className="text-right py-2 px-3" style={{ color: "var(--muted)" }}>Lo 80 (MT)</th>
                  <th className="text-right py-2 px-3" style={{ color: "var(--muted)" }}>Hi 80 (MT)</th>
                </tr>
              </thead>
              <tbody>
                {fc12.map((f, i) => (
                  <tr key={f.month} style={{ borderBottom: "1px solid var(--grid)", background: i % 2 === 0 ? "var(--surface-2)" : "transparent" }}>
                    <td className="py-2 px-3 font-medium">{f.label}</td>
                    <td className="text-right py-2 px-3 font-mono">{fmt(f.forecast_mt)}</td>
                    <td className="text-right py-2 px-3 font-mono" style={{ color: "var(--muted)" }}>{fmt(f.lo80)}</td>
                    <td className="text-right py-2 px-3 font-mono" style={{ color: "var(--muted)" }}>{fmt(f.hi80)}</td>
                  </tr>
                ))}
                <tr style={{ borderTop: "2px solid #4f8fc9", fontWeight: 600 }}>
                  <td className="py-2 px-3">Annual Total</td>
                  <td className="text-right py-2 px-3 font-mono" style={{ color: "#4f8fc9" }}>{fmt(national.annual_forecast_mt)}</td>
                  <td colSpan={2} className="text-right py-2 px-3" style={{ color: "var(--muted)" }}>{(national.annual_forecast_mt / 12).toFixed(0)} MT/month avg</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* ════════════════════════════════════════════════════════════
          SECTION: Raw Material Forecast
          ════════════════════════════════════════════════════════════ */}
      <section id="materials" className="scroll-mt-32">
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <span className="w-1 h-5 rounded-full inline-block" style={{ background: "#5a9e6f" }} />
          Raw Material Forecast
        </h2>
        <p className="text-xs mb-3" style={{ color: "var(--muted)" }}>
          Forecast × ACCL cement recipe. Click a card to drill in.
          CEM-II {(materials.type_mix["CEM-II"] * 100).toFixed(0)}% · OPC {(materials.type_mix["OPC"] * 100).toFixed(0)}% · PCC {(materials.type_mix["PCC"] * 100).toFixed(0)}%.
        </p>

        {/* material picker */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 mb-4">
          {materials.materials.map((m) => {
            const sel = m.material === selMat;
            return (
              <button key={m.material} onClick={() => setSelMat(m.material)}
                      className="card text-left cursor-pointer transition-all duration-150"
                      style={{ borderColor: sel ? MAT_COLOR[m.material] : "var(--grid)",
                               background: sel ? `color-mix(in srgb, ${MAT_COLOR[m.material]} 8%, var(--surface-1))` : "var(--surface-1)" }}>
                <div className="text-sm font-medium">{m.material}</div>
                <div className="text-xl font-bold mt-1.5" style={{ color: sel ? MAT_COLOR[m.material] : "var(--ink)" }}>
                  {fmt(m.annual_mt)}
                </div>
                <div className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>MT/yr · {m.ratio_kg_per_ton} kg/t</div>
              </button>
            );
          })}
        </div>

        {/* selected material */}
        {(() => {
          const mat = materials.materials.find((m) => m.material === selMat);
          if (!mat) return null;
          const past12 = mat.past.slice(-12);
          const combo: { label: string; past?: number; future?: number; trend?: number }[] = [
            ...past12.map((p) => ({ label: p.label, past: p.mt, future: undefined as (number | undefined), trend: undefined as (number | undefined) })),
            ...mat.future.map((f) => ({
              label: f.label, past: undefined as (number | undefined), future: f.mt,
              trend: f.mt, // trend line only on future
            })),
          ];

          return (
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="card" style={{ borderColor: "var(--grid)" }}>
                <div className="text-sm font-medium mb-2">{selMat} — Monthly Past & Forecast</div>
                <ResponsiveContainer width="100%" height={260}>
                  <ComposedChart data={combo} margin={{ left: 8, right: 8, top: 14, bottom: 18 }}>
                    <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" />
                    <XAxis dataKey="label" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }} minTickGap={18} interval="preserveStartEnd" />
                    <YAxis stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }} tickFormatter={(v) => fmt(v)} width={48} />
                    <Tooltip formatter={(v, n) => [`${fmt(v as number)} MT`, n === "past" ? "Actual" : n === "trend" ? "Trend" : "Forecast"]}
                             contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 8, fontSize: 12 }} />
                    <Legend wrapperStyle={{ fontSize: 10 }} />
                    <Bar dataKey="past" name="Actual" fill={`${MAT_COLOR[selMat]}60`} radius={[2, 2, 0, 0]} isAnimationActive={false} />
                    <Bar dataKey="future" name="Forecast" fill={MAT_COLOR[selMat]} radius={[2, 2, 0, 0]} isAnimationActive={false} />
                    <Line dataKey="trend" name="Trend" type="monotone" stroke="#333"
                          strokeWidth={2} dot={{ r: 3, fill: MAT_COLOR[selMat], strokeWidth: 2, stroke: "#fff" }}
                          isAnimationActive={false} connectNulls={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
              <div className="card" style={{ borderColor: "var(--grid)" }}>
                <div className="text-sm font-medium mb-2">{selMat} — Table</div>
                <div className="overflow-x-auto max-h-64">
                  <table className="w-full text-sm" style={{ borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "2px solid var(--grid)" }}>
                        <th className="text-left py-2 px-3" style={{ color: "var(--muted)" }}>Month</th>
                        <th className="text-right py-2 px-3" style={{ color: "var(--muted)" }}>Actual (MT)</th>
                        <th className="text-right py-2 px-3" style={{ color: "var(--muted)" }}>Forecast (MT)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {mat.past.slice(-6).map((p) => (
                        <tr key={p.month} style={{ borderBottom: "1px solid var(--grid)" }}>
                          <td className="py-2 px-3">{p.label}</td>
                          <td className="text-right py-2 px-3 font-mono">{fmt(p.mt)}</td>
                          <td className="text-right py-2 px-3" style={{ color: "var(--muted)" }}>—</td>
                        </tr>
                      ))}
                      {mat.future.map((f) => (
                        <tr key={f.month} style={{ borderBottom: "1px solid var(--grid)", background: "var(--surface-2)" }}>
                          <td className="py-2 px-3 font-medium">{f.label}</td>
                          <td className="text-right py-2 px-3" style={{ color: "var(--muted)" }}>—</td>
                          <td className="text-right py-2 px-3 font-mono" style={{ color: MAT_COLOR[selMat] }}>{fmt(f.mt)}</td>
                        </tr>
                      ))}
                      <tr style={{ borderTop: "2px solid var(--grid)", fontWeight: 600 }}>
                        <td className="py-2 px-3">Annual</td>
                        <td className="text-right py-2 px-3 font-mono" style={{ color: "var(--muted)" }}>{fmt(mat.past.reduce((a, x) => a + x.mt, 0))}</td>
                        <td className="text-right py-2 px-3 font-mono" style={{ color: MAT_COLOR[selMat] }}>{fmt(mat.annual_mt)}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          );
        })()}
      </section>

      {/* ════════════════════════════════════════════════════════════
          SECTION: District Forecast
          ════════════════════════════════════════════════════════════ */}
      <section id="districts" className="scroll-mt-32">
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <span className="w-1 h-5 rounded-full inline-block" style={{ background: "#c98f4f" }} />
          District-wise Forecast
        </h2>
        <p className="text-xs mb-3" style={{ color: "var(--muted)" }}>
          Top {districts.top_districts.length} of {districts.total_districts_mapped} districts. Click a bar to drill in.
        </p>

        <div className="card mb-4" style={{ borderColor: "var(--grid)" }}>
          <div className="text-sm font-medium mb-2">Annual Forecast by District</div>
          <ResponsiveContainer width="100%" height={340}>
            <BarChart data={[...districts.top_districts].sort((a, b) => b.annual_mt - a.annual_mt)}
                      layout="vertical" margin={{ left: 80, right: 12, top: 6, bottom: 8 }}>
              <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" horizontal={false} />
              <XAxis type="number" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }} tickFormatter={(v) => fmt(v)} />
              <YAxis type="category" dataKey="district" stroke="transparent" tick={{ fill: "var(--ink)", fontSize: 10 }} width={78} />
              <Tooltip formatter={(v) => [`${fmt(v as number)} MT`, "Annual"]}
                       contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 8, fontSize: 12 }} />
              <Bar dataKey="annual_mt" radius={[0, 3, 3, 0]} isAnimationActive={false} cursor="pointer"
                   onClick={(entry) => { const dd = entry as unknown as { district?: string; payload?: { district?: string } }; setSelDist(dd?.district ?? dd?.payload?.district ?? null); }}>
                {districts.top_districts.map((dd) => (
                  <Cell key={dd.district} fill={dd.district === selDist ? "#c98f4f" : "#d9c5a8"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {selDist && (() => {
          const dist = districts.top_districts.find((dd) => dd.district === selDist);
          if (!dist) return null;
          const combo: { label: string; past?: number; future?: number; trend?: number }[] = [
            ...dist.past.slice(-12).map((p) => ({ label: p.label, past: p.mt, future: undefined as (number | undefined), trend: undefined as (number | undefined) })),
            ...dist.future.map((f) => ({
              label: f.label, past: undefined as (number | undefined), future: f.mt,
              trend: f.mt,
            })),
          ];
          return (
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="card" style={{ borderColor: "var(--grid)" }}>
                <div className="flex items-center justify-between mb-2">
                  <div className="text-sm font-medium">{dist.district} — Monthly</div>
                  <button className="chip text-xs" onClick={() => setSelDist(null)}>close ✕</button>
                </div>
                <ResponsiveContainer width="100%" height={240}>
                  <ComposedChart data={combo} margin={{ left: 8, right: 8, top: 14, bottom: 18 }}>
                    <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" />
                    <XAxis dataKey="label" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }} minTickGap={18} interval="preserveStartEnd" />
                    <YAxis stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }} tickFormatter={(v) => fmt(v)} width={48} />
                    <Tooltip formatter={(v, n) => [`${fmt(v as number)} MT`, n === "past" ? "Actual" : n === "trend" ? "Trend" : "Forecast"]}
                             contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 8, fontSize: 12 }} />
                    <Legend wrapperStyle={{ fontSize: 10 }} />
                    <Bar dataKey="past" name="Actual" fill="#e0cfba" radius={[2, 2, 0, 0]} isAnimationActive={false} />
                    <Bar dataKey="future" name="Forecast" fill="#c98f4f" radius={[2, 2, 0, 0]} isAnimationActive={false} />
                    <Line dataKey="trend" name="Trend" type="monotone" stroke="#5c3d1a"
                          strokeWidth={2} dot={{ r: 3, fill: "#c98f4f", strokeWidth: 2, stroke: "#fff" }}
                          isAnimationActive={false} connectNulls={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
              <div className="card" style={{ borderColor: "var(--grid)" }}>
                <div className="text-sm font-medium mb-2">{dist.district} — Forecast Table</div>
                <div className="overflow-x-auto max-h-64">
                  <table className="w-full text-sm" style={{ borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "2px solid var(--grid)" }}>
                        <th className="text-left py-2 px-3" style={{ color: "var(--muted)" }}>Month</th>
                        <th className="text-right py-2 px-3" style={{ color: "var(--muted)" }}>Forecast (MT)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dist.future.map((f, i) => (
                        <tr key={f.month} style={{ borderBottom: "1px solid var(--grid)", background: i % 2 === 0 ? "var(--surface-2)" : "transparent" }}>
                          <td className="py-2 px-3 font-medium">{f.label}</td>
                          <td className="text-right py-2 px-3 font-mono">{fmt(f.mt)}</td>
                        </tr>
                      ))}
                      <tr style={{ borderTop: "2px solid #c98f4f", fontWeight: 600 }}>
                        <td className="py-2 px-3">Annual ({dist.share_pct}% share)</td>
                        <td className="text-right py-2 px-3 font-mono" style={{ color: "#c98f4f" }}>{fmt(dist.annual_mt)}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          );
        })()}
      </section>

      {/* ════════════════════════════════════════════════════════════
          SECTION: Supply Chain
          ════════════════════════════════════════════════════════════ */}
      <section id="supply" className="scroll-mt-32">
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <span className="w-1 h-5 rounded-full inline-block" style={{ background: "#9e5a6f" }} />
          Supply Chain — Day-wise Dispatch
        </h2>
        <div className="grid grid-cols-3 gap-4 mb-4">
          {[
            { k: "Annual Truckloads", v: fmt(sc.annual_loads), hi: true },
            { k: "Avg Trucks / Day", v: fmt(sc.avg_day_loads) },
            { k: "Peak Day (fleet sizing)", v: fmt(sc.peak_day_loads) },
          ].map((x) => (
            <div key={x.k} className="card" style={{ borderColor: "var(--grid)" }}>
              <div className="text-xs" style={{ color: "var(--muted)" }}>{x.k}</div>
              <div className="text-xl font-bold mt-1" style={{ color: x.hi ? "#9e5a6f" : "var(--ink)" }}>{x.v}</div>
            </div>
          ))}
        </div>

        <div className="card mb-4" style={{ borderColor: "var(--grid)" }}>
          <div className="text-sm font-medium mb-2">Monthly Truckloads — Click a bar for day-wise detail</div>
          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={sc.monthly} margin={{ left: 8, right: 8, top: 12, bottom: 18 }}>
              <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" />
              <XAxis dataKey="label" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 10 }} />
              <YAxis stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 10 }} width={44} />
              <Tooltip formatter={(v, n) => [`${fmt(v as number)} loads`, n === "trend" ? "Trend" : "Truckloads"]}
                       contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 8, fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Bar dataKey="trucks" name="Truckloads" radius={[4, 4, 0, 0]} isAnimationActive={false} cursor="pointer"
                   onClick={(entry) => { const m = entry as unknown as { month?: string; payload?: { month?: string } }; setOpenSupply(m?.month ?? m?.payload?.month ?? null); }}>
                <LabelList dataKey="trucks" position="top" formatter={(v: unknown) => v != null && Number(v) > 0 ? barLbl(v) : ""}
                           fill="var(--ink)" fontSize={9} fontWeight={600} />
                {sc.monthly.map((m) => (
                  <Cell key={m.month} fill={m.month === openSupply ? "#9e5a6f" : "#cca8b3"} />
                ))}
              </Bar>
              <Line dataKey="trucks" name="Trend" type="monotone" stroke="#4a2030"
                    strokeWidth={2} dot={{ r: 3, fill: "#9e5a6f", strokeWidth: 2, stroke: "#fff" }}
                    isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>

        {openSupply && (() => {
          const sm = sc.monthly.find((m) => m.month === openSupply);
          if (!sm) return null;
          return (
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="card" style={{ borderColor: "var(--grid)" }}>
                <div className="flex items-center justify-between mb-2">
                  <div className="text-sm font-medium">{sm.label} — Day-by-Day Trucks ({sc.truck_mt} MT/truck)</div>
                  <button className="chip text-xs" onClick={() => setOpenSupply(null)}>close ✕</button>
                </div>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={sm.daily} margin={{ left: 4, right: 4, top: 4, bottom: 16 }}>
                    <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" />
                    <XAxis dataKey="date" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 8 }} tickFormatter={(dd: string) => dd.slice(8)} interval={2} />
                    <YAxis stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }} width={28} allowDecimals={false} />
                    <Tooltip formatter={(v) => [`${fmt(v as number)} loads`, "Trucks"]}
                             contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 8, fontSize: 12 }} />
                    <Bar dataKey="trucks" fill="#9e5a6f" radius={[2, 2, 0, 0]} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
                <div className="text-xs" style={{ color: "var(--muted)" }}>
                  Total: {fmt(sm.trucks)} loads · Peak day: {sm.peak_day_trucks} trucks
                </div>
              </div>
              <div className="card" style={{ borderColor: "var(--grid)" }}>
                <div className="text-sm font-medium mb-2">{sm.label} — Daily Dispatch Table</div>
                <div className="overflow-x-auto max-h-64">
                  <table className="w-full text-xs" style={{ borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "2px solid var(--grid)" }}>
                        <th className="text-left py-1.5 px-2" style={{ color: "var(--muted)" }}>Date</th>
                        <th className="text-left py-1.5 px-2" style={{ color: "var(--muted)" }}>Day</th>
                        <th className="text-right py-1.5 px-2" style={{ color: "var(--muted)" }}>MT</th>
                        <th className="text-right py-1.5 px-2" style={{ color: "var(--muted)" }}>Trucks</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sm.daily.slice(0, 31).map((dd) => (
                        <tr key={dd.date} style={{ borderBottom: "1px solid var(--grid)" }}>
                          <td className="py-1 px-2 font-mono">{dd.date.slice(5)}</td>
                          <td className="py-1 px-2">{dd.day}</td>
                          <td className="text-right py-1 px-2 font-mono">{fmt(dd.mt)}</td>
                          <td className="text-right py-1 px-2 font-mono" style={{ color: dd.trucks >= sm.peak_day_trucks ? "var(--crit)" : "var(--ink)" }}>{dd.trucks}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          );
        })()}
      </section>

      {/* ════════════════════════════════════════════════════════════
          SECTION: Model Performance
          ════════════════════════════════════════════════════════════ */}
      {bake && (
        <section id="validation" className="scroll-mt-32">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <span className="w-1 h-5 rounded-full inline-block" style={{ background: "#2E7D32" }} />
            Model Performance — 2-Origin Backtest
          </h2>
          <p className="text-xs mb-3" style={{ color: "var(--muted)" }}>
            Each model trained on data up to the cutoff, then forecasts the next 6 months blind. Black line = actual.
            Champion: <b>{bake.champion}</b> (WAPE {(bake.champion_wape * 100).toFixed(1)}%, BIAS {(bake.champion_bias * 100).toFixed(1)}%).
          </p>

          <div className="overflow-x-auto mb-4">
            <table className="w-full text-xs" style={{ borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "2px solid var(--grid)" }}>
                  <th className="text-left py-1.5 px-2" style={{ color: "var(--muted)" }}>#</th>
                  <th className="text-left py-1.5 px-2" style={{ color: "var(--muted)" }}>Model</th>
                  <th className="text-right py-1.5 px-2" style={{ color: "var(--muted)" }}>WAPE Avg</th>
                  <th className="text-right py-1.5 px-2" style={{ color: "var(--muted)" }}>BIAS Avg</th>
                  <th className="text-right py-1.5 px-2" style={{ color: "var(--muted)" }}>MASE</th>
                </tr>
              </thead>
              <tbody>
                {bake.leaderboard.map((r, idx) => (
                  <tr key={r.model} style={{ borderBottom: "1px solid var(--grid)", background: r.model === bake.champion ? "var(--surface-2)" : "transparent" }}>
                    <td className="py-1.5 px-2" style={{ color: "var(--muted)" }}>{idx + 1}</td>
                    <td className="py-1.5 px-2 font-medium">
                      <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: mc(r.model, idx), marginRight: 4 }} />
                      {r.model === bake.champion ? "★ " : ""}{r.model}
                    </td>
                    <td className="text-right py-1.5 px-2 tabular-nums font-bold"
                        style={{ color: r.wape_avg != null && r.wape_avg < 0.15 ? "#2E7D32" : "var(--ink)" }}>
                      {r.wape_avg != null ? `${(r.wape_avg * 100).toFixed(1)}%` : "—"}
                    </td>
                    <td className="text-right py-1.5 px-2 tabular-nums"
                        style={{ color: r.bias_avg != null && Math.abs(r.bias_avg) < 0.05 ? "var(--ink)" : "var(--crit)" }}>
                      {r.bias_avg != null ? `${r.bias_avg >= 0 ? "+" : ""}${(r.bias_avg * 100).toFixed(1)}%` : "—"}
                    </td>
                    <td className="text-right py-1.5 px-2 tabular-nums">
                      {r.mase_avg != null ? r.mase_avg.toFixed(2) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            {[{
              title: `Origin 1 — Train through ${bake.backtest_origins[0]?.train_through ?? "—"}, Test ${bake.backtest_origins[0]?.test_window ?? "—"}`,
              origin: bake.origin1_details, months: MONTHS_O1,
            }, {
              title: `Origin 2 — Train through ${bake.backtest_origins[1]?.train_through ?? "—"}, Test ${bake.backtest_origins[1]?.test_window ?? "—"}`,
              origin: bake.origin2_details, months: MONTHS_O2,
            }].map((bt) => {
              const chartData = backtestChart(bt.origin, bt.months);
              return (
                <div key={bt.title} className="card" style={{ borderColor: "var(--grid)" }}>
                  <div className="text-sm font-medium mb-2">{bt.title}</div>
                  <ResponsiveContainer width="100%" height={280}>
                    <LineChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
                      <XAxis dataKey="month" tick={{ fontSize: 11 }} stroke="var(--muted)" />
                      <YAxis tickFormatter={(v: number) => v >= 1e3 ? `${(v / 1e3).toFixed(0)}k` : `${v}`}
                             tick={{ fontSize: 10 }} stroke="var(--muted)" width={48} />
                      <Tooltip formatter={(v) => [fmt(Number(v)), ""]}
                               contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 8, fontSize: 12 }} />
                      <Legend wrapperStyle={{ fontSize: 10 }} />
                      <Line type="monotone" dataKey="Actual" stroke="#000" strokeWidth={2.5}
                            dot={{ r: 3, fill: "#000" }} name="Actual" />
                      {topModels.map((m, i) => (
                        <Line key={m} type="monotone" dataKey={m} stroke={mc(m, i)}
                              strokeWidth={m === bake.champion ? 2.5 : 1.5}
                              strokeDasharray={m === bake.champion ? "" : "5 3"}
                              dot={{ r: m === bake.champion ? 3 : 2 }} name={m} />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* ════════════════════════════════════════════════════════════
          SECTION: Full History + Forecast
          ════════════════════════════════════════════════════════════ */}
      <section className="scroll-mt-32">
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <span className="w-1 h-5 rounded-full inline-block" style={{ background: "#6c5ce7" }} />
          Full Series — History + 12-Month Forecast
        </h2>
        <div className="card" style={{ borderColor: "var(--grid)" }}>
          <div className="text-sm font-medium mb-2">
            {national.n_months} months actual + 12 months forecast &middot; {fmt(national.annual_forecast_mt)} MT projected annual
          </div>
          <ResponsiveContainer width="100%" height={380}>
            <ComposedChart data={(() => {
              const rows: Record<string, number | string | null>[] = [];
              for (const h of national.history) {
                rows.push({ label: h.label, actual: h.actual_mt, fitted: h.fitted_mt ?? null, forecast: null, lo80: null, hi80: null });
              }
              for (const f of national.forecast) {
                rows.push({ label: f.label, actual: null, fitted: null, forecast: f.forecast_mt, lo80: f.lo80, hi80: f.hi80 });
              }
              return rows;
            })()} margin={{ left: 8, right: 8, top: 14, bottom: 18 }}>
              <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" />
              <XAxis dataKey="label" stroke="transparent"
                     tick={{ fill: "var(--muted)", fontSize: 9 }}
                     minTickGap={24} interval="preserveStartEnd" />
              <YAxis stroke="transparent"
                     tick={{ fill: "var(--muted)", fontSize: 9 }}
                     tickFormatter={(v) => fmt(v)} width={54} />
              <Tooltip formatter={(v, n) => [`${fmt(v as number)} MT`, String(n)]}
                       contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 8, fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Bar dataKey="actual" name="Actual" fill="#d0d8e0" radius={[1, 1, 0, 0]} isAnimationActive={false} />
              <Bar dataKey="forecast" name="Forecast" fill="#4f8fc9" radius={[1, 1, 0, 0]} isAnimationActive={false} />
              <Line dataKey="fitted" name="Fitted" type="monotone" stroke="#2E7D32" strokeWidth={1.5} dot={false}
                    connectNulls isAnimationActive={false} />
              <Line dataKey="forecast" name="Trend" type="monotone" stroke="#1a3a5c" strokeWidth={2.5} dot={{ r: 3, fill: "#1a3a5c", strokeWidth: 2, stroke: "#fff" }}
                    connectNulls isAnimationActive={false} />
              <Line dataKey="lo80" name="Lo 80" type="monotone" stroke="#4f8fc9" strokeWidth={1} strokeDasharray="4 4"
                    dot={false} connectNulls isAnimationActive={false} legendType="none" />
              <Line dataKey="hi80" name="Hi 80" type="monotone" stroke="#4f8fc9" strokeWidth={1} strokeDasharray="4 4"
                    dot={false} connectNulls isAnimationActive={false} legendType="none" />
            </ComposedChart>
          </ResponsiveContainer>
          <div className="text-xs mt-2" style={{ color: "var(--muted)" }}>
            {national.history[0]?.label} – {national.forecast[national.forecast.length - 1]?.label} &middot;
            Total actual: {fmt(national.history.reduce((a, h) => a + h.actual_mt, 0))} MT &middot;
            Forecast: {fmt(national.annual_forecast_mt)} MT &middot;
            80% CI band shown in dashed blue
          </div>
        </div>
      </section>

      <p className="text-xs mt-8 pt-4" style={{ color: "var(--muted)", borderTop: "1px solid var(--grid)", lineHeight: 1.6 }}>
        Method: Holt-Winters (additive, damped) trained on 59 months of ACCL sales from SQL Server.
        Materials = forecast x ACCL cement recipe. Districts = proportional to historical share, reconciled to national.
        Supply chain = forecast / day-of-week dispatch profile / truck capacity (@ {sc.truck_mt} MT/truck).
      </p>
    </div>
    </>
  );
}
