/**
 * The kinetic transcript's model (system design §10.3). Pure functions only:
 * every typographic property is computed from a measurement, so the type is
 * the evidence.
 */
import type { AnalysisResult, Finding, FlawCode, ScriptToken, WordMeasure } from "../api/schema";

export type LineItem =
  | { type: "word"; key: string; word: WordMeasure; token: ScriptToken | null; findings: Finding[] }
  | { type: "insert"; key: string; word: WordMeasure; findings: Finding[] }
  | { type: "skip"; key: string; token: ScriptToken; findings: Finding[] };

const byId = (findings: Finding[]) => new Map(findings.map((f) => [f.id, f]));

function findingsFor(word: WordMeasure, index: Map<string, Finding>): Finding[] {
  return word.finding_ids.map((id) => index.get(id)).filter((f): f is Finding => Boolean(f));
}

/**
 * Walk the alignment in order so the take reads like the script it performed:
 * matched words in place, insertions where they were said, and skipped script
 * words where they should have been.
 */
export function buildTakeLine(result: AnalysisResult): LineItem[] {
  const index = byId(result.findings);
  const skips = result.findings.filter((f) => f.code === "SKIP" && f.script_span);
  const items: LineItem[] = [];
  result.alignment.forEach((op, i) => {
    if ((op.op === "match" || op.op === "sub") && op.take_index != null) {
      const word = result.take.words[op.take_index];
      if (!word) return;
      const token = op.script_index != null ? (result.script.tokens[op.script_index] ?? null) : null;
      items.push({ type: "word", key: `w${word.index}`, word, token, findings: findingsFor(word, index) });
    } else if (op.op === "ins" && op.take_index != null) {
      const word = result.take.words[op.take_index];
      if (!word) return;
      items.push({ type: "insert", key: `i${word.index}`, word, findings: findingsFor(word, index) });
    } else if (op.op === "del" && op.script_index != null) {
      const token = result.script.tokens[op.script_index];
      if (!token) return;
      const covering = skips.filter(
        (f) => f.script_span && f.script_span[0] <= token.index && token.index <= f.script_span[1],
      );
      items.push({ type: "skip", key: `d${token.index}-${i}`, token, findings: covering });
    }
  });
  return items;
}

/** The reference take, in spoken order, matched to the script. */
export function buildReferenceLine(result: AnalysisResult): WordMeasure[] {
  return [...result.reference.words].sort((a, b) => a.start - b.start);
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export interface WordStyle {
  /** Archivo width axis: rushed words condense, dragged words expand. */
  wdth: number;
  /** Archivo weight axis: loud is heavy, fading is hairline. */
  wght: number;
  /** Baseline shift in em from pitch (semitones from the speaker's median). */
  shiftEm: number;
  /** Leading space in em proportional to the pause before the word. */
  pauseEm: number;
}

export const PAUSE_LABEL_MIN_MS = 150;

export function wordStyle(word: Pick<WordMeasure, "rate_ratio" | "loudness_db" | "pitch_st" | "pause_before_ms">): WordStyle {
  const r = word.rate_ratio ?? 1;
  const db = word.loudness_db ?? 0;
  const st = word.pitch_st ?? 0;
  const ms = word.pause_before_ms ?? 0;
  return {
    wdth: Math.round(clamp(100 - (r - 1) * 90, 62, 125)),
    wght: Math.round(clamp(450 + db * 45, 100, 900)),
    shiftEm: Number(clamp(-st * 0.025, -0.15, 0.15).toFixed(3)),
    pauseEm: ms >= PAUSE_LABEL_MIN_MS ? Number(Math.min((ms / 1000) * 1.6, 6).toFixed(2)) : 0,
  };
}

export const FLAW_NAMES: Record<FlawCode, string> = {
  RUSH: "rushed",
  DRAG: "dragged",
  HESITATE: "hesitation",
  MONO: "monotone",
  FADE: "trailing off",
  SKIP: "skipped",
  FILLER: "filler",
};

export function pauseLabel(ms: number): string {
  return `${(ms / 1000).toFixed(2)}s`;
}

/** Screen-reader text: "deadline, 0.97 second pause, hesitation flag". */
export function spokenLabel(text: string, pauseMs: number, findings: Finding[]): string {
  const parts = [text];
  if (pauseMs >= PAUSE_LABEL_MIN_MS) parts.push(`${(pauseMs / 1000).toFixed(2)} second pause`);
  for (const f of findings) parts.push(`${FLAW_NAMES[f.code]} flag`);
  return parts.join(", ");
}

/** Index of the word sounding at time t (or -1). */
export function wordAt(words: Pick<WordMeasure, "start" | "end">[], t: number): number {
  for (let i = 0; i < words.length; i++) {
    const w = words[i]!;
    if (t >= w.start && t < w.end) return i;
  }
  return -1;
}
