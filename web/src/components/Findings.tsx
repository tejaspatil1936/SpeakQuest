import { useEffect, useRef } from "react";
import type { Coaching, CoachingItem, Finding } from "../api/schema";
import { findingHeadline, fmtTime } from "../lib/copy";

function Evidence({ evidence }: { evidence: Finding["evidence"] }) {
  return (
    <dl className="mono mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[0.8rem] text-ink-2">
      {Object.entries(evidence).map(([k, v]) => (
        <div key={k} className="flex gap-1">
          <dt>{k.replace(/_/g, " ")}</dt>
          <dd className="text-ink">{String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function Coach({ item }: { item: CoachingItem }) {
  return (
    <div className="mt-4 border-l border-rule pl-4">
      <p className="voice text-[1.2rem] leading-snug">{item.headline}</p>
      <p className="mt-1 font-voice">{item.why}</p>
      <p className="mt-2 font-voice">
        <span className="label mr-2 not-italic">Drill</span>
        <span className="italic">{item.drill}</span>
      </p>
    </div>
  );
}

export function FindingsPanel({
  findings,
  coaching,
  selected,
  onSelect,
}: {
  findings: Finding[];
  coaching: Coaching | null | undefined;
  selected: number;
  onSelect: (index: number) => void;
}) {
  const items = new Map((coaching?.items ?? []).map((i) => [i.finding_id, i]));
  const refs = useRef<Array<HTMLLIElement | null>>([]);

  useEffect(() => {
    refs.current[selected]?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [selected]);

  if (findings.length === 0) {
    return (
      <p className="voice py-6 text-l">
        Nothing to flag. Pace, pauses, pitch, volume and wording all held up against the reference.
      </p>
    );
  }

  return (
    <ol className="flex flex-col" aria-label="Findings">
      {findings.map((f, i) => {
        const isSel = i === selected;
        const coach = items.get(f.id);
        return (
          <li
            key={f.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            className={`border-b border-rule py-5 pl-4 ${isSel ? "border-l-4 border-l-tally" : "border-l-4 border-l-transparent"}`}
          >
            <button
              type="button"
              onClick={() => onSelect(i)}
              aria-pressed={isSel}
              className="w-full text-left"
              aria-label={`${f.code} at ${fmtTime(f.start)}: ${findingHeadline(f)}`}
            >
              <span className="label flex flex-wrap items-center gap-x-3">
                <span className="border border-rule px-1.5 py-0.5">{f.code}</span>
                <span>
                  {fmtTime(f.start)}–{fmtTime(f.end)}
                </span>
                <span className="text-ink-2">
                  Severity {f.severity}/3 · {f.dimension}
                </span>
              </span>
              <span className="mt-2 block font-display text-[1.25rem] leading-snug" style={{ fontVariationSettings: '"wdth" 90, "wght" 560' }}>
                {findingHeadline(f)}
              </span>
            </button>
            <Evidence evidence={f.evidence} />
            {coach && <Coach item={coach} />}
          </li>
        );
      })}
    </ol>
  );
}

export function CoachingNote({ coaching }: { coaching: Coaching | null | undefined }) {
  if (!coaching) {
    return (
      <p className="label text-ink-2">
        Coaching unavailable for this take — the measurements stand on their own.
      </p>
    );
  }
  return (
    <p className="label text-ink-2">
      {coaching.source === "bedrock"
        ? `Coaching written by ${coaching.model_id ?? "a language model"} from these findings only, then checked`
        : "Coaching from templates (the model's draft didn't pass the fact check or wasn't available)"}
      {coaching.attempts > 0 ? ` · ${coaching.attempts} attempt${coaching.attempts > 1 ? "s" : ""}` : ""}
    </p>
  );
}
