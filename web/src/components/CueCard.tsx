import type { ReactNode } from "react";
import type { Challenge } from "../api/schema";

export const DIFFICULTY = { 1: "Warm-up", 2: "Standard", 3: "Hard" } as const;

/** Index-card frame: rounded corners, a punch hole, a ruled header. */
export function CardFrame({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`relative rounded-card border border-rule bg-paper ${className}`}>
      <span
        aria-hidden="true"
        className="absolute left-4 top-4 h-3.5 w-3.5 rounded-full border border-rule"
        style={{ boxShadow: "inset 0 1px 0 var(--ink-2)" }}
      />
      {children}
    </div>
  );
}

export function CueMeta({ challenge, number }: { challenge: Challenge; number?: number }) {
  return (
    <div className="label flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-rule py-3 pl-12 pr-4">
      {number !== undefined && <span>No. {String(number).padStart(2, "0")}</span>}
      <span>
        Difficulty {challenge.difficulty}/3 · {DIFFICULTY[challenge.difficulty]}
      </span>
      <span className="text-ink-2">Listen for: {challenge.flaw_targets.join(" · ")}</span>
      {challenge.reference_duration_s != null && (
        <span className="ml-auto text-ink-2">Ref {challenge.reference_duration_s.toFixed(1)} s</span>
      )}
    </div>
  );
}
