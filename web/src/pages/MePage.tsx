import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useApi } from "../api";
import type { Badge, ProgressResponse } from "../api/schema";
import { ErrorPanel, Loading } from "../components/States";
import { airTime, LEVELS } from "../lib/levels";

function Stamp({ badge, i }: { badge: Badge; i: number }) {
  const tilt = [-6, 4, -3, 7, -8, 2][i % 6];
  return (
    <li
      className="wide inline-block border-[3px] border-double border-rule px-4 py-2 text-[0.95rem] uppercase"
      style={{ transform: `rotate(${tilt}deg)` }}
      aria-label={`Stamp: ${badge.label}, ${new Date(badge.awarded_at).toLocaleDateString()}`}
    >
      {badge.label}
      <span className="mono mt-1 block text-[0.62rem] tracking-[0.12em]">
        {new Date(badge.awarded_at).toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" })}
      </span>
    </li>
  );
}

function Ladder({ progress }: { progress: ProgressResponse }) {
  const { level, xp } = progress;
  const toNext = level.next_at_s != null ? Math.max(0, level.next_at_s - xp) : null;
  return (
    <div>
      <ol className="flex flex-col" aria-label="Levels">
        {LEVELS.map((l, i) => {
          const state = i < level.index ? "past" : i === level.index ? "now" : "next";
          return (
            <li key={l.name} className="flex items-baseline gap-4 border-b border-rule py-2" aria-current={state === "now" ? "step" : undefined}>
              <span className="mono w-6 text-sm text-ink-2">{String(i + 1).padStart(2, "0")}</span>
              <span
                className={`font-display text-[1.3rem] ${state === "next" ? "text-ink-2" : ""}`}
                style={{ fontVariationSettings: `"wdth" ${state === "now" ? 125 : 80}, "wght" ${state === "now" ? 800 : 450}` }}
              >
                {l.name}
              </span>
              {state === "now" && <span className="label ml-auto">You are here</span>}
            </li>
          );
        })}
      </ol>
      <p className="label mt-3 text-ink-2">
        {toNext != null && level.next_name ? `${airTime(toNext)} of air time to ${level.next_name}` : "Top of the bill."}
      </p>
    </div>
  );
}

export default function MePage() {
  const api = useApi();
  const progress = useQuery({ queryKey: ["progress"], queryFn: () => api.getProgress(), staleTime: 0 });
  const challenges = useQuery({ queryKey: ["challenges"], queryFn: () => api.listChallenges() });
  const titles = new Map((challenges.data ?? []).map((c) => [c.id, c.title]));

  if (progress.isPending) return <Loading what="your takes" />;
  if (progress.isError) return <ErrorPanel error={progress.error} onRetry={() => void progress.refetch()} />;
  const p = progress.data;

  return (
    <>
      {api.mode === "demo" && (
        <p className="label border-b border-rule px-[var(--gutter)] py-2 text-ink-2">
          Demo data · derived from the bundled synthetic fixtures, not from your recordings
        </p>
      )}
      <section className="grid grid-cols-12 border-b border-rule">
        <div className="col-span-12 overflow-hidden px-[var(--gutter)] py-8 lg:col-span-7 lg:border-r lg:border-rule">
          <p className="label text-ink-2">Air time</p>
          <p className="display text-mega tabular-nums" aria-label={`Air time ${airTime(p.xp)}`}>
            {Math.floor(p.xp / 60)}
            <span className="text-xl">m</span>
            {String(p.xp % 60).padStart(2, "0")}
            <span className="text-xl">s</span>
          </p>
          <p className="voice text-l">
            {p.takes.length === 0
              ? "No takes yet. The booth is open."
              : `${p.takes.length} ${p.takes.length === 1 ? "take" : "takes"} on file. Level: ${p.level.name}.`}
          </p>
        </div>
        <div className="col-span-12 px-[var(--gutter)] py-8 lg:col-span-5">
          <Ladder progress={p} />
        </div>
      </section>

      <section className="border-b border-rule px-[var(--gutter)] py-8" aria-labelledby="stamps-h">
        <h2 id="stamps-h" className="display text-m uppercase">
          Stamps
        </h2>
        {p.badges.length === 0 ? (
          <p className="voice mt-3">No stamps yet. Finish a take to earn your first.</p>
        ) : (
          <ul className="mt-6 flex flex-wrap gap-x-8 gap-y-6">
            {p.badges.map((b, i) => (
              <Stamp key={b.id} badge={b} i={i} />
            ))}
          </ul>
        )}
      </section>

      <section className="px-[var(--gutter)] py-8" aria-labelledby="takes-h">
        <h2 id="takes-h" className="display text-m uppercase">
          Takes
        </h2>
        {p.takes.length === 0 ? (
          <p className="mt-3">
            <Link className="btn mt-2" to="/">
              Pick a script
            </Link>
          </p>
        ) : (
          <div className="mt-4 overflow-x-auto" data-scroll-x tabIndex={0} role="region" aria-label="Takes table, scrolls sideways on small screens">
            <table className="mono w-full min-w-[560px] border-collapse text-sm">
              <thead>
                <tr className="label border-b-2 border-rule text-left">
                  <th scope="col" className="py-2 font-normal">When</th>
                  <th scope="col" className="py-2 font-normal">Script</th>
                  <th scope="col" className="py-2 text-right font-normal">Length</th>
                  <th scope="col" className="py-2 text-right font-normal">Score</th>
                  <th scope="col" className="py-2 pl-4 font-normal">Flags</th>
                </tr>
              </thead>
              <tbody>
                {p.takes.map((t) => (
                  <tr key={t.analysisId} className="border-b border-rule">
                    <td className="py-2.5">
                      {new Date(t.createdAt).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
                    </td>
                    <td className="py-2.5">
                      <Link className="underline" to={`/take/${t.analysisId}`}>
                        {titles.get(t.challengeId) ?? t.challengeId}
                      </Link>
                    </td>
                    <td className="py-2.5 text-right">{t.durationS != null ? `${t.durationS.toFixed(1)} s` : "–"}</td>
                    <td className="py-2.5 text-right text-[1.05rem] font-semibold">
                      {t.status === "DONE" ? (t.scores?.overall ?? "–") : t.status.toLowerCase()}
                    </td>
                    <td className="py-2.5 pl-4 text-ink-2">{t.codes.length ? t.codes.join(" ") : t.status === "DONE" ? "clean" : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
