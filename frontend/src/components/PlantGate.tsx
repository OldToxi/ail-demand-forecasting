"use client";
import type { ReactNode } from "react";

// The 🏭 ACCL plant-picker step, matching the Production page. Pages start gated: nothing shows until the
// user clicks the plant. `entered` = has the user picked a plant; `onEnter` opens it. Single-plant for now
// (ACCL), but rendered as a list so more plants drop in later.
export function PlantPicker({ label = "Akij Cement Company Ltd.", subtitle, onEnter }: {
  label?: string; subtitle: string; onEnter: () => void;
}) {
  return (
    <div className="card">
      <div className="font-medium" style={{ borderLeft: "3px solid var(--s1)", paddingLeft: 8 }}>Select a plant</div>
      <div className="mb-3 text-xs" style={{ color: "var(--muted)" }}>{subtitle}</div>
      <div className="flex flex-wrap gap-3">
        <button
          onClick={onEnter}
          className="flex items-center gap-3 rounded-xl border px-5 py-4 text-left transition hover:-translate-y-0.5 hover:shadow-sm"
          style={{ borderColor: "color-mix(in srgb, var(--s1) 35%, var(--grid))", background: "color-mix(in srgb, var(--s1) 6%, var(--surface-1))" }}
        >
          <span className="flex h-11 w-11 items-center justify-center rounded-xl text-xl"
                style={{ background: "color-mix(in srgb, var(--s1) 14%, transparent)" }}>🏭</span>
          <span>
            <span className="block font-semibold" style={{ color: "var(--ink)" }}>{label}</span>
            <span className="block text-xs" style={{ color: "var(--muted)" }}>open →</span>
          </span>
        </button>
      </div>
    </div>
  );
}

// the "↺ change plant" chip for the page header once entered
export function ChangePlantChip({ onExit }: { onExit: () => void }) {
  return (
    <button className="chip" onClick={onExit} title="Back to plant selection">↺ change plant</button>
  );
}

export function Gate({ entered, picker, children }: { entered: boolean; picker: ReactNode; children: ReactNode }) {
  return <>{entered ? children : picker}</>;
}
