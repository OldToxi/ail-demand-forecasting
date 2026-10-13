"use client";
import { useEffect, useState, type CSSProperties } from "react";
import Link from "next/link";
import { apiGet, fmt } from "@/lib/api";

type FPoint = { month: string; horizon: number; point: number };
type UIPayload = {
  champion?: string | null;
  value_summary?: { currency: string; price_per_mt: number; forecast_value_12m: number; last12_value: number };
  holdout?: { wape_all?: number };
  detail?: Record<string, { forecasts?: { base?: FPoint[] } }>;
};

const CARD = {
  href: "/ail-forecast",
  title: "AIL Demand Forecast",
  desc: "12-month statistical demand forecast from AIL steel sales — channel, zone and corporate top-accounts, with scenarios and planner adjustments.",
  color: "var(--brand)",
};

// crore = 10,000,000 (1e7)
const crore = (v?: number | null): string =>
  v == null ? "—" : (v / 1e7).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export default function Home() {
  const [data, setData] = useState<UIPayload | null>(null);

  useEffect(() => {
    apiGet<UIPayload>("/forecast/ui").then(setData).catch(() => setData(null));
  }, []);

  const companyFc =
    data?.detail?.["AIL|company"]?.forecasts?.base?.reduce((a, f) => a + f.point, 0) ?? null;
  const value = data?.value_summary?.forecast_value_12m ?? null;
  const champion = data?.champion ?? null;
  const wape = data?.holdout?.wape_all ?? null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold" style={{ color: "var(--ink)" }}>
          AIL Demand Forecast
        </h1>
        <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
          AIL demand forecasting — 12-month steel sales-based forecast with scenarios and planner adjustments.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <div className="kpi" style={{ "--accent": "var(--acc-demand)" } as CSSProperties}>
          <div className="kpi-label">12-Month Forecast</div>
          <div className="kpi-value mt-1.5" style={{ color: "var(--ink)" }}>{companyFc == null ? "—" : `${fmt(companyFc)} MT`}</div>
          <div className="kpi-sub mt-1">MT steel</div>
        </div>
        <div className="kpi" style={{ "--accent": "var(--acc-demand)" } as CSSProperties}>
          <div className="kpi-label">Forecast Value</div>
          <div className="kpi-value mt-1.5" style={{ color: "var(--ink)" }}>{value == null ? "—" : `৳ ${crore(value)} cr`}</div>
          <div className="kpi-sub mt-1">12-month value</div>
        </div>
        <div className="kpi" style={{ "--accent": "var(--acc-demand)" } as CSSProperties}>
          <div className="kpi-label">Model</div>
          <div className="kpi-value mt-1.5" style={{ color: "var(--ink)" }}>{champion ?? "—"}</div>
          <div className="kpi-sub mt-1">champion</div>
        </div>
        <div className="kpi" style={{ "--accent": "var(--acc-demand)" } as CSSProperties}>
          <div className="kpi-label">Holdout WAPE</div>
          <div className="kpi-value mt-1.5" style={{ color: "var(--ink)" }}>{wape == null ? "—" : `${(wape * 100).toFixed(1)}%`}</div>
          <div className="kpi-sub mt-1">holdout</div>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Link
          key={CARD.href}
          href={CARD.href}
          className="card card-hover block"
          style={{ borderColor: `color-mix(in srgb, ${CARD.color} 35%, var(--grid))` }}
        >
          <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: CARD.color }}>
            open
          </div>
          <div className="mt-1 text-lg font-semibold" style={{ color: "var(--ink)" }}>{CARD.title}</div>
          <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>{CARD.desc}</p>
        </Link>
      </div>
    </div>
  );
}
