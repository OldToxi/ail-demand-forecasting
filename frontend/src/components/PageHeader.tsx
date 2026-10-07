import type { ReactNode } from "react";

// One consistent page title block for every page (title + optional subtitle + optional right-side controls).
export default function PageHeader({
  title,
  subtitle,
  right,
}: {
  title: string;
  subtitle?: ReactNode;
  right?: ReactNode;
}) {
  return (
    <div className="mb-1 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold" style={{ color: "var(--ink)" }}>{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm" style={{ color: "var(--muted)" }}>{subtitle}</p>}
      </div>
      {right && <div className="flex flex-wrap items-center gap-3">{right}</div>}
    </div>
  );
}
