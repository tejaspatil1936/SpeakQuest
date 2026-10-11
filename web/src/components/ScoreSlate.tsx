import { motion, useReducedMotion } from "motion/react";
import type { AnalysisResult } from "../api/schema";
import { DIMENSIONS } from "../api/schema";
import { DIMENSION_LABELS, takeSummary } from "../lib/copy";

/** Mega score, cropped by the viewport, beside a mono "slate" of dimensions. */
export function ScoreSlate({ result }: { result: AnalysisResult }) {
  const reduce = useReducedMotion();
  const counts = Object.fromEntries(DIMENSIONS.map((d) => [d, result.findings.filter((f) => f.dimension === d).length]));
  const points = Object.fromEntries(
    DIMENSIONS.map((d) => [d, result.penalties.filter((p) => p.dimension === d).reduce((s, p) => s + p.points, 0)]),
  );
  return (
    <section className="grid grid-cols-12 border-b border-rule" aria-label="Score">
      <div className="col-span-12 overflow-hidden pl-[var(--gutter)] lg:col-span-7 lg:border-r lg:border-rule">
        <p className="label pt-6">Take score / 100</p>
        <motion.p
          className="display -ml-[0.07em] text-mega tabular-nums"
          style={{ fontVariationSettings: '"wdth" 62, "wght" 900' }}
          initial={reduce ? false : { opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: "easeOut" }}
          aria-label={`Overall score ${result.scores.overall} out of 100`}
        >
          {result.scores.overall}
        </motion.p>
        <p className="voice max-w-prose pb-6 pr-[var(--gutter)] text-l">{takeSummary(result.findings)}</p>
      </div>
      <div className="col-span-12 px-[var(--gutter)] py-6 lg:col-span-5">
        <table className="mono w-full border-collapse text-sm">
          <caption className="label mb-3 text-left">Slate</caption>
          <thead>
            <tr className="label border-b-2 border-rule text-left">
              <th scope="col" className="py-2 font-normal">
                Dimension
              </th>
              <th scope="col" className="py-2 text-right font-normal">
                Score
              </th>
              <th scope="col" className="py-2 text-right font-normal">
                Flags
              </th>
              <th scope="col" className="py-2 text-right font-normal">
                −Pts
              </th>
            </tr>
          </thead>
          <tbody>
            {DIMENSIONS.map((d) => (
              <tr key={d} className="border-b border-rule">
                <th scope="row" className="py-2.5 text-left font-normal">
                  {DIMENSION_LABELS[d]}
                </th>
                <td className="py-2.5 text-right text-[1.1rem] font-semibold">{result.scores[d]}</td>
                <td className="py-2.5 text-right">{counts[d] || "–"}</td>
                <td className="py-2.5 text-right text-ink-2">{points[d] ? points[d] : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <dl className="label mt-5 grid grid-cols-2 gap-x-4 gap-y-1 text-ink-2">
          <dt>Rubric</dt>
          <dd>v{result.versions.rubric_version}</dd>
          <dt>Timing</dt>
          <dd className="truncate">{result.versions.aligner}</dd>
          <dt>Language</dt>
          <dd>{result.versions.transcribe_language}</dd>
          <dt>Pace vs ref</dt>
          <dd>{result.take.rate_ratio_global != null ? `${result.take.rate_ratio_global.toFixed(2)}×` : "–"}</dd>
        </dl>
      </div>
    </section>
  );
}
