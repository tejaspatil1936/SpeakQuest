import { QUIET_LEVEL } from "../lib/recorder";
import type { RecorderStatus } from "../hooks/useRecorder";

/**
 * The record button is a tally light. Its halo grows with the *measured*
 * input level — no looping animation — and it only turns red while recording.
 */
export function TallyButton({
  status,
  level,
  onClick,
  disabled,
}: {
  status: RecorderStatus;
  level: number;
  onClick: () => void;
  disabled?: boolean;
}) {
  const live = status === "recording";
  const label =
    status === "recording" ? "Stop recording" : status === "countdown" ? "Counting in" : "Start recording";
  const halo = live || status === "ready" ? Math.round(level * 26) : 0;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || status === "countdown"}
      aria-label={label}
      aria-pressed={live}
      className="relative grid h-36 w-36 shrink-0 place-items-center rounded-full border-2 border-rule disabled:opacity-40 sm:h-44 sm:w-44"
      style={{
        outline: halo ? `${halo / 4 + 1}px solid ${live ? "var(--tally)" : "var(--ink)"}` : undefined,
        outlineOffset: `${4 + halo}px`,
        transition: "outline-offset 60ms linear",
      }}
    >
      <span
        aria-hidden="true"
        className={`block rounded-full ${live ? "bg-tally" : "bg-ink"}`}
        style={{
          width: live ? "72%" : "38%",
          height: live ? "72%" : "38%",
          transform: `scale(${1 + (live ? level * 0.12 : 0)})`,
        }}
      />
      <span className="label absolute -bottom-8 whitespace-nowrap">
        {live ? "On air · stop" : status === "recorded" ? "Record again" : "Record"}
      </span>
    </button>
  );
}

/** Horizontal level meter with a quiet-zone marker, in 20 segments. */
export function LevelMeter({ level, active }: { level: number; active: boolean }) {
  const segments = 20;
  const lit = Math.round(level * segments);
  const quietSeg = Math.round(QUIET_LEVEL * segments);
  const db = active ? Math.round(level * 60 - 60) : null;
  return (
    <div>
      <div className="label mb-1 flex justify-between text-ink-2">
        <span>Input</span>
        <span aria-live="off">{db === null ? "mic closed" : `${db} dBFS`}</span>
      </div>
      <div
        role="meter"
        aria-label="Microphone input level"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(level * 100)}
        className="flex h-5 gap-[2px] border border-rule p-[2px]"
      >
        {Array.from({ length: segments }, (_, i) => (
          <span
            key={i}
            className={`flex-1 ${i < lit ? "bg-ink" : ""} ${i === quietSeg ? "border-l border-dashed border-ink-2" : ""}`}
          />
        ))}
      </div>
      <div className="label mt-1 flex justify-between text-ink-2">
        <span>−60</span>
        <span>too quiet ↑</span>
        <span>0 dB</span>
      </div>
    </div>
  );
}

export function fmtClock(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = (seconds % 60).toFixed(1).padStart(4, "0");
  return `${m}:${s}`;
}
