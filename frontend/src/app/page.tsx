import Link from "next/link";

const CARD = {
  href: "/ail-forecast",
  title: "AIL Demand Forecast",
  desc: "12-month statistical demand forecast from AIL steel sales — channel, zone and corporate top-accounts, with scenarios and planner adjustments.",
  color: "var(--brand)",
};

export default function Home() {
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
