import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

export interface AudioButtonHandle {
  audio: HTMLAudioElement | null;
}

/** A plain play/pause control for a single clip, with elapsed time in mono. */
export const AudioButton = forwardRef<
  AudioButtonHandle,
  { src: string; label: string; onTime?: (t: number) => void }
>(function AudioButton({ src, label, onTime }, ref) {
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [failed, setFailed] = useState(false);
  useImperativeHandle(ref, () => ({ audio: audio.current }), []);

  useEffect(() => {
    const el = audio.current;
    if (!el) return;
    let raf = 0;
    const loop = () => {
      setTime(el.currentTime);
      onTime?.(el.currentTime);
      if (!el.paused) raf = requestAnimationFrame(loop);
    };
    const onPlay = () => {
      setPlaying(true);
      raf = requestAnimationFrame(loop);
    };
    const onPause = () => {
      setPlaying(false);
      cancelAnimationFrame(raf);
      onTime?.(-1);
    };
    el.addEventListener("play", onPlay);
    el.addEventListener("pause", onPause);
    el.addEventListener("ended", onPause);
    return () => {
      cancelAnimationFrame(raf);
      el.removeEventListener("play", onPlay);
      el.removeEventListener("pause", onPause);
      el.removeEventListener("ended", onPause);
    };
  }, [onTime]);

  return (
    <div className="flex items-center gap-3">
      {/* No <track>: captions are the synced transcript on the page (the reference line
          highlights the word being spoken), and the script itself is always on screen. */}
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio ref={audio} src={src} preload="metadata" onError={() => setFailed(true)} />
      <button
        type="button"
        className="btn"
        disabled={failed}
        onClick={() => {
          const el = audio.current;
          if (!el) return;
          if (el.paused) void el.play().catch(() => setFailed(true));
          else el.pause();
        }}
        aria-label={`${playing ? "Pause" : "Play"} ${label}`}
      >
        <span aria-hidden="true">{playing ? "❚❚" : "▶"}</span>
        {label}
      </button>
      <span className="mono text-sm text-ink-2">{failed ? "unavailable" : `${time.toFixed(1)} s`}</span>
    </div>
  );
});
