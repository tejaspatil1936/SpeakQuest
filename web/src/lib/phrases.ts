import type { AnalysisResult, WordMeasure } from "../api/schema";
import type { LineItem } from "./transcript";

/** Step through findings with ←/→; clamps at both ends. */
export function stepFinding(current: number, delta: number, count: number): number {
  if (count === 0) return -1;
  if (current < 0) return delta > 0 ? 0 : count - 1;
  return Math.min(count - 1, Math.max(0, current + delta));
}

/**
 * Assign each item to a script phrase so the reference and the take can be
 * set line by line, like a score above its performance. Insertions belong to
 * the phrase of the word before them.
 */
export function groupTakeByPhrase(items: LineItem[]): Map<number, LineItem[]> {
  const out = new Map<number, LineItem[]>();
  let phrase = 0;
  const firstKnown = items.find((i) => i.type !== "insert");
  if (firstKnown) phrase = firstKnown.type === "skip" ? firstKnown.token.phrase : (firstKnown.token?.phrase ?? 0);
  for (const item of items) {
    if (item.type === "word" && item.token) phrase = item.token.phrase;
    if (item.type === "skip") phrase = item.token.phrase;
    const list = out.get(phrase) ?? [];
    list.push(item);
    out.set(phrase, list);
  }
  return out;
}

export function groupReferenceByPhrase(result: AnalysisResult, words: WordMeasure[]): Map<number, WordMeasure[]> {
  const out = new Map<number, WordMeasure[]>();
  let phrase = 0;
  for (const w of words) {
    if (w.script_index != null) phrase = result.script.tokens[w.script_index]?.phrase ?? phrase;
    const list = out.get(phrase) ?? [];
    list.push(w);
    out.set(phrase, list);
  }
  return out;
}
