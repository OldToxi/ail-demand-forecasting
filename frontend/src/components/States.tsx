import type { CSSProperties } from "react";

// shimmer block — size it with style/className
export function Skeleton({ className = "", style }: { className?: string; style?: CSSProperties }) {
  return <div className={`skeleton ${className}`} style={{ height: 16, ...style }} aria-hidden />;
}

// generic full-page loading placeholder (title + a few blocks)
export function PageSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true">
      <Skeleton style={{ height: 26, width: "38%" }} />
      <div className="grid grid-cols-3 gap-4">
        {[0, 1, 2].map((i) => <Skeleton key={i} style={{ height: 76 }} />)}
      </div>
      <Skeleton style={{ height: 300 }} />
    </div>
  );
}

// friendly, product-facing error card — no dev/backend/port wording
export function ErrorCard({ error }: { error?: string }) {
  return (
    <div className="card" style={{ borderColor: "color-mix(in srgb, var(--crit) 40%, var(--grid))" }}>
      <div className="font-medium" style={{ color: "var(--crit)" }}>Couldn&apos;t load this data</div>
      <p className="mt-1 text-sm" style={{ color: "var(--ink-2)" }}>
        Please refresh the page. If it keeps happening, this view&apos;s data may still be publishing —
        try again in a moment.
      </p>
      {error && <p className="mt-2 text-xs" style={{ color: "var(--muted)" }}>{error}</p>}
    </div>
  );
}
