import Link from "next/link";

const TABS = [
  {
    href: "/demand-forecast-planning",
    title: "Demand Forecast",
    desc: "12-month statistical forecast — national demand, raw materials, districts and day-wise dispatch.",
    color: "var(--s1)",
  },
  {
    href: "/demand-planning",
    title: "Demand Planning",
    desc: "Top-down CAGR sales target — national market × ACCL share, then required production and trucks.",
    color: "var(--s3)",
  },
  {
    href: "/production",
    title: "Production Planning",
    desc: "What to produce and buy — clinker + raw materials exploded through the cement BOM.",
    color: "var(--s2)",
  },
];

export default function Home() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold" style={{ color: "var(--ink)" }}>
          Demand &amp; Production Planning
        </h1>
        <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
          One integrated system: demand forecast → demand planning target → production material plan.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {TABS.map((t) => (
          <Link
            key={t.href}
            href={t.href}
            className="card card-hover block"
            style={{ borderColor: `color-mix(in srgb, ${t.color} 35%, var(--grid))` }}
          >
            <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: t.color }}>
              open
            </div>
            <div className="mt-1 text-lg font-semibold" style={{ color: "var(--ink)" }}>{t.title}</div>
            <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>{t.desc}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
