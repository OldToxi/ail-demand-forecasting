"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/ail-forecast", label: "AIL Forecast" },
];

export default function Nav() {
  const path = usePathname();
  return (
    <nav
      className="sticky top-0 z-10 px-4 py-2.5"
      style={{ background: "var(--surface-1)", borderBottom: "1px solid var(--grid)" }}
    >
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-2 gap-y-2 md:gap-x-3">
        <Link
          href="/"
          className="mr-1 font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          style={{ color: "var(--ink)", outlineColor: "var(--brand)" }}
        >
          {process.env.NEXT_PUBLIC_APP_TITLE ?? "AIL Demand Forecast"}
        </Link>
        {links.map((l) => {
          const active = path?.startsWith(l.href);
          return (
            <Link
              key={l.href}
              href={l.href}
              className="rounded-full px-3 py-1 text-sm transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
              style={{
                color: active ? "#fff" : "var(--ink-2)",
                background: active ? "var(--brand)" : "transparent",
                fontWeight: active ? 600 : 400,
                outlineColor: "var(--brand)",
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
