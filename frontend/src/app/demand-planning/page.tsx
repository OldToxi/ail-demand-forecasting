"use client";
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, ComposedChart, Line, Legend } from "recharts";
import { apiGet, fmt } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { ErrorCard, PageSkeleton } from "@/components/States";

// ── Types ────────────────────────────────────────────────────────
type Act = { month: string; actual_mt: number; actual_value?: number; provisional?: boolean; constrained?: boolean };
type CompanyDetail = { actuals: Act[]; forecasts?: { base?: { month: string; point: number; value?: number }[] } };
type UIPayload = {
  value_summary?: { currency: string; price_per_mt: number; forecast_value_12m: number; last12_value: number };
  series: { series_id: string; level: string; channel?: string; zone?: string; label?: string }[];
  detail: Record<string, CompanyDetail>;
};
type BomMaterial = { id: string; name: string; mix_pct: number; kg_per_mt_steel: number; rate: number; stock_mt: number };
type Bom = {
  sbu: string; as_of: string; currency: string;
  steel_per_bar: number; metallic_yield: number;
  charge_kg_per_mt_steel: number; material_cost_per_mt_steel: number;
  materials: BomMaterial[];
  energy: { name: string; value: number; unit: string }[];
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
  const [basis, setBasis] = useState<"forecast" | "trend">("forecast");
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

  const [bom, setBom] = useState<Bom | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiGet<Bom>("/forecast/bom")
      .then((b) => { if (!cancelled) setBom(b); })
      .catch(() => { if (!cancelled) setBom(null); });
    return () => { cancelled = true; };
  }, []);

  const fcPlan = useMemo(() => {
    if (!payload) return [] as { label: string; idx: number; target: number; value: number | null }[];
    const company = payload.series.find((s) => s.level === "company");
    const det = company ? payload.detail[company.series_id] : undefined;
    return (det?.forecasts?.base ?? []).map((p) => ({
      label: `${MONTHS[Number(p.month.slice(5, 7)) - 1]} '${p.month.slice(2, 4)}`,
      idx: Number(p.month.slice(5, 7)) - 1,
      target: Math.round(p.point),
      value: p.value ?? null,
    }));
  }, [payload]);

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

  const trendTarget = calc.latestMt != null ? calc.latestMt * (1 + (growthPct ?? 0) / 100) : null;
  const sumSeasonality = calc.seasonality.reduce((a, b) => a + b, 0);

  // next 12 calendar months (starting with the current month), labeled "Mon 'YY"
  const months = (() => {
    const now = new Date();
    return Array.from({ length: 12 }, (_, i) => {
      const d = new Date(now.getFullYear(), now.getMonth() + i, 1);
      return { label: `${MONTHS[d.getMonth()]} '${String(d.getFullYear()).slice(-2)}`, idx: d.getMonth() };
    });
  })();

  const useFc = basis === "forecast" && fcPlan.length > 0;

  // monthly bar plan: model forecast, or the trend target spread by historical seasonality
  const monthlyBase = useFc
    ? fcPlan
    : months.map((m) => ({
        label: m.label,
        idx: m.idx,
        target:
          trendTarget != null && sumSeasonality > 0
            ? Math.round((trendTarget * (calc.seasonality[m.idx] ?? 0)) / sumSeasonality)
            : 0,
        value: null as number | null,
      }));
  const monthlyTotal = monthlyBase.reduce((a, x) => a + x.target, 0);
  const target12 = monthlyTotal;
  const monthly = monthlyBase.map((x) => ({
    ...x,
    pct: monthlyTotal > 0 ? (x.target / monthlyTotal) * 100 : 0,
  }));
  const monthlyValueTotal = monthly.reduce(
    (a, x) => a + (x.value ?? (calc.price != null ? x.target * calc.price : 0)),
    0,
  );
  const targetValue = monthlyValueTotal;
  const impliedGrowth = calc.latestMt ? (monthlyTotal / calc.latestMt - 1) * 100 : null;

  const matRows = bom && sbu === "AIL"
    ? (() => {
        const planBar = monthlyTotal;
        const steel = planBar * bom.steel_per_bar;
        const rows = bom.materials.map((m) => {
          const need = (steel * m.kg_per_mt_steel) / 1000;
          const cover = need > 0 ? m.stock_mt / (need / 365) : null;
          const buy = Math.max(0, need - m.stock_mt);
          return { ...m, need, cover, buy, spend: buy * m.rate };
        });
        const spend = rows.reduce((a, r) => a + r.spend, 0);
        const covers = rows.map((r) => r.cover).filter((c): c is number => c != null);
        return { planBar, steel, rows, spend, minCover: covers.length ? Math.min(...covers) : 0 };
      })()
    : null;

  const growthStr = growthPct == null ? "—" : `${growthPct >= 0 ? "+" : ""}${growthPct.toFixed(1)}%`;
  const impliedStr = impliedGrowth == null ? "—" : `${impliedGrowth >= 0 ? "+" : ""}${impliedGrowth.toFixed(1)}%`;

  type Kpi = { k: string; v: string; s: string };
  const kpis: Kpi[] = [
    { k: "Latest full year (MT)", v: `${fmt(calc.latestMt)} MT`, s: calc.latest != null ? `FY ${calc.latest}` : "no full year yet" },
    { k: useFc ? "Implied growth vs FY" : "Selected CAGR (%)", v: useFc ? impliedStr : growthStr, s: useFc ? "model forecast vs FY" : `${cagrKey} CAGR` },
    { k: "Target 12-month (MT)", v: `${fmt(target12)} MT`, s: useFc ? "model forecast (base)" : "next 12 months" },
    { k: "Target value (৳ cr)", v: `৳ ${crore(targetValue)} cr`, s: `at ৳${fmt(calc.price)} / MT` },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Demand Planning"
        subtitle={basis === "forecast" ? "12-month plan from the statistical model forecast (base scenario)." : "12-month sales target from the historical trend and seasonality."}
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
          <div className="text-xs" style={{ color: "var(--muted)" }}>
            Plan basis
            <div className="mt-1 flex items-center gap-1" role="group" aria-label="Plan basis">
              {(["forecast", "trend"] as const).map((b) => (
                <button
                  key={b}
                  onClick={() => setBasis(b)}
                  aria-pressed={basis === b}
                  className={`chip cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${basis === b ? "chip-active" : ""}`}
                  style={{ outlineColor: "var(--brand)" }}
                >
                  {b === "forecast" ? "Forecast (model)" : "Trend growth"}
                </button>
              ))}
            </div>
          </div>
          {basis === "trend" && (
            <>
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
            </>
          )}
        </div>
        <p className="muted mt-2 text-xs">
          {basis === "forecast"
            ? "Monthly plan = statistical model forecast (base scenario) for the next 12 months."
            : "Trend plan spreads the target by historical seasonality; the market-share lever needs market data (not available)."}
        </p>
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

      {sbu === "AIL" && bom && matRows && (
        <div className="card">
          <h2 className="section-h">
            <span className="section-bar" style={{ "--accent": "var(--acc-model)" } as CSSProperties} />
            Raw-material plan (BOM)
          </h2>
          <p className="muted mt-1 text-xs">
            Converts the 12-month bar plan above into steel and raw-material need using the AIL Oct-2026 BOM.
          </p>
          <div className="mt-3 grid grid-cols-2 gap-4 md:grid-cols-4">
            {[
              { k: "Bar plan (MT)", v: fmt(matRows.planBar) },
              { k: "Steel required (MT)", v: fmt(matRows.steel) },
              { k: "Material purchase (৳ cr)", v: `৳ ${crore(matRows.spend)}` },
              { k: "Tightest stock cover", v: `${matRows.minCover.toFixed(1)} d` },
            ].map((x) => (
              <div key={x.k} className="kpi" style={{ "--accent": "var(--acc-model)" } as CSSProperties}>
                <div className="kpi-label">{x.k}</div>
                <div className="kpi-value mt-1.5" style={{ color: "var(--ink)" }}>{x.v}</div>
              </div>
            ))}
          </div>
          <div className="mt-4 overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Material</th>
                  <th className="num">kg / MT steel</th>
                  <th className="num">12m need (MT)</th>
                  <th className="num">Stock (MT)</th>
                  <th className="num">Cover (days)</th>
                  <th className="num">Buy (MT)</th>
                  <th className="num">Spend (৳ cr)</th>
                </tr>
              </thead>
              <tbody>
                {matRows.rows.map((r) => (
                  <tr key={r.id}>
                    <td>{r.name}</td>
                    <td className="num">{fmt(r.kg_per_mt_steel, 1)}</td>
                    <td className="num">{fmt(r.need)}</td>
                    <td className="num">{fmt(r.stock_mt)}</td>
                    <td className="num" style={{ color: r.cover != null && r.cover < 7 ? "var(--crit)" : undefined }}>
                      {r.cover == null ? "—" : r.cover.toFixed(1)}
                    </td>
                    <td className="num">{fmt(r.buy)}</td>
                    <td className="num">৳ {crore(r.spend)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted mt-2 text-xs">
            Norms: {bom.steel_per_bar.toFixed(4)} MT steel / MT bar, {fmt(bom.charge_kg_per_mt_steel)} kg charge / MT steel. Stock as of {bom.as_of}; buy assumes no receipts or safety stock. Cover under 7 days is red.
          </p>
        </div>
      )}

      {/* Notes */}
      <div className="card">
        <h2 className="section-h">
          <span className="section-bar" style={{ "--accent": "var(--acc-model)" } as CSSProperties} />
          Notes
        </h2>
        <ul className="mt-3 list-disc pl-5 text-sm" style={{ color: "var(--ink-2)", lineHeight: 1.7 }}>
          <li>
            Volume plan:{" "}
            {basis === "forecast"
              ? "the monthly plan is the statistical model forecast (base scenario)"
              : "the target projects historical sales forward using trend and seasonality"}
            ; it is not a national-market demand model.
          </li>
          <li>Seasonality applied: the 12-month target is spread month-by-month using the historical monthly share.</li>
          <li>No national-market/share data: market-size and market-share levers are unavailable, so the plan is volume-only.</li>
        </ul>
      </div>
    </div>
  );
}
