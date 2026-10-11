import { motion, useReducedMotion } from "motion/react";
import { Fragment, memo, useMemo } from "react";
import type { AnalysisResult, Finding, WordMeasure } from "../api/schema";
import { groupReferenceByPhrase, groupTakeByPhrase } from "../lib/phrases";
import {
  buildReferenceLine,
  buildTakeLine,
  FLAW_NAMES,
  pauseLabel,
  spokenLabel,
  wordStyle,
  type LineItem,
} from "../lib/transcript";

const NEUTRAL = '"wdth" 100, "wght" 450';
const settings = (wdth: number, wght: number) => `"wdth" ${wdth}, "wght" ${wght}`;

function PauseGap({ ms, em }: { ms: number; em: number }) {
  return (
    <span aria-hidden="true" className="relative inline-block align-baseline" style={{ width: `${em}em` }}>
      <span className="absolute inset-x-1 top-1/2 border-t border-ink-2" />
      <span className="mono absolute left-1/2 top-[calc(50%+0.2em)] -translate-x-1/2 whitespace-nowrap text-[0.65rem] leading-none text-ink-2">
        {pauseLabel(ms)}
      </span>
    </span>
  );
}

/** Codes this word is the *first* word of, so a tag shows once per finding. */
function leadingCodes(word: WordMeasure, findings: Finding[], firstWordOf: Map<string, number>) {
  return findings.filter((f) => firstWordOf.get(f.id) === word.index);
}

interface WordProps {
  word: WordMeasure;
  findings: Finding[];
  tags: Finding[];
  order: number;
  active: boolean;
  selected: boolean;
  italic?: boolean;
  onSeek: (t: number) => void;
  animate: boolean;
}

const Word = memo(function Word({ word, findings, tags, order, active, selected, italic, onSeek, animate }: WordProps) {
  const s = wordStyle(word);
  const target = settings(s.wdth, s.wght);
  const flawClass = findings.length ? `flaw flaw-${findings[0]!.code}` : "";
  return (
    <>
      {s.pauseEm > 0 && <PauseGap ms={word.pause_before_ms} em={s.pauseEm} />}
      <motion.button
        type="button"
        onClick={() => onSeek(word.start)}
        aria-label={spokenLabel(word.text, word.pause_before_ms, findings)}
        aria-current={active ? "true" : undefined}
        className={`relative mx-[0.12em] inline-block px-[0.04em] align-baseline ${flawClass} ${
          italic ? "font-voice italic text-ink-2" : "font-display"
        } ${active ? "bg-ink text-paper" : ""} ${selected ? "outline outline-1 outline-offset-2 outline-rule" : ""}`}
        style={{ transform: `translateY(${s.shiftEm}em)` }}
        initial={animate ? { fontVariationSettings: NEUTRAL, opacity: 0.3 } : false}
        animate={{ fontVariationSettings: italic ? NEUTRAL : target, opacity: 1 }}
        transition={{ duration: 0.4, ease: "easeOut", delay: animate ? Math.min(order * 0.018, 1.2) : 0 }}
      >
        {word.text}
        {tags.map((f) => (
          <span key={f.id} className="mono ml-[0.15em] align-super text-[0.62rem] font-medium not-italic tracking-wider text-ink">
            {f.code}
          </span>
        ))}
      </motion.button>
    </>
  );
});

function Skipped({ item, onSeek }: { item: Extract<LineItem, { type: "skip" }>; onSeek: (t: number) => void }) {
  const f = item.findings[0];
  return (
    <button
      type="button"
      onClick={() => f && onSeek(f.start)}
      aria-label={`${item.token.display}, skipped${f ? ", skip flag" : ""}`}
      className="mx-[0.12em] inline-block font-display text-ink-2 line-through decoration-ink-2 decoration-2"
      style={{ fontVariationSettings: NEUTRAL }}
    >
      {item.token.norm}
      {f && item.token.index === f.script_span?.[0] && (
        <span className="mono ml-[0.15em] align-super text-[0.62rem] text-ink no-underline">SKIP</span>
      )}
    </button>
  );
}

export interface KineticTranscriptProps {
  result: AnalysisResult;
  takeTime: number;
  refTime: number;
  selectedFindingId: string | null;
  onSeekTake: (t: number) => void;
  onSeekReference: (t: number) => void;
  plain: boolean;
}

export function KineticTranscript({
  result,
  takeTime,
  refTime,
  selectedFindingId,
  onSeekTake,
  onSeekReference,
  plain,
}: KineticTranscriptProps) {
  const reduce = useReducedMotion() ?? false;
  const takeLine = useMemo(() => buildTakeLine(result), [result]);
  const refLine = useMemo(() => buildReferenceLine(result), [result]);
  const takeByPhrase = useMemo(() => groupTakeByPhrase(takeLine), [takeLine]);
  const refByPhrase = useMemo(() => groupReferenceByPhrase(result, refLine), [result, refLine]);
  const firstWordOf = useMemo(() => {
    const m = new Map<string, number>();
    for (const w of result.take.words) for (const id of w.finding_ids) if (!m.has(id)) m.set(id, w.index);
    return m;
  }, [result]);
  const phrases = [...new Set([...refByPhrase.keys(), ...takeByPhrase.keys()])].sort((a, b) => a - b);

  if (plain) return <PlainTranscript items={takeLine} />;

  let order = 0;
  return (
    <div className="flex flex-col">
      {phrases.map((p) => (
        <div key={p} className="border-b border-rule py-5 last:border-b-0">
          <p className="mb-1 text-[1.15rem] leading-relaxed opacity-40 sm:text-[1.35rem]" aria-label={`Reference, line ${p + 1}`}>
            <span className="label mr-3 align-middle">Ref</span>
            {(refByPhrase.get(p) ?? []).map((w) => {
              const s = wordStyle(w);
              const active = refTime >= w.start && refTime < w.end;
              return (
                <Fragment key={`r${w.index}`}>
                  {s.pauseEm > 0 && <PauseGap ms={w.pause_before_ms} em={s.pauseEm} />}
                  <button
                    type="button"
                    onClick={() => onSeekReference(w.start)}
                    aria-label={`Reference: ${spokenLabel(w.text, w.pause_before_ms, [])}`}
                    aria-current={active ? "true" : undefined}
                    className={`mx-[0.12em] inline-block font-display ${active ? "bg-ink text-paper" : ""}`}
                    style={{ fontVariationSettings: settings(s.wdth, s.wght), transform: `translateY(${s.shiftEm}em)` }}
                  >
                    {w.text}
                  </button>
                </Fragment>
              );
            })}
          </p>
          <p className="text-l leading-[1.6]" aria-label={`Your take, line ${p + 1}`}>
            <span className="label mr-3 align-middle">You</span>
            {(takeByPhrase.get(p) ?? []).map((item) => {
              if (item.type === "skip") return <Skipped key={item.key} item={item} onSeek={onSeekTake} />;
              const w = item.word;
              const active = takeTime >= w.start && takeTime < w.end;
              return (
                <Word
                  key={item.key}
                  word={w}
                  findings={item.findings}
                  tags={leadingCodes(w, item.findings, firstWordOf)}
                  order={order++}
                  active={active}
                  selected={selectedFindingId != null && w.finding_ids.includes(selectedFindingId)}
                  italic={item.type === "insert"}
                  onSeek={onSeekTake}
                  animate={!reduce}
                />
              );
            })}
          </p>
        </div>
      ))}
      <Legend />
    </div>
  );
}

function PlainTranscript({ items }: { items: LineItem[] }) {
  const text = items
    .map((item) => {
      if (item.type === "skip") return `(skipped: ${item.token.norm})`;
      const w = item.word;
      const pause = w.pause_before_ms >= 150 ? `[${(w.pause_before_ms / 1000).toFixed(2)} s pause] ` : "";
      const word = item.type === "insert" ? `[${w.text}]` : w.text;
      const flags = item.findings.length ? ` {${item.findings.map((f) => FLAW_NAMES[f.code]).join(", ")}}` : "";
      return `${pause}${word}${flags}`;
    })
    .join(" ");
  return (
    <p className="max-w-prose whitespace-pre-wrap py-5 font-voice text-body" aria-label="Plain transcript of your take">
      {text}
    </p>
  );
}

const LEGEND: Array<[string, string]> = [
  ["RUSH", "double rule"],
  ["DRAG", "dashed"],
  ["HESITATE", "dotted"],
  ["MONO", "solid"],
  ["FADE", "thin dash"],
  ["FILLER", "wave"],
  ["SKIP", "struck through"],
];

function Legend() {
  return (
    <div className="label mt-4 flex flex-wrap gap-x-5 gap-y-2 text-ink-2" aria-label="How to read the transcript">
      <span>Narrow = faster · wide = slower · heavy = louder · thin = quieter · raised = higher</span>
      {LEGEND.map(([code, pattern]) => (
        <span key={code} className="inline-flex items-baseline gap-1">
          <span className={`flaw flaw-${code} font-display normal-case tracking-normal text-ink`}>abc</span>
          {code} {pattern}
        </span>
      ))}
    </div>
  );
}
