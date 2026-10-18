"use client";
import { useEffect, useState, type CSSProperties } from "react";
import Link from "next/link";
import { apiGet, fmt } from "@/lib/api";

type FPoint = { month: string; horizon: number; point: number };
type UIPayload = {
  champion?: string | null;
  value_summary?: { currency: string; price_per_mt: number; forecast_value_12m: number; last12_value: number };
  holdout?: { wape_all?: number };
  series?: { series_id: string; level: string }[];
  detail?: Record<string, { forecasts?: { base?: FPoint[] } }>;
};

// crore = 10,000,000 (1e7)
const crore = (v?: number | null): string =>
  v == null ? "—" : (v / 1e7).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

type SBUId = "AIL" | "ACL";

const SBUS: { id: SBUId; label: string; industry: string; desc: string; href: string; accent: string }[] = [
  {
    id: "AIL",
    label: "AIL · Anwar Ispat Ltd.",
    industry: "steel",
    desc: "12-month statistical steel demand forecast — channel, zone and corporate totals with scenarios and planner adjustments.",
    href: "/ail-forecast/?sbu=AIL",
    accent: "var(--acc-demand)",
  },
  {
    id: "ACL",
    label: "ACL · Anwar Cement Ltd.",
    industry: "cement",
    desc: "12-month statistical cement demand forecast — channel, zone and corporate totals with scenarios and planner adjustments.",
    href: "/ail-forecast/?sbu=ACL",
    accent: "var(--acc-region)",
  },
];

// derive the four headline metrics from a payload; company 12m forecast = sum of detail[company].forecasts.base[].point
function metricsFor(d: UIPayload | null, sbu: SBUId) {
  const companyId = d?.series?.find((s) => s.level === "company")?.series_id ?? `${sbu}|company`;
  const companyFc = d?.detail?.[companyId]?.forecasts?.base?.reduce((a, f) => a + f.point, 0) ?? null;
  return {
    companyFc,
    value: d?.value_summary?.forecast_value_12m ?? null,
    champion: d?.champion ?? null,
    wape: d?.holdout?.wape_all ?? null,
  };
}

export default function Home() {
  const [sbu, setSbu] = useState<SBUId>("AIL");
  const [data, setData] = useState<{ AIL: UIPayload | null; ACL: UIPayload | null }>({ AIL: null, ACL: null });

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      apiGet<UIPayload>("/forecast/ui").catch(() => null),
      apiGet<UIPayload>("/forecast/acl").catch(() => null),
    ]).then(([AIL, ACL]) => {
      if (!cancelled) setData({ AIL, ACL });
    });
    return () => { cancelled = true; };
  }, []);

  const sel = metricsFor(data[sbu], sbu);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold" style={{ color: "var(--ink)" }}>
            Demand Forecast — AIL & ACL
          </h1>
          <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
            12-month statistical demand forecast for Anwar Ispat (steel) and Anwar Cement (cement).
          </p>
        </div>
        <div className="flex items-center gap-1" role="group" aria-label="SBU selector">
          {(["AIL", "ACL"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSbu(s)}
              aria-label={`Show ${s} forecast`}
              aria-pressed={sbu === s}
              className={`chip cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${sbu === s ? "chip-active" : ""}`}
              style={{ outlineColor: "var(--brand)" }}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <div className="kpi" style={{ "--accent": "var(--acc-demand)" } as CSSProperties}>
          <div className="kpi-label">12-Month Forecast</div>
          <div className="kpi-value mt-1.5" style={{ color: "var(--ink)" }}>{sel.companyFc == null ? "—" : `${fmt(sel.companyFc)} MT`}</div>
          <div className="kpi-sub mt-1">{sbu === "ACL" ? "MT cement" : "MT steel"}</div>
        </div>
        <div className="kpi" style={{ "--accent": "var(--acc-demand)" } as CSSProperties}>
          <div className="kpi-label">Forecast Value</div>
          <div className="kpi-value mt-1.5" style={{ color: "var(--ink)" }}>{sel.value == null ? "—" : `৳ ${crore(sel.value)} cr`}</div>
          <div className="kpi-sub mt-1">12-month value</div>
        </div>
        <div className="kpi" style={{ "--accent": "var(--acc-demand)" } as CSSProperties}>
          <div className="kpi-label">Model</div>
          <div className="kpi-value mt-1.5" style={{ color: "var(--ink)" }}>{sel.champion ?? "—"}</div>
          <div className="kpi-sub mt-1">champion</div>
        </div>
        <div className="kpi" style={{ "--accent": "var(--acc-demand)" } as CSSProperties}>
          <div className="kpi-label">Holdout WAPE</div>
          <div className="kpi-value mt-1.5" style={{ color: "var(--ink)" }}>{sel.wape == null ? "—" : `${(sel.wape * 100).toFixed(1)}%`}</div>
          <div className="kpi-sub mt-1">holdout</div>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {SBUS.map((s) => {
          const m = metricsFor(data[s.id], s.id);
          const selected = sbu === s.id;
          return (
            <Link
              key={s.id}
              href={s.href}
              className="card card-hover relative block overflow-hidden focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
              style={{
                outlineColor: "var(--brand)",
                borderColor: `color-mix(in srgb, ${s.accent} ${selected ? 50 : 30}%, var(--grid))`,
                background: selected ? `color-mix(in srgb, ${s.accent} 6%, var(--surface-1))` : undefined,
              }}
            >
              <span
                aria-hidden
                style={{ position: "absolute", top: 0, left: 0, right: 0, height: 3, background: s.accent }}
              />
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: s.accent }}>
                    {s.label} <span style={{ color: "var(--muted)", fontWeight: 500, textTransform: "none" }}>({s.industry})</span>
                  </div>
                  <p className="mt-1.5 text-sm" style={{ color: "var(--muted)" }}>{s.desc}</p>
                </div>
                <span className="shrink-0 text-sm font-semibold" style={{ color: s.accent }}>open →</span>
              </div>
              <div className="mt-3 text-lg font-semibold" style={{ color: "var(--ink)", fontVariantNumeric: "tabular-nums" }}>
                {m.companyFc == null ? "—" : `${fmt(m.companyFc)} MT`} · ৳{crore(m.value)} cr
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
