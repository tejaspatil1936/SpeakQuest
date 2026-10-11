import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useApi } from "../api";
import { describeError } from "../api/errors";
import { AudioButton } from "../components/AudioButton";
import { fmtClock, LevelMeter, TallyButton } from "../components/Booth";
import { CardFrame, CueMeta } from "../components/CueCard";
import { ErrorPanel, Loading } from "../components/States";
import { useRecorder } from "../hooks/useRecorder";
import { useSendTake } from "../hooks/useSendTake";
import { MAX_TAKE_SECONDS, QUIET_LEVEL } from "../lib/recorder";

const MIN_TAKE_SECONDS = 1.5;

export default function CuePage() {
  const { id = "" } = useParams();
  const api = useApi();
  const navigate = useNavigate();
  const challenges = useQuery({ queryKey: ["challenges"], queryFn: () => api.listChallenges() });
  const challenge = challenges.data?.find((c) => c.id === id);
  const rec = useRecorder();
  const sender = useSendTake(id);
  const busy = sender.phase === "signing" || sender.phase === "uploading" || sender.phase === "starting";

  // R re-takes from anywhere on the page (system design §9, §10.8).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() !== "r" || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (busy) return;
      if (rec.status === "recorded" || rec.status === "recording" || rec.status === "ready") {
        e.preventDefault();
        sender.reset();
        rec.retake();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rec, sender, busy]);

  if (challenges.isPending) return <Loading what="the cue card" />;
  if (challenges.isError) return <ErrorPanel error={challenges.error} onRetry={() => void challenges.refetch()} />;
  if (!challenge) {
    return (
      <section className="px-[var(--gutter)] py-16">
        <h1 className="display text-xl">No such script.</h1>
        <Link className="btn mt-6" to="/">
          Back to the scripts
        </Link>
      </section>
    );
  }

  const onTally = () => {
    if (rec.status === "recording") rec.stop();
    else if (rec.status === "ready" || rec.status === "recorded") {
      sender.reset();
      rec.start();
    }
  };

  const tooShort = rec.take !== null && rec.take.durationS < MIN_TAKE_SECONDS;
  const quiet = rec.status === "recording" && rec.elapsed > 1.5 && rec.level < QUIET_LEVEL;

  const submit = async () => {
    if (!rec.take) return;
    const analysisId = await sender.send(rec.take);
    if (analysisId) navigate(`/take/${analysisId}`);
  };

  const pct = sender.progress.total ? Math.round((sender.progress.loaded / sender.progress.total) * 100) : 0;

  return (
    <div className="grid grid-cols-12">
      {/* Cue card: the script stays visible while recording. */}
      <section className="col-span-12 px-[var(--gutter)] py-8 lg:col-span-7 lg:border-r lg:border-rule" aria-labelledby="cue-title">
        <p className="label mb-3 text-ink-2">
          <Link to="/" className="underline">
            Scripts
          </Link>{" "}
          / {challenge.title}
        </p>
        <h1 id="cue-title" className="display mb-6 text-xl uppercase">
          {challenge.title}
        </h1>
        <CardFrame>
          <CueMeta challenge={challenge} />
          <p
            className="px-5 py-8 font-display text-l sm:px-8"
            style={{ fontVariationSettings: '"wdth" 92, "wght" 460', lineHeight: 1.25 }}
          >
            {challenge.script}
          </p>
          <div className="flex flex-wrap items-center justify-between gap-4 border-t border-rule px-5 py-4 sm:px-8">
            <p className="voice text-ink-2">“{challenge.cue}”</p>
            {challenge.reference_audio_url && (
              <AudioButton src={challenge.reference_audio_url} label="Reference" />
            )}
          </div>
        </CardFrame>
      </section>

      {/* The booth. */}
      <section className="col-span-12 border-t border-rule px-[var(--gutter)] py-8 lg:col-span-5 lg:border-t-0" aria-label="Recording booth">
        <p className="label mb-6 flex items-center gap-2">
          <span
            aria-hidden="true"
            className={`inline-block h-2.5 w-2.5 rounded-full ${rec.status === "recording" ? "bg-tally" : "border border-rule"}`}
          />
          {rec.status === "recording" ? "On air" : rec.status === "countdown" ? "Standing by" : "Booth"}
          <span className="mono ml-auto text-sm" aria-live="off">
            {fmtClock(rec.elapsed)} / {fmtClock(MAX_TAKE_SECONDS)}
          </span>
        </p>

        {!rec.supported && <ErrorPanel title="Can't record here." error={new Error(rec.error ?? "")} />}

        {rec.supported && (rec.status === "idle" || rec.status === "opening" || rec.status === "error") && (
          <div className="flex flex-col items-start gap-4">
            <p className="max-w-prose">
              Open the microphone first and say a line: the meter shows whether you're loud enough before you
              record.
            </p>
            <button type="button" className="btn btn-solid" onClick={() => void rec.open()} disabled={rec.status === "opening"}>
              {rec.status === "opening" ? "Opening mic…" : "Open the mic"}
            </button>
            {rec.error && (
              <p role="alert" className="border-l-4 border-tally pl-3">
                {rec.error}
              </p>
            )}
          </div>
        )}

        {rec.supported && !["idle", "opening", "error"].includes(rec.status) && (
          <div className="flex flex-col gap-10">
            <div className="flex items-center gap-8">
              <TallyButton status={rec.status} level={rec.level} onClick={onTally} disabled={busy} />
              <div className="min-w-0 flex-1" aria-live="assertive">
                {rec.status === "countdown" && (
                  <p className="display text-mega leading-none" aria-label={`Recording in ${rec.countdown}`}>
                    {rec.countdown || ""}
                  </p>
                )}
                {rec.status === "ready" && <p className="voice text-l">Ready when you are.</p>}
                {rec.status === "recording" && <p className="voice text-l">Read the card.</p>}
                {rec.status === "recorded" && <p className="voice text-l">That's a take.</p>}
              </div>
            </div>

            <LevelMeter level={rec.level} active />
            {quiet && (
              <p role="alert" className="label border-l-4 border-tally pl-3">
                Too quiet — move closer to the mic.
              </p>
            )}

            {rec.status === "recorded" && rec.take && (
              <div className="rule-t flex flex-col gap-4 pt-6">
                <div className="flex flex-wrap items-center gap-4">
                  <AudioButton src={rec.take.url} label="Your take" />
                  <span className="label text-ink-2">
                    {rec.take.durationS.toFixed(1)} s · {(rec.take.blob.size / 1024).toFixed(0)} KB ·{" "}
                    {rec.take.mimeType.split(";")[0]}
                  </span>
                </div>
                {tooShort && (
                  <p role="alert" className="border-l-4 border-tally pl-3">
                    That take is under {MIN_TAKE_SECONDS} s. Read the whole card.
                  </p>
                )}
                {api.mode === "demo" && (
                  <p className="label text-ink-2">
                    Demo build: sending shows a pre-analysed synthetic take for this script, not yours.
                  </p>
                )}
                <div className="flex flex-wrap gap-3">
                  <button type="button" className="btn btn-solid" onClick={() => void submit()} disabled={busy || tooShort}>
                    {sender.phase === "error" ? "Try sending again" : "Send take"}
                  </button>
                  <button type="button" className="btn" onClick={() => { sender.reset(); rec.retake(); }} disabled={busy}>
                    Re-take <span className="kbd">R</span>
                  </button>
                </div>
              </div>
            )}

            {busy && (
              <div aria-live="polite">
                <p className="label mb-2">
                  {sender.phase === "signing" && "Booking a slot…"}
                  {sender.phase === "uploading" &&
                    `Uploading ${pct}%${sender.progress.attempt > 1 ? ` · attempt ${sender.progress.attempt}` : ""}`}
                  {sender.phase === "starting" && "Cueing the analysis…"}
                </p>
                <div className="h-2 border border-rule" role="progressbar" aria-label="Upload progress" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                  <div className="h-full bg-ink" style={{ width: `${sender.phase === "starting" ? 100 : pct}%` }} />
                </div>
              </div>
            )}

            {sender.phase === "error" && (
              <div role="alert" className="border-l-4 border-tally pl-4">
                <p>{describeError(sender.error)}</p>
                <p className="label mt-1 text-ink-2">Your take is still here — nothing was lost.</p>
              </div>
            )}

            <p className="label text-ink-2">
              <span className="kbd">R</span> re-take · up to {MAX_TAKE_SECONDS / 60} min · 10 MB
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
