/**
 * Director's-voice sentences for findings (system design §10.6). Every number
 * printed comes from the finding's own evidence; times come from the finding,
 * never from model text.
 */
import type { Dimension, Finding } from "../api/schema";

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const quote = (words: string[], max = 6) =>
  words.length > max ? `'${words.slice(0, max).join(" ")} …'` : `'${words.join(" ")}'`;

export function fmtRatio(r: number): string {
  return `${r.toFixed(1)}×`;
}

export function fmtTime(t: number): string {
  const m = Math.floor(t / 60);
  const s = (t % 60).toFixed(2).padStart(5, "0");
  return `${m}:${s}`;
}

export function findingHeadline(f: Finding): string {
  const e = f.evidence;
  switch (f.code) {
    case "RUSH":
    case "DRAG": {
      const r = num(e.rate_ratio);
      const verb = f.code === "RUSH" ? "rushed" : "dragged";
      if (e.scope === "whole take") {
        return `The whole take ran at ${r ? fmtRatio(r) : "a different"} the reference pace.`;
      }
      return `You ${verb} ${quote(f.words)}${r ? ` — ${fmtRatio(r)} the reference pace` : ""}.`;
    }
    case "HESITATE": {
      const ms = num(e.pause_ms);
      const next = f.words[f.words.length - 1];
      return `You stopped for ${ms ? (ms / 1000).toFixed(2) : "a long"} s before '${next ?? "the next word"}' — the reference doesn't.`;
    }
    case "MONO": {
      const sd = num(e.pitch_sd_st);
      const ref = num(e.reference_pitch_sd_st);
      return `Pitch went flat on ${quote(f.words, 4)}${sd != null && ref != null ? ` — ${sd} semitones of movement against ${ref} in the reference` : ""}.`;
    }
    case "FADE": {
      const drop = num(e.drop_db);
      return `You trailed off on ${quote(f.words)}${drop != null ? ` — ${drop} dB under your average` : ""}.`;
    }
    case "SKIP":
      return `You skipped ${quote(f.words)}.`;
    case "FILLER": {
      const kind = String(e.kind ?? "");
      if (kind === "vocalization") {
        const ms = num(e.vocalization_ms);
        return `A filler sound slipped in${ms ? ` — ${(ms / 1000).toFixed(2)} s of voice between words` : ""}.`;
      }
      if (kind.includes("repeat") && !kind.includes("filler")) return `You repeated ${quote(f.words)}.`;
      if (kind.includes("filler")) return `${quote(f.words)} crept in.`;
      return `You added ${quote(f.words)}, which isn't in the script.`;
    }
  }
}

export const DIMENSION_LABELS: Record<Dimension, string> = {
  pace: "Pace",
  pauses: "Pauses",
  pitch: "Pitch",
  volume: "Volume",
  accuracy: "Accuracy",
};

/** One-line summary for the score page: "Take 3. Pauses fixed. Pitch still flat." style. */
export function takeSummary(findings: Finding[]): string {
  if (findings.length === 0) return "Clean take. Nothing to flag against the reference.";
  const dims = [...new Set(findings.map((f) => f.dimension))].map((d) => DIMENSION_LABELS[d]);
  const n = findings.length;
  return `${n} ${n === 1 ? "note" : "notes"} from the booth: ${dims.join(", ").toLowerCase()}.`;
}
