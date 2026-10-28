"use client";
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, ComposedChart, Line, Legend } from "recharts";
import { apiGet, fmt } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { ErrorCard, PageSkeleton } from "@/components/States";

// ── Types ────────────────────────────────────────────────────────
type Act = { month: string; actual_mt: number; actual_value?: number; provisional?: boolean; constrained?: boolean };
type CompanyDetail = { actuals: Act[] };
type UIPayload = {
  value_summary?: { currency: string; price_per_mt: number; forecast_value_12m: number; last12_value: number };
  series: { series_id: string; level: string; channel?: string; zone?: string; label?: string }[];
  detail: Record<string, CompanyDetail>;
};

type CagrKey = "1yr" | "2yr" | "3yr" | "5yr" | "all";
const CAGR_KEYS: CagrKey[] = ["1yr", "2yr", "3yr", "5yr", "all"];

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// crore = 10,000,000 (1e7)
const crore = (v?: number | null): string =>
  v == null ? "—" : (v / 1e7).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

type YearBucket = { year: number; mt: number; months: number };
type Calc = {
  annual: YearBucket[];
  fullYears: YearBucket[];
  latest: number | null;
  latestMt: number | null;
  last12Mt: number;
  cagrWindows: Record<CagrKey, number | null>;
  seasonality: number[];
  price: number | null;
};

// ── Page ─────────────────────────────────────────────────────────
export default function DemandPlanning() {
  const [sbu, setSbu] = useState<"AIL" | "ACL">("AIL");
  const [cagrKey, setCagrKey] = useState<CagrKey>("1yr");
  const [growthPct, setGrowthPct] = useState<number | null>(null);
  const [data, setData] = useState<{ AIL: UIPayload | null; ACL: UIPayload | null }>({ AIL: null, ACL: null });
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setErr(null);
    Promise.all([apiGet<UIPayload>("/forecast/ui"), apiGet<UIPayload>("/forecast/acl")])
      .then(([AIL, ACL]) => {
        if (!cancelled) setData({ AIL, ACL });
      })
      .catch((e) => {
        if (!cancelled) setErr(String(e));
      });
    return () => { cancelled = true; };
  }, []);

  const payload = sbu === "ACL" ? data.ACL : data.AIL;

  const calc = useMemo<Calc | null>(() => {
    if (!payload) return null;

    // company series → its actuals, plus the company price
    const company = payload.series.find((s) => s.level === "company");
    const sid = company?.series_id;
    const actuals = sid ? payload.detail[sid]?.actuals ?? [] : [];
    const price = payload.value_summary?.price_per_mt ?? null;

    // group actuals by calendar year
    const byYear = new Map<number, { mt: number; months: number }>();
    for (const a of actuals) {
      const year = Number(a.month.slice(0, 4));
      if (!Number.isFinite(year)) continue;
      const cur = byYear.get(year) ?? { mt: 0, months: 0 };
      cur.mt += a.actual_mt;
      cur.months += 1;
      byYear.set(year, cur);
    }
    const annual: YearBucket[] = [...byYear.entries()]
      .map(([year, v]) => ({ year, mt: v.mt, months: v.months }))
      .sort((a, b) => a.year - b.year);

    const fullYears = annual.filter((y) => y.months === 12);
    const latestYear = fullYears.length ? fullYears[fullYears.length - 1].year : null;
    const latestMt = latestYear != null ? fullYears[fullYears.length - 1].mt : null;

    const last12Mt = actuals.slice(-12).reduce((a, x) => a + x.actual_mt, 0);

    // CAGR windows: base year must exist as a full year
    const mtFor = new Map(fullYears.map((y) => [y.year, y.mt]));
    const cagrWindows: Record<CagrKey, number | null> = { "1yr": null, "2yr": null, "3yr": null, "5yr": null, all: null };
    if (latestYear != null && latestMt != null && latestMt > 0) {
      const cagr = (baseYear: number, w: number): number | null => {
        const baseMt = mtFor.get(baseYear);
        if (baseMt == null || baseMt <= 0 || w <= 0) return null;
        return (Math.pow(latestMt / baseMt, 1 / w) - 1) * 100;
      };
      cagrWindows["1yr"] = cagr(latestYear - 1, 1);
      cagrWindows["2yr"] = cagr(latestYear - 2, 2);
      cagrWindows["3yr"] = cagr(latestYear - 3, 3);
      cagrWindows["5yr"] = cagr(latestYear - 5, 5);
      const earliest = fullYears[0].year;
      cagrWindows.all = cagr(earliest, latestYear - earliest);
    }

    // seasonality: mean actual_mt per calendar month ÷ overall mean
    const monthSums = new Array(12).fill(0) as number[];
    const monthCounts = new Array(12).fill(0) as number[];
    let total = 0;
    for (const a of actuals) {
      const mIdx = Number(a.month.slice(5, 7)) - 1;
      if (mIdx < 0 || mIdx > 11) continue;
      monthSums[mIdx] += a.actual_mt;
      monthCounts[mIdx] += 1;
      total += a.actual_mt;
    }
    const overallMean = actuals.length ? total / actuals.length : 0;
    const seasonality = monthSums.map((s, i) =>
      overallMean > 0 && monthCounts[i] > 0 ? s / monthCounts[i] / overallMean : 0,
    );

    return { annual, fullYears, latest: latestYear, latestMt, last12Mt, cagrWindows, seasonality, price };
  }, [payload]);

  // keep growthPct in sync with the chosen window whenever the payload or window changes
  useEffect(() => {
    const v = calc?.cagrWindows[cagrKey];
    setGrowthPct(v == null ? null : Math.round(v * 100) / 100);
  }, [calc, cagrKey]);

  if (err) return <ErrorCard error={err} />;
  if (!calc) return <PageSkeleton />;

  const target12 = calc.latestMt != null ? calc.latestMt * (1 + (growthPct ?? 0) / 100) : null;
  const targetValue = target12 != null && calc.price != null ? target12 * calc.price : null;

  const sumSeasonality = calc.seasonality.reduce((a, b) => a + b, 0);

  // next 12 calendar months (starting with the current month), labeled "Mon 'YY"
  const months = (() => {
    const now = new Date();
    return Array.from({ length: 12 }, (_, i) => {
      const d = new Date(now.getFullYear(), now.getMonth() + i, 1);
      return { label: `${MONTHS[d.getMonth()]} '${String(d.getFullYear()).slice(-2)}`, idx: d.getMonth() };
    });
  })();

  // spread the 12-month target across months using historical seasonality
  const monthly = months.map((m) => {
    const target =
      target12 != null && sumSeasonality > 0
        ? Math.round((target12 * (calc.seasonality[m.idx] ?? 0)) / sumSeasonality)
        : 0;
    const value = calc.price != null ? target * calc.price : null;
    const pct = target12 != null && target12 > 0 ? (target / target12) * 100 : 0;
    return { label: m.label, target, value, pct };
  });
  const monthlyTotal = monthly.reduce((a, x) => a + x.target, 0);
  const monthlyValueTotal = monthly.reduce((a, x) => a + (x.value ?? 0), 0);

  const growthStr = growthPct == null ? "—" : `${growthPct >= 0 ? "+" : ""}${growthPct.toFixed(1)}%`;

  type Kpi = { k: string; v: string; s: string };
  const kpis: Kpi[] = [
    { k: "Latest full year (MT)", v: `${fmt(calc.latestMt)} MT`, s: calc.latest != null ? `FY ${calc.latest}` : "no full year yet" },
    { k: "Selected CAGR (%)", v: growthStr, s: `${cagrKey} CAGR` },
    { k: "Target 12-month (MT)", v: `${fmt(target12)} MT`, s: "next 12 months" },
    { k: "Target value (৳ cr)", v: `৳ ${crore(targetValue)} cr`, s: `at ৳${fmt(calc.price)} / MT` },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Demand Planning"
        subtitle="12-month sales target from the historical trend and seasonality."
        right={
          <div className="flex items-center gap-1" role="group" aria-label="SBU selector">
            {(["AIL", "ACL"] as const).map((s) => (
              <button
                key={s}
                onClick={() => setSbu(s)}
                aria-label={`Show ${s} plan`}
                aria-pressed={sbu === s}
                className={`chip cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${sbu === s ? "chip-active" : ""}`}
                style={{ outlineColor: "var(--brand)" }}
              >
                {s}
              </button>
            ))}
          </div>
        }
      />

      {/* Target levers */}
      <div className="card">
        <h2 className="section-h">
          <span className="section-bar" style={{ "--accent": "var(--brand)" } as CSSProperties} />
          Target levers
        </h2>
        <div className="mt-3 flex flex-wrap items-end gap-x-5 gap-y-3">
          <label className="text-xs" style={{ color: "var(--muted)" }}>
            Growth window
            <select
              className="input ml-2"
              value={cagrKey}
              onChange={(e) => setCagrKey(e.target.value as CagrKey)}
              aria-label="Growth window"
            >
              {CAGR_KEYS.filter((k) => calc.cagrWindows[k] != null).map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
          </label>
          <label className="text-xs" style={{ color: "var(--muted)" }}>
            Growth %
            <input
              className="input ml-2"
              type="number"
              step="0.1"
              style={{ width: 90 }}
              value={growthPct ?? ""}
              onChange={(e) => setGrowthPct(e.target.value === "" ? null : Number(e.target.value))}
              aria-label="Growth percent"
            />
          </label>
        </div>
        <p className="muted mt-2 text-xs">National-market share lever requires market data (not available).</p>
      </div>

      {/* 4-card KPI strip */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {kpis.map((x) => (
          <div key={x.k} className="kpi" style={{ "--accent": "var(--brand)" } as CSSProperties}>
            <div className="kpi-label">{x.k}</div>
            <div className="kpi-value mt-1.5" style={{ color: "var(--ink)" }}>{x.v}</div>
            <div className="kpi-sub mt-1">{x.s}</div>
          </div>
        ))}
      </div>

      {/* Annual history */}
      <div className="card">
        <h2 className="section-h">
          <span className="section-bar" style={{ "--accent": "var(--acc-history)" } as CSSProperties} />
          Annual history
        </h2>
        <div className="mt-3">
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={calc.annual} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" />
              <XAxis dataKey="year" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 11 }} />
              <YAxis stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(v) => fmt(v)} width={52} />
              <Tooltip
                formatter={(v) => [`${fmt(v as number)} MT`, "Sales"]}
                contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 10, fontSize: 12, boxShadow: "var(--shadow)" }}
                labelStyle={{ color: "var(--muted)" }}
              />
              <Bar dataKey="mt" radius={[4, 4, 0, 0]} isAnimationActive={false}>
                {calc.annual.map((a) => (
                  <Cell key={a.year} fill={a.months === 12 ? "var(--c-forecast)" : "var(--c-band)"} />
                ))}
              </Bar>
              {target12 != null && (
                <ReferenceLine y={target12} stroke="var(--acc-region)" strokeDasharray="4 4" />
              )}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* 12-month target */}
      <div className="card">
        <h2 className="section-h">
          <span className="section-bar" style={{ "--accent": "var(--acc-demand)" } as CSSProperties} />
          12-month target
        </h2>
        <div className="mt-3">
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={monthly} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" />
              <XAxis dataKey="label" stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 10 }} minTickGap={18} interval="preserveStartEnd" />
              <YAxis stroke="transparent" tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(v) => fmt(v)} width={52} />
              <Tooltip
                formatter={(v) => [`${fmt(v as number)} MT`, "Target"]}
                contentStyle={{ background: "var(--surface-1)", border: "1px solid var(--grid)", borderRadius: 10, fontSize: 12, boxShadow: "var(--shadow)" }}
                labelStyle={{ color: "var(--muted)" }}
              />
              <Legend wrapperStyle={{ fontSize: 12, color: "var(--muted)" }} />
              <Bar dataKey="target" name="Target" fill="var(--c-forecast)" isAnimationActive={false} />
              <Line dataKey="target" name="Trend" stroke="var(--c-forecast)" />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-4 overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>Month</th>
                <th className="num">Target (MT)</th>
                <th className="num">Value (৳ cr)</th>
                <th className="num">% of year</th>
              </tr>
            </thead>
            <tbody>
              {monthly.map((m) => (
                <tr key={m.label}>
                  <td>{m.label}</td>
                  <td className="num">{fmt(m.target)}</td>
                  <td className="num">৳ {crore(m.value)} cr</td>
                  <td className="num">{m.pct.toFixed(1)}%</td>
                </tr>
              ))}
              <tr>
                <td><b>Total</b></td>
                <td className="num"><b>{fmt(monthlyTotal)}</b></td>
                <td className="num"><b>৳ {crore(monthlyValueTotal)} cr</b></td>
                <td className="num"><b>{target12 != null && target12 > 0 ? "100%" : "—"}</b></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Notes */}
      <div className="card">
        <h2 className="section-h">
          <span className="section-bar" style={{ "--accent": "var(--acc-model)" } as CSSProperties} />
          Notes
        </h2>
        <ul className="mt-3 list-disc pl-5 text-sm" style={{ color: "var(--ink-2)", lineHeight: 1.7 }}>
          <li>Sales-based proxy: the target projects historical sales (MT) forward; it is not a national-market demand model.</li>
          <li>Seasonality applied: the 12-month target is spread month-by-month using the historical monthly share.</li>
          <li>No national-market/share data: market-size and market-share levers are unavailable, so the plan is volume-only.</li>
        </ul>
      </div>
    </div>
  );
}
