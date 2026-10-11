import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useApi } from "../api";
import { CardFrame, CueMeta } from "../components/CueCard";
import { ErrorPanel, Loading } from "../components/States";

export function ChallengeIndex() {
  const api = useApi();
  const challenges = useQuery({ queryKey: ["challenges"], queryFn: () => api.listChallenges() });

  return (
    <>
      <section className="grid grid-cols-12 border-b border-rule">
        <div className="col-span-12 overflow-hidden px-[var(--gutter)] pb-8 pt-10 lg:col-span-8 lg:border-r lg:border-rule">
          <p className="label mb-4 text-ink-2">Today's call sheet</p>
          <h1 className="display text-xl uppercase lg:-mr-[6vw] lg:whitespace-nowrap">
            Read it.
            <br />
            Hear it. Fix it.
          </h1>
        </div>
        <div className="col-span-12 flex flex-col justify-end gap-4 px-[var(--gutter)] pb-8 pt-2 lg:col-span-4 lg:pt-10">
          <p className="max-w-prose">
            Pick a script, do a take. We line your words up against a reference reading and mark the exact seconds
            where your pace, pauses, pitch, volume or wording drift — with the measurements to prove it.
          </p>
          <p className="label text-ink-2">
            {challenges.data ? `${challenges.data.length} scripts` : "Scripts"} · English (US) · up to 3 min
          </p>
        </div>
      </section>

      {challenges.isPending && <Loading what="scripts" />}
      {challenges.isError && <ErrorPanel error={challenges.error} onRetry={() => void challenges.refetch()} />}

      {challenges.data && (
        <ol className="flex flex-col gap-8 px-[var(--gutter)] py-10" aria-label="Scripts">
          {challenges.data.map((c, i) => (
            <li key={c.id} className={`grid grid-cols-12 ${i % 2 ? "" : ""}`}>
              <Link
                to={`/c/${c.id}`}
                className={`group col-span-12 block focus-visible:outline-offset-4 md:col-span-10 lg:col-span-9 ${
                  i % 2 ? "md:col-start-3 lg:col-start-4" : ""
                }`}
                aria-label={`${c.title}. Difficulty ${c.difficulty} of 3. ${c.cue}`}
              >
                <CardFrame className="transition-transform duration-200 ease-out group-hover:-translate-y-0.5">
                  <CueMeta challenge={c} number={i + 1} />
                  <div className="grid grid-cols-12 gap-y-3 px-5 py-6 sm:px-8">
                    <h2 className="display col-span-12 text-m uppercase sm:col-span-4 sm:text-[2rem]">{c.title}</h2>
                    <p
                      className="col-span-12 font-display text-[1.35rem] leading-snug sm:col-span-8 sm:text-[1.6rem]"
                      style={{ fontVariationSettings: '"wdth" 88, "wght" 420' }}
                    >
                      {c.script}
                    </p>
                    <p className="voice col-span-12 text-ink-2 sm:col-span-8 sm:col-start-5">“{c.cue}”</p>
                  </div>
                  <div className="label flex justify-end border-t border-rule px-5 py-3 group-hover:bg-ink group-hover:text-paper">
                    Take it →
                  </div>
                </CardFrame>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
