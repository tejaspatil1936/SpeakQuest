import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useApi } from "../api";
import type { LoadedResult } from "../api/types";
import { AudioButton, type AudioButtonHandle } from "../components/AudioButton";
import { CoachingNote, FindingsPanel } from "../components/Findings";
import { KineticTranscript } from "../components/KineticTranscript";
import { FailedView, ProcessingView } from "../components/Processing";
import { ScoreSlate } from "../components/ScoreSlate";
import { ErrorPanel, Loading } from "../components/States";
import { Waveform, type WaveformHandle } from "../components/Waveform";
import { stepFinding } from "../lib/phrases";

export const POLL_MS = 1500;

export default function TakePage() {
  const { analysisId = "" } = useParams();
  const api = useApi();
  const status = useQuery({
    queryKey: ["status", analysisId],
    queryFn: () => api.getStatus(analysisId),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "DONE" || s === "FAILED" ? false : POLL_MS;
    },
    staleTime: 0,
  });
  const done = status.data?.status === "DONE";
  const result = useQuery({
    queryKey: ["result", analysisId],
    queryFn: () => api.getResult(analysisId),
    enabled: done,
    staleTime: 5 * 60_000,
  });

  if (status.isError) return <ErrorPanel error={status.error} onRetry={() => void status.refetch()} title="We lost the take." />;
  if (status.data?.status === "FAILED") return <FailedView status={status.data} />;
  if (!done) return <ProcessingView status={status.data} />;
  if (result.isError) return <ErrorPanel error={result.error} onRetry={() => void result.refetch()} />;
  if (!result.data) return <Loading what="the playback" />;
  return <Playback loaded={result.data} demo={api.mode === "demo"} />;
}

function Playback({ loaded, demo }: { loaded: LoadedResult; demo: boolean }) {
  const { result } = loaded;
  const navigate = useNavigate();
  const wave = useRef<WaveformHandle>(null);
  const refAudio = useRef<AudioButtonHandle>(null);
  const [takeTime, setTakeTime] = useState(-1);
  const [refTime, setRefTime] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState(-1);
  const [plain, setPlain] = useState(false);
  const findings = result.findings;

  const select = useCallback(
    (i: number) => {
      setSelected(i);
      const f = findings[i];
      if (f) wave.current?.seek(Math.max(0, f.start - 0.25));
    },
    [findings],
  );

  // Space play/pause · ←/→ step findings · R re-take (system design §10.8).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
      if (e.key === " " && !(t instanceof HTMLButtonElement)) {
        e.preventDefault();
        wave.current?.playPause();
      } else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        select(stepFinding(selected, e.key === "ArrowRight" ? 1 : -1, findings.length));
      } else if (e.key.toLowerCase() === "r") {
        navigate(`/c/${result.challenge_id}`);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [findings.length, navigate, result.challenge_id, select, selected]);

  const seekReference = (t: number) => {
    const el = refAudio.current?.audio;
    if (!el) return;
    el.currentTime = t;
    void el.play().catch(() => undefined);
  };

  return (
    <article>
      {demo && (
        <p className="label border-b border-rule px-[var(--gutter)] py-2 text-ink-2">
          Demo fixture · synthetic TTS voice analysed by the real pipeline · not your recording
        </p>
      )}
      <ScoreSlate result={result} />

      <section className="border-b border-rule px-[var(--gutter)] py-6" aria-labelledby="transcript-h">
        <div className="mb-2 flex flex-wrap items-center gap-x-6 gap-y-3">
          <h2 id="transcript-h" className="display text-m uppercase">
            The playback
          </h2>
          <button type="button" className="btn" onClick={() => wave.current?.playPause()}>
            {playing ? "Pause take" : "Play take"} <span className="kbd">Space</span>
          </button>
          {loaded.referenceAudioUrl && (
            <AudioButton ref={refAudio} src={loaded.referenceAudioUrl} label="Reference" onTime={setRefTime} />
          )}
          <label className="label ml-auto flex min-h-[44px] cursor-pointer items-center gap-2">
            <input type="checkbox" checked={plain} onChange={(e) => setPlain(e.target.checked)} className="h-4 w-4 accent-[var(--ink)]" />
            Plain text
          </label>
        </div>
        <KineticTranscript
          result={result}
          takeTime={takeTime}
          refTime={refTime}
          selectedFindingId={findings[selected]?.id ?? null}
          onSeekTake={(t) => {
            wave.current?.seek(t);
            wave.current?.play();
          }}
          onSeekReference={seekReference}
          plain={plain}
        />
      </section>

      <section className="px-[var(--gutter)] py-6" aria-label="Waveform">
        <Waveform
          ref={wave}
          url={loaded.audioUrl}
          findings={findings}
          selectedId={findings[selected]?.id ?? null}
          onTime={setTakeTime}
          onPlayingChange={setPlaying}
          onRegionClick={(id) => select(findings.findIndex((f) => f.id === id))}
        />
      </section>

      <section className="grid grid-cols-12 border-t border-rule" aria-labelledby="notes-h">
        <div className="col-span-12 px-[var(--gutter)] py-6 lg:col-span-4 lg:border-r lg:border-rule">
          <h2 id="notes-h" className="display text-m uppercase">
            Director's notes
          </h2>
          <p className="label mt-2 text-ink-2">
            {findings.length} {findings.length === 1 ? "note" : "notes"} · <span className="kbd">←</span>{" "}
            <span className="kbd">→</span> to step · <span className="kbd">R</span> re-take
          </p>
          <div className="mt-4">
            <CoachingNote coaching={result.coaching} />
          </div>
          {result.warnings.length > 0 && (
            <ul className="label mt-4 flex flex-col gap-1 text-ink-2">
              {result.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
          <div className="mt-6 flex flex-wrap gap-3">
            <Link to={`/c/${result.challenge_id}`} className="btn btn-solid">
              Re-take <span className="kbd">R</span>
            </Link>
            <Link to="/me" className="btn">
              All takes
            </Link>
          </div>
        </div>
        <div className="col-span-12 px-[var(--gutter)] lg:col-span-8">
          <FindingsPanel findings={findings} coaching={result.coaching} selected={selected} onSelect={select} />
        </div>
      </section>
    </article>
  );
}
