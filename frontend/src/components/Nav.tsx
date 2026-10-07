"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/demand-forecast-planning", label: "Demand Forecast" },
  { href: "/demand-planning", label: "Demand Planning" },
  { href: "/production", label: "Production Planning" },
  { href: "/ail-forecast", label: "AIL Forecast" },
];

export default function Nav() {
  const path = usePathname();
  return (
    <nav
      className="sticky top-0 z-10 border-b px-4 py-2.5"
      style={{ background: "var(--surface-1)", borderColor: "var(--grid)", boxShadow: "var(--shadow)" }}
    >
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-2 gap-y-2 md:gap-x-3">
        <Link href="/" className="mr-1 font-semibold" style={{ color: "var(--ink)" }}>
          {process.env.NEXT_PUBLIC_APP_TITLE ?? "Demand & Production Planning"}
        </Link>
        {links.map((l) => {
          const active = path?.startsWith(l.href);
          return (
            <Link
              key={l.href}
              href={l.href}
              className="rounded-full px-3 py-1 text-sm transition"
              style={{
                color: active ? "#fff" : "var(--ink-2)",
                background: active ? "var(--s1)" : "transparent",
                fontWeight: active ? 600 : 400,
              }}
            >
              {l.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
