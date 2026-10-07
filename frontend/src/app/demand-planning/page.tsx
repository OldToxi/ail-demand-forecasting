"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Label,
  BarChart, Cell, LabelList,
} from "recharts";
import { apiGet, fmt } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { ErrorCard, PageSkeleton } from "@/components/States";
import { PlantPicker, ChangePlantChip } from "@/components/PlantGate";

type Target = {
  source: string;
  latest_full_year: number;
  latest_market_mmt: number; latest_accl_mmt: number; latest_share_pct: number;
  cagr_windows: Record<string, number>;
  default_cagr_window_yr: number; default_cagr_pct: number;
  accl_trend_cagr_pct: number; default_target_share_pct: number;
  market_next12_mmt: number; target_accl_next12_mmt: number;
  baseline_accl_next12_mmt: number; gap_vs_baseline_mmt: number;
  monthly_target_mt: number[];
  seasonality: Record<string, number>;
  years: number[]; market_mmt: number[]; accl_mmt: number[]; share_pct: number[];
  full_years: number[];
  production: {
    type_mix: Record<string, number>;
    blended_ratio_per_ton: Record<string, number>;
    by_type_ratio: Record<string, Record<string, number>>;
  };
  dispatch: { dow_profile: Record<string, number>; default_truck_mt: number; dow_order: string[] };
  accl_monthly_history: Record<string, number>;   // "YYYY-MM" -> actual ACCL cement MT (completed months)
  growth_rates?: { min: number; max: number; step: number; default: number };
};

const MATERIALS = ["Clinker", "Gypsum", "Limestone", "Slag"];
const MAT_ICON: Record<string, string> = { Clinker: "🔥", Gypsum: "⚪", Limestone: "🪨", Slag: "⛏️" };

// compact in-bar value label with a decimal so precision isn't lost: 45.16M · 94.3k · 231
// (rendered vertically inside the bar so the decimals fit — see the LabelList angle).
const barLbl = (v: string | number | boolean | null | undefined): string => {
  if (v == null || typeof v === "boolean") return "";
  const n = typeof v === "number" ? v : Number(v);
  if (!isFinite(n) || n === 0) return "";
  const a = Math.abs(n);
  if (a >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return `${Math.round(n)}`;
};

export default function DemandTarget() {
  const [entered, setEntered] = useState(false);
  const [t, setT] = useState<Target | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [cagrKey, setCagrKey] = useState<string>("");
  const [share, setShare] = useState<number>(0);
  const [growthRate, setGrowthRate] = useState<number>(0);
  const [truckMt, setTruckMt] = useState<number>(15);
  const [openMonth, setOpenMonth] = useState<string | null>(null);
  const [selMat, setSelMat] = useState<string>("Clinker");
  const [openMatMonth, setOpenMatMonth] = useState<number | null>(null);
  useEffect(() => {
    apiGet<Target>("/demand-planning/market-target")
      .then((d) => { setT(d); setCagrKey(`${d.default_cagr_window_yr}yr`); setShare(d.default_target_share_pct); setGrowthRate(d.default_cagr_pct); })
      .catch((e) => setErr(String(e)));
  }, []);

  // live recompute from CAGR window + target share
  // ONE shared rolling-12-month axis used by sales, materials AND dispatch — so every monthly chart on
  // the page lines up month-for-month (avoids the Jan-Dec vs rolling mismatch).
  const rollingMonths = useMemo(() => {
    if (!t) return [];
    const start = new Date(); start.setDate(1); start.setMonth(start.getMonth() + 1);
    return Array.from({ length: 12 }, (_, i) => {
      const d = new Date(start.getFullYear(), start.getMonth() + i, 1);
      return {
        key: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`,
        label: d.toLocaleString("en", { month: "short", year: "2-digit" }),
        monthNum: d.getMonth() + 1, year: d.getFullYear(),
        seas: t.seasonality[String(d.getMonth() + 1)] ?? 1,
      };
    });
  }, [t]);

  const calc = useMemo(() => {
    if (!t || rollingMonths.length === 0) return null;
    const cagr = growthRate;
    const marketNext = t.latest_market_mmt * (1 + cagr / 100);
    const targetAccl = marketNext * share / 100;            // M MT
    const baseline = t.latest_accl_mmt * (1 + t.accl_trend_cagr_pct / 100);
    const targetMt = targetAccl * 1e6;
    const ssum = rollingMonths.reduce((a, m) => a + m.seas, 0);
    // monthly sales target on the rolling axis
    const monthly = rollingMonths.map((m) => ({
      month: m.label, target: Math.round(targetMt * m.seas / ssum),
    }));
    // raw materials for the target sales, same rolling axis
    const materials = MATERIALS.map((mat) => {
      const ratio = t.production.blended_ratio_per_ton[mat] ?? 0;
      return {
        material: mat,
        annual: Math.round(targetMt * ratio),
        monthly: rollingMonths.map((m) => ({
          month: m.label, monthNum: m.monthNum, key: m.key, year: m.year,
          mt: Math.round(targetMt * ratio * m.seas / ssum),
        })),
      };
    });
    return { cagr, marketNext, targetAccl, targetMt, baseline, gap: targetAccl - baseline, monthly, materials };
  }, [t, cagrKey, share, growthRate, rollingMonths]);

  // day-wise dispatch: spread the target sales across the next 12 months' calendar days using the
  // day-of-week profile, then trucks/day = ceil(daily MT / truck capacity). Recomputes with share + capacity.
  const dispatch = useMemo(() => {
    if (!t || !calc || rollingMonths.length === 0) return null;
    const dow = t.dispatch.dow_profile;                       // Mon..Sun weights (mean 1)
    const dowName = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
    const seasSum = rollingMonths.reduce((a, m) => a + m.seas, 0);
    let annualLoads = 0, peakDay = 0;
    // same rolling months as sales/materials -> monthly totals line up exactly
    const monthly = rollingMonths.map((m) => {
      const monthMt = calc.targetMt * m.seas / seasSum;       // = the sales monthly target for this month
      const days: Date[] = [];
      for (let day = 1; new Date(m.year, m.monthNum - 1, day).getMonth() === m.monthNum - 1; day++)
        days.push(new Date(m.year, m.monthNum - 1, day));
      const wsum = days.reduce((a, d) => a + (dow[dowName[d.getDay()]] ?? 1), 0);
      const daily = days.map((d) => {
        const mt = monthMt * (dow[dowName[d.getDay()]] ?? 1) / wsum;
        const tk = Math.ceil(mt / truckMt);
        annualLoads += tk; peakDay = Math.max(peakDay, tk);
        return { date: `${m.key}-${String(d.getDate()).padStart(2, "0")}`, mt, trucks: tk };
      });
      return { key: m.key, label: m.label, trucks: daily.reduce((a, x) => a + x.trucks, 0),
               peak: daily.reduce((a, x) => Math.max(a, x.trucks), 0), daily };
    });
    return { monthly, annualLoads, peakDay, avgDay: Math.round(annualLoads / 365) };
  }, [t, calc, truckMt, rollingMonths]);
  const openDays = useMemo(() =>
    dispatch && openMonth ? (dispatch.monthly.find((m) => m.key === openMonth)?.daily ?? []) : [],
    [dispatch, openMonth]);

  // selected raw material (Clinker default) — its rolling-12 monthly requirement drives the chart below
  const selMaterial = useMemo(
    () => calc?.materials.find((m) => m.material === selMat) ?? calc?.materials[0] ?? null,
    [calc, selMat]);

  // click a month -> that calendar month's PAST actual need (history volume × current recipe) + FUTURE plan.
  // "all in sync": past uses the SAME blended ratio the plan uses, so actual↔plan are directly comparable.
  const matMonthHistory = useMemo(() => {
    if (!t || !calc || openMatMonth == null) return null;
    const ratio = t.production.blended_ratio_per_ton[selMat] ?? 0;
    const rows: { label: string; actual?: number; plan?: number }[] = [];
    Object.entries(t.accl_monthly_history).forEach(([ym, vol]) => {
      const [y, mo] = ym.split("-").map(Number);
      if (mo === openMatMonth) rows.push({ label: String(y), actual: Math.round(vol * ratio) });
    });
    const fut = selMaterial?.monthly.find((mm) => mm.monthNum === openMatMonth);
    if (fut) rows.push({ label: `${fut.year} (plan)`, plan: fut.mt });
    rows.sort((a, b) => parseInt(a.label) - parseInt(b.label));
    const monthName = new Date(2000, openMatMonth - 1, 1).toLocaleString("en", { month: "long" });
    return { rows, monthName };
  }, [t, calc, selMat, openMatMonth, selMaterial]);

  if (err) return <ErrorCard error={err} />;
  if (!entered) {
    return (
      <div className="space-y-5">
        <PageHeader title="Demand Planning" subtitle="Choose a plant to open its 12-month sales target." />
        <PlantPicker subtitle="Top-down CAGR target — the national-market-matched 12-month sales goal for ACCL."
                     onEnter={() => setEntered(true)} />
      </div>
    );
  }
  if (!t || !calc) return <PageSkeleton />;

  // yearly market/share chart data — in tonnes (MT), not millions (ACCL is too small a number in M)
  const yearData = t.years.map((y, i) => ({
    year: y, market: Math.round(t.market_mmt[i] * 1e6), accl: Math.round(t.accl_mmt[i] * 1e6), share: t.share_pct[i],
  }));
  const cagrOptions = Object.keys(t.cagr_windows);
  const trendDown = t.accl_trend_cagr_pct < 0;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Demand Planning — 12-month target (ACCL)"
        subtitle="National market → ACCL share → required sales → required production. Adjust the share lever; everything re-derives."
        right={<ChangePlantChip onExit={() => setEntered(false)} />}
      />

      {/* levers */}
      <div className="card" style={{ borderColor: "var(--s3)" }}>
        <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
          <div className="font-medium" style={{ borderLeft: "3px solid var(--s3)", paddingLeft: 8 }}>Target levers</div>
          <label className="flex items-center gap-2 text-sm">
            <span style={{ color: "var(--muted)" }}>Market CAGR</span>
            <select value={cagrKey} onChange={(e) => { setCagrKey(e.target.value); setGrowthRate(t.cagr_windows[e.target.value] ?? t.default_cagr_pct); }}
                    className="rounded border px-2 py-1 text-sm"
                    style={{ background: "var(--surface-1)", borderColor: "var(--grid)", color: "var(--ink)" }}>
              {cagrOptions.map((k) => (
                <option key={k} value={k}>{k} ({t.cagr_windows[k] >= 0 ? "+" : ""}{t.cagr_windows[k]}%/yr)</option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <span style={{ color: "var(--muted)" }}>Growth rate</span>
            <input type="range" min={t.growth_rates?.min ?? -10} max={t.growth_rates?.max ?? 25} step={t.growth_rates?.step ?? 0.1}
                   value={growthRate}
                   onChange={(e) => setGrowthRate(Number(e.target.value))}
                   className="w-28" />
            <b style={{ color: "var(--s3)", minWidth: 60, textAlign: "right" }}>{growthRate >= 0 ? "+" : ""}{growthRate.toFixed(1)}%</b>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <span style={{ color: "var(--muted)" }}>Target share</span>
            <input type="range" min={3} max={7} step={0.1} value={share}
                   onChange={(e) => setShare(Number(e.target.value))} />
            <b style={{ color: "var(--s1)", minWidth: 44 }}>{share.toFixed(1)}%</b>
          </label>
          <button className="chip" onClick={() => { setCagrKey(`${t.default_cagr_window_yr}yr`); setShare(t.default_target_share_pct); setGrowthRate(t.default_cagr_pct); }}>reset</button>
          <span className="text-xs" style={{ color: "var(--muted)" }}>
            {share > t.latest_share_pct + 0.05 ? "Share-gain target (above 2025)"
              : share < t.latest_share_pct - 0.05 ? "Below current share" : "Hold current share (turnaround)"}
          </span>
        </div>
      </div>

      {/* headline target */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {[
            { k: "12-month sales target", v: `${(calc.targetAccl).toFixed(2)}M`, s: "MT — plan to this", hi: true },
            { k: "National market (next 12m)", v: `${calc.marketNext.toFixed(1)}M`, s: `MT @ ${calc.cagr >= 0 ? "+" : ""}${calc.cagr.toFixed(1)}% market growth` },
            { k: "Implied share", v: `${share.toFixed(1)}%`, s: `vs ${t.latest_share_pct}% in ${t.latest_full_year}` },
            { k: "Gap vs do-nothing", v: `${calc.gap >= 0 ? "+" : ""}${(calc.gap * 1000).toFixed(0)}k`, s: "MT to close — the ask", warn: calc.gap > 0 },
          ].map((x) => (
          <div key={x.k} className="card">
            <div className="text-sm" style={{ color: "var(--muted)" }}>{x.k}</div>
            <div className="text-2xl font-semibold" style={{ color: x.hi ? "var(--s1)" : x.warn ? "var(--crit)" : "var(--ink)" }}>{x.v}</div>
            <div className="text-xs" style={{ color: "var(--muted)" }}>{x.s}</div>
          </div>
        ))}
      </div>

      {/* turnaround note */}
      <div className="card" style={{ background: "color-mix(in srgb, var(--s1) 5%, var(--surface-1))", borderColor: "color-mix(in srgb, var(--s1) 22%, var(--grid))" }}>
        <div className="text-sm" style={{ color: "var(--ink-2)" }}>
          ACCL peaked at <b>2.39M MT / 5.3% share (2022)</b> and slid to <b>{t.latest_accl_mmt}M / {t.latest_share_pct}% ({t.latest_full_year})</b>
          {trendDown && <> — a do-nothing trend of <b>{t.accl_trend_cagr_pct}%/yr</b> drifts down to ~{calc.baseline.toFixed(2)}M</>}.
          Holding {share.toFixed(1)}% share while the market grows {calc.cagr >= 0 ? "+" : ""}{calc.cagr.toFixed(1)}% sets a target of
          <b> {calc.targetAccl.toFixed(2)}M MT</b> — i.e. <b>{calc.gap >= 0 ? "+" : ""}{(calc.gap * 1000).toFixed(0)}k MT above the drift</b>.
          {" "}The raw materials to produce it are below.
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* monthly target */}
        <div className="card">
          <div className="font-medium" style={{ borderLeft: "3px solid var(--s1)", paddingLeft: 8 }}>Monthly target — next 12 months</div>
          <div className="mb-2 text-xs" style={{ color: "var(--muted)" }}>
            Annual target split by cement seasonality (dry-season peak, monsoon trough). Sums to {calc.targetAccl.toFixed(2)}M MT.
          </div>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={calc.monthly} margin={{ left: 12, right: 12, top: 6, bottom: 20 }}>
              <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" />
              <XAxis dataKey="month" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 10 }}>
                <Label value="Month (rolling 12)" position="insideBottom" offset={-10} style={{ fill: "var(--muted)", fontSize: 10 }} />
              </XAxis>
              <YAxis stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 10 }} tickFormatter={(v) => fmt(v)} width={54}>
                <Label value="Target (MT)" angle={-90} position="insideLeft" style={{ fill: "var(--muted)", fontSize: 10, textAnchor: "middle" }} />
              </YAxis>
              <Tooltip formatter={(v) => [`${fmt(v as number)} MT`, "Monthly target"]}
                       contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 8, fontSize: 12 }} />
              <Bar dataKey="target" fill="var(--s1)" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                <LabelList dataKey="target" position="insideTop" angle={-90} offset={14} formatter={barLbl} fill="#fff" fontSize={9} fontWeight={600} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* market history + share — ONE chart: national market (bars, MT) + ACCL share (line, %) */}
        <div className="card">
          <div className="font-medium" style={{ borderLeft: "3px solid var(--s3)", paddingLeft: 8 }}>Market &amp; ACCL — history</div>
          <div className="mb-1 text-xs" style={{ color: "var(--muted)" }}>
            <b style={{ color: "var(--s2)" }}>Bars</b> = national market volume (MT, left).
            <b style={{ color: "var(--s1)" }}> Line</b> = ACCL market share (%, right) — the market keeps growing while ACCL&apos;s
            share is the slice the target defends. Source: actual brand-level sales panel.
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart data={yearData} margin={{ left: 12, right: 12, top: 18, bottom: 4 }} barCategoryGap="18%">
              <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" />
              <XAxis dataKey="year" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }} minTickGap={10} />
              <YAxis yAxisId="mt" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }} width={54} tickFormatter={(v) => fmt(v)}>
                <Label value="National market (MT)" angle={-90} position="insideLeft" style={{ fill: "var(--muted)", fontSize: 9, textAnchor: "middle" }} />
              </YAxis>
              <YAxis yAxisId="pct" orientation="right" domain={[0, 8]} stroke="transparent" tick={{ fill: "var(--s1)", fontSize: 9 }} width={38} tickFormatter={(v) => `${v}%`}>
                <Label value="ACCL share (%)" angle={90} position="insideRight" style={{ fill: "var(--s1)", fontSize: 9, textAnchor: "middle" }} />
              </YAxis>
              <Tooltip formatter={(v, n) => n === "share" ? [`${(v as number).toFixed(2)}%`, "ACCL share"] : [`${fmt(v as number)} MT`, "National market"]}
                       contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 8, fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Bar yAxisId="mt" dataKey="market" name="National market" fill="var(--s2)" radius={[2, 2, 0, 0]} isAnimationActive={false}>
                <LabelList dataKey="market" position="insideTop" angle={-90} offset={14} formatter={barLbl} fill="#fff" fontSize={9} fontWeight={600} />
              </Bar>
              <Line yAxisId="pct" dataKey="share" name="ACCL share %" stroke="var(--s1)" strokeWidth={2.4} dot={{ r: 2.5 }} isAnimationActive={false}>
                <LabelList dataKey="share" position="top" formatter={(v: string | number | boolean | null | undefined) => (v == null || typeof v === "boolean") ? "" : `${Number(v).toFixed(1)}%`} fill="var(--s1)" fontSize={9} fontWeight={600} />
              </Line>
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* required production — raw materials for the target sales (driven by the share lever) */}
      <div className="card">
        <div className="flex flex-wrap items-center gap-2">
          <div className="font-medium" style={{ borderLeft: "3px solid var(--s1)", paddingLeft: 8 }}>
            Required production for the target — raw materials
          </div>
          <span className="chip" style={{ borderColor: "var(--s1)", color: "var(--s1)" }}>drives with the share lever</span>
        </div>
        <div className="mb-3 mt-1 text-xs" style={{ color: "var(--muted)" }}>
          To sell <b>{calc.targetAccl.toFixed(2)}M MT</b> of cement, you must produce these raw materials
          (target volume × ACCL&apos;s cement recipe — {(t.production.type_mix["CEM-II"] * 100).toFixed(0)}% CEM-II, blended).
          Move the share slider and every material re-sizes. <b>Click a material</b> to see its monthly requirement.
        </div>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {calc.materials.map((m) => {
            const isSel = m.material === selMat;
            const isClinker = m.material === "Clinker";
            return (
              <button key={m.material} type="button"
                      onClick={() => { setSelMat(m.material); setOpenMatMonth(null); }}
                      className="card text-left"
                      style={{ cursor: "pointer",
                               ...(isSel ? { borderColor: "var(--s1)", background: "color-mix(in srgb, var(--s1) 6%, var(--surface-1))" } : {}) }}>
                <div className="flex items-center gap-2 text-sm" style={{ color: "var(--muted)" }}>
                  <span>{MAT_ICON[m.material]}</span>{m.material}{isClinker && <span className="chip" style={{ fontSize: 9, borderColor: "var(--s1)", color: "var(--s1)" }}>make-vs-buy</span>}
                </div>
                <div className="text-2xl font-semibold" style={{ color: isSel ? "var(--s1)" : "var(--ink)" }}>
                  {fmt(m.annual)}
                </div>
                <div className="text-xs" style={{ color: "var(--muted)" }}>
                  MT/yr · {(t.production.blended_ratio_per_ton[m.material] * 1000).toFixed(0)} kg per t cement
                </div>
              </button>
            );
          })}
        </div>
        {/* selected material's monthly profile — click a month for its past-vs-plan history */}
        {selMaterial && (
        <div className="mt-4">
          <div className="mb-1 text-xs" style={{ color: "var(--muted)" }}>
            <b>{selMat}</b> — monthly requirement{selMat === "Clinker" && " (the procurement lead-time driver; import ~45–60 days ahead)"}.
            {" "}<b>Click a month</b> for its past actual vs plan.
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={selMaterial.monthly} margin={{ left: 12, right: 12, top: 4, bottom: 18 }}>
              <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" />
              <XAxis dataKey="month" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }}>
                <Label value="Month (rolling 12) — click a bar" position="insideBottom" offset={-9} style={{ fill: "var(--muted)", fontSize: 9 }} />
              </XAxis>
              <YAxis stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }} tickFormatter={(v) => fmt(v)} width={48} />
              <Tooltip formatter={(v) => [`${fmt(v as number)} MT ${selMat.toLowerCase()}`, "Monthly"]}
                       contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 8, fontSize: 12 }} />
              <Bar dataKey="mt" radius={[3, 3, 0, 0]} isAnimationActive={false} cursor="pointer"
                   onClick={(d) => { const p = d as unknown as { monthNum?: number; payload?: { monthNum?: number } }; const mn = p?.monthNum ?? p?.payload?.monthNum; if (mn) setOpenMatMonth(mn === openMatMonth ? null : mn); }}>
                <LabelList dataKey="mt" position="insideTop" angle={-90} offset={14} formatter={barLbl} fill="#fff" fontSize={9} fontWeight={600} />
                {selMaterial.monthly.map((mm) => <Cell key={mm.key} fill={mm.monthNum === openMatMonth ? "var(--s3)" : "var(--s1)"} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        )}
        {matMonthHistory && (
          <div className="mt-3 rounded-lg border p-3" style={{ borderColor: "var(--s3)", background: "color-mix(in srgb, var(--s3) 5%, var(--surface-1))" }}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-sm font-medium">{selMat} in {matMonthHistory.monthName} — actual history vs plan</div>
              <button className="chip" onClick={() => setOpenMatMonth(null)}>close ✕</button>
            </div>
            <div className="mb-1 mt-1 text-xs" style={{ color: "var(--muted)" }}>
              Past bars = actual ACCL delivery volume for {matMonthHistory.monthName} × the current recipe; the plan bar is this target&apos;s requirement.
            </div>
            <ResponsiveContainer width="100%" height={190}>
              <BarChart data={matMonthHistory.rows} margin={{ left: 12, right: 12, top: 8, bottom: 18 }}>
                <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" />
                <XAxis dataKey="label" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }}>
                  <Label value={matMonthHistory.monthName} position="insideBottom" offset={-9} style={{ fill: "var(--muted)", fontSize: 9 }} />
                </XAxis>
                <YAxis stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }} tickFormatter={(v) => fmt(v)} width={48} />
                <Tooltip formatter={(v, n) => [`${fmt(v as number)} MT`, n === "plan" ? "Plan" : "Actual"]}
                         contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 8, fontSize: 12 }} />
                <Legend wrapperStyle={{ fontSize: 10 }} />
                <Bar dataKey="actual" name="Actual" fill="var(--s1)" radius={[2, 2, 0, 0]} isAnimationActive={false}>
                  <LabelList dataKey="actual" position="insideTop" angle={-90} offset={14} formatter={barLbl} fill="#fff" fontSize={9} fontWeight={600} />
                </Bar>
                <Bar dataKey="plan" name="Plan" fill="var(--s3)" radius={[2, 2, 0, 0]} isAnimationActive={false}>
                  <LabelList dataKey="plan" position="insideTop" angle={-90} offset={14} formatter={barLbl} fill="var(--ink)" fontSize={9} fontWeight={600} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
        <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
          Blend from ACCL&apos;s actual type mix: CEM-II {(t.production.type_mix["CEM-II"] * 100).toFixed(1)}% ·
          OPC {(t.production.type_mix["OPC"] * 100).toFixed(1)}% · PCC {(t.production.type_mix["PCC"] * 100).toFixed(1)}%.
          Full per-material BOM detail on the <Link href="/production" style={{ color: "var(--s1)" }}>Production</Link> page.
        </p>
      </div>

      {/* day-wise dispatch — trucks to move the target, from the daily dispatch profile (driven by share) */}
      {dispatch && (
        <div className="card">
          <div className="flex flex-wrap items-center gap-2">
            <div className="font-medium" style={{ borderLeft: "3px solid var(--s3)", paddingLeft: 8 }}>
              Day-wise dispatch plan — trucks to move the target
            </div>
            <span className="chip" style={{ borderColor: "var(--s3)", color: "var(--s3)" }}>drives with the share lever</span>
            <div className="ml-auto flex items-center gap-2 text-sm">
              <label style={{ color: "var(--muted)" }}>Truck capacity</label>
              <input type="number" min={1} max={40} step={1} value={truckMt}
                     onChange={(e) => setTruckMt(Math.max(1, Number(e.target.value) || 1))}
                     className="w-16 rounded border px-2 py-1 text-right"
                     style={{ background: "var(--surface-1)", borderColor: "var(--s1)", color: "var(--ink)" }} />
              <span style={{ color: "var(--muted)" }}>MT</span>
            </div>
          </div>
          <div className="mb-3 mt-1 text-xs" style={{ color: "var(--muted)" }}>
            The {calc.targetAccl.toFixed(2)}M MT target spread across days by the actual dispatch day-of-week profile
            (Fri/Sat lighter), then trucks/day = ceil(daily MT ÷ {truckMt} MT). <b>Click a month</b> for its day-by-day plan.
          </div>
          <div className="grid grid-cols-3 gap-4">
            {[
              { k: "Annual truckloads", v: fmt(dispatch.annualLoads), hi: true },
              { k: "Avg trucks / day", v: fmt(dispatch.avgDay) },
              { k: "Peak day (fleet sizing)", v: fmt(dispatch.peakDay) },
            ].map((x) => (
              <div key={x.k}>
                <div className="text-xs" style={{ color: "var(--muted)" }}>{x.k}</div>
                <div className="text-xl font-semibold" style={{ color: x.hi ? "var(--s1)" : "var(--ink)" }}>{x.v}</div>
              </div>
            ))}
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={dispatch.monthly} margin={{ left: 12, right: 12, top: 8, bottom: 20 }}>
              <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" />
              <XAxis dataKey="label" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 10 }} minTickGap={8}>
                <Label value="Month (click for day-wise)" position="insideBottom" offset={-10} style={{ fill: "var(--muted)", fontSize: 10 }} />
              </XAxis>
              <YAxis stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 10 }} width={44}>
                <Label value="Truckloads / month" angle={-90} position="insideLeft" style={{ fill: "var(--muted)", fontSize: 10, textAnchor: "middle" }} />
              </YAxis>
              <Tooltip formatter={(v) => [`${fmt(v as number)} loads`, "Truckloads"]}
                       contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 8, fontSize: 12 }} />
              <Bar dataKey="trucks" radius={[3, 3, 0, 0]} isAnimationActive={false} cursor="pointer"
                   onClick={(d) => { const m = d as unknown as { key?: string; payload?: { key?: string } }; const k = m?.key ?? m?.payload?.key; if (k) setOpenMonth(k === openMonth ? null : k); }}>
                <LabelList dataKey="trucks" position="insideTop" angle={-90} offset={14} formatter={barLbl} fill="#fff" fontSize={9} fontWeight={600} />
                {dispatch.monthly.map((m) => <Cell key={m.key} fill={m.key === openMonth ? "var(--s3)" : "var(--s1)"} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>

          {openMonth && (
            <div className="mt-3 rounded-lg border p-3" style={{ borderColor: "var(--s3)", background: "color-mix(in srgb, var(--s3) 5%, var(--surface-1))" }}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-sm font-medium">{openMonth} — day-by-day trucks (@ {truckMt} MT)</div>
                <div className="text-xs" style={{ color: "var(--muted)" }}>
                  {fmt(openDays.reduce((a, d) => a + d.trucks, 0))} loads · peak <b style={{ color: "var(--s3)" }}>{openDays.reduce((a, d) => Math.max(a, d.trucks), 0)}</b>/day
                  <button className="chip" style={{ marginLeft: 6 }} onClick={() => setOpenMonth(null)}>close ✕</button>
                </div>
              </div>
              <ResponsiveContainer width="100%" height={190}>
                <BarChart data={openDays} margin={{ left: 8, right: 8, top: 8, bottom: 18 }}>
                  <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" />
                  <XAxis dataKey="date" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }} tickFormatter={(d: string) => d.slice(8)} interval={1}>
                    <Label value={`Day of ${openMonth}`} position="insideBottom" offset={-9} style={{ fill: "var(--muted)", fontSize: 9 }} />
                  </XAxis>
                  <YAxis stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 9 }} width={30} allowDecimals={false} />
                  <Tooltip formatter={(v) => [`${fmt(v as number)} loads`, "Trucks"]}
                           contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 8, fontSize: 12 }} />
                  <Bar dataKey="trucks" fill="var(--s3)" radius={[2, 2, 0, 0]} isAnimationActive={false}>
                    <LabelList dataKey="trucks" position="insideTop" angle={-90} offset={14} formatter={barLbl} fill="var(--ink)" fontSize={8} fontWeight={600} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
              <div className="mt-1 text-xs" style={{ color: "var(--muted)" }}>Lighter on Fri/Sat — the real dispatch rhythm.</div>
            </div>
          )}
          <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
            Day-of-week weights from the actual daily delivery history. Full per-district truck plan on the
            <Link href="/demand-forecast-planning" style={{ color: "var(--s1)" }}> Demand Forecast</Link> page.
          </p>
        </div>
      )}

      <div className="flex flex-wrap gap-3 text-sm">
        <Link href="/demand-forecast-planning" className="chip">forecast (bottom-up) →</Link>
        <Link href="/production" className="chip">production detail →</Link>
        <Link href="/demand-forecast-planning" className="chip">supply chain →</Link>
      </div>
      <p className="text-xs" style={{ color: "var(--muted)" }}>
        Method: national market size &amp; growth rate from live brand-level sales panel ({t.years[0]}–{t.latest_full_year});
        target = market × growth rate × target share; monthly split by cement seasonality. All levers live.
        Source: {t.source}.
      </p>
    </div>
  );
}
