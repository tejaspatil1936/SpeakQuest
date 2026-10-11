import { Link } from "react-router-dom";
import type { AnalysisStatusResponse, Stage } from "../api/schema";

const STEPS: Array<{ stage: Stage; label: string; detail: string }> = [
  { stage: "NORMALIZE", label: "Normalise", detail: "16 kHz mono, level and length checks" },
  { stage: "TRANSCRIBE", label: "Transcribe", detail: "Word-level timestamps" },
  { stage: "ANALYZE", label: "Analyse", detail: "Script diff, pace, pauses, pitch, volume" },
  { stage: "EXPLAIN", label: "Explain", detail: "Coaching from the findings, fact-checked" },
  { stage: "PERSIST", label: "File it", detail: "Score, air time and stamps" },
];
const ORDER: Stage[] = ["QUEUED", "NORMALIZE", "TRANSCRIBE", "ANALYZE", "EXPLAIN", "PERSIST", "DONE"];

export function ProcessingView({ status }: { status: AnalysisStatusResponse | undefined }) {
  const at = status ? ORDER.indexOf(status.stage) : 0;
  return (
    <section className="grid grid-cols-12 px-[var(--gutter)] py-10" aria-live="polite" aria-busy="true">
      <div className="col-span-12 lg:col-span-7">
        <p className="label mb-3 text-ink-2">Take {status?.analysisId.slice(0, 8) ?? "…"}</p>
        <h1 className="display text-xl uppercase">In the edit.</h1>
        <p className="voice mt-4 text-l">Listening back against the reference. This usually takes under a minute.</p>
      </div>
      <ol className="col-span-12 mt-10 lg:col-span-5 lg:mt-0">
        {STEPS.map((step) => {
          const idx = ORDER.indexOf(step.stage);
          const state = idx < at ? "done" : idx === at ? "now" : "next";
          return (
            <li key={step.stage} className="flex items-baseline gap-4 border-b border-rule py-3">
              <span className="mono w-14 text-sm">{state === "done" ? "done" : state === "now" ? "now ▸" : ""}</span>
              <span className={state === "next" ? "text-ink-2" : ""}>
                <span className="font-display text-[1.2rem]" style={{ fontVariationSettings: `"wdth" 80, "wght" ${state === "now" ? 800 : 500}` }}>
                  {step.label}
                </span>
                <span className="label ml-3 text-ink-2">{step.detail}</span>
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export function FailedView({ status }: { status: AnalysisStatusResponse }) {
  return (
    <section className="px-[var(--gutter)] py-10" role="alert">
      <p className="label mb-3 flex items-center gap-2">
        <span aria-hidden="true" className="inline-block h-2.5 w-2.5 rounded-full bg-tally" />
        Take failed{status.error?.stage ? ` at ${status.error.stage.toLowerCase()}` : ""}
      </p>
      <h1 className="display text-xl uppercase">Cut.</h1>
      <p className="voice mt-4 max-w-prose text-l">{status.error?.message ?? "The analysis stopped before it finished."}</p>
      {status.error?.code && <p className="label mt-3 text-ink-2">Code {status.error.code}</p>}
      <div className="mt-8 flex flex-wrap gap-3">
        <Link to={`/c/${status.challengeId}`} className="btn btn-solid">
          Record it again
        </Link>
        <Link to="/" className="btn">
          Pick another script
        </Link>
      </div>
    </section>
  );
}
