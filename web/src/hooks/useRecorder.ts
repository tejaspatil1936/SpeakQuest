import { useCallback, useEffect, useRef, useState } from "react";
import { levelFromBytes, MAX_TAKE_SECONDS, micErrorMessage, recordingSupport } from "../lib/recorder";

export type RecorderStatus = "idle" | "opening" | "ready" | "countdown" | "recording" | "recorded" | "error";

export interface Take {
  blob: Blob;
  url: string;
  mimeType: string;
  durationS: number;
}

/**
 * Microphone → live level meter → 3-2-1 count-in → MediaRecorder.
 * Processing (AGC, noise suppression, echo cancellation) is turned off so the
 * loudness we measure later is the speaker's, not the browser's.
 */
export function useRecorder() {
  const support = useRef(recordingSupport());
  const [status, setStatus] = useState<RecorderStatus>("idle");
  const [error, setError] = useState<string | null>(support.current.ok ? null : support.current.reason);
  const [level, setLevel] = useState(0);
  const [countdown, setCountdown] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [take, setTake] = useState<Take | null>(null);

  const stream = useRef<MediaStream | null>(null);
  const ctx = useRef<AudioContext | null>(null);
  const raf = useRef<number>(0);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const started = useRef(0);
  const timers = useRef<number[]>([]);
  const urlRef = useRef<string | null>(null);

  const clearTimers = () => {
    timers.current.forEach((t) => window.clearTimeout(t));
    timers.current = [];
  };

  const release = useCallback(() => {
    clearTimers();
    cancelAnimationFrame(raf.current);
    if (recorder.current && recorder.current.state !== "inactive") recorder.current.stop();
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    void ctx.current?.close().catch(() => undefined);
    ctx.current = null;
  }, []);

  useEffect(
    () => () => {
      release();
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    },
    [release],
  );

  const open = useCallback(async () => {
    if (!support.current.ok) return;
    setStatus("opening");
    setError(null);
    try {
      const media = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, autoGainControl: false, noiseSuppression: false, echoCancellation: false },
      });
      stream.current = media;
      const audioCtx = new AudioContext();
      ctx.current = audioCtx;
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 1024;
      audioCtx.createMediaStreamSource(media).connect(analyser);
      const buf = new Uint8Array(analyser.fftSize);
      let smoothed = 0;
      const tick = () => {
        analyser.getByteTimeDomainData(buf);
        const now = levelFromBytes(buf);
        // Fast attack, slow release, like a broadcast meter.
        smoothed = now > smoothed ? now : smoothed * 0.9 + now * 0.1;
        setLevel(smoothed);
        if (recorder.current?.state === "recording") {
          const secs = (performance.now() - started.current) / 1000;
          setElapsed(secs);
          if (secs >= MAX_TAKE_SECONDS) recorder.current.stop();
        }
        raf.current = requestAnimationFrame(tick);
      };
      raf.current = requestAnimationFrame(tick);
      setStatus("ready");
    } catch (e) {
      setError(micErrorMessage(e));
      setStatus("error");
    }
  }, []);

  const beginRecording = useCallback(() => {
    const media = stream.current;
    if (!media || !support.current.ok) return;
    const mimeType = support.current.mimeType;
    const rec = new MediaRecorder(media, { mimeType, audioBitsPerSecond: 64_000 });
    chunks.current = [];
    rec.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.current.push(e.data);
    };
    rec.onstop = () => {
      const durationS = (performance.now() - started.current) / 1000;
      const blob = new Blob(chunks.current, { type: rec.mimeType || mimeType });
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      const url = URL.createObjectURL(blob);
      urlRef.current = url;
      setTake({ blob, url, mimeType: blob.type, durationS });
      setElapsed(durationS);
      setStatus("recorded");
    };
    recorder.current = rec;
    started.current = performance.now();
    setElapsed(0);
    rec.start(250);
    setStatus("recording");
  }, []);

  /** 3-2-1 count-in, then record. */
  const start = useCallback(() => {
    if (!stream.current) return;
    clearTimers();
    setTake(null);
    setStatus("countdown");
    [3, 2, 1].forEach((n, i) => timers.current.push(window.setTimeout(() => setCountdown(n), i * 1000)));
    timers.current.push(
      window.setTimeout(() => {
        setCountdown(0);
        beginRecording();
      }, 3000),
    );
  }, [beginRecording]);

  const stop = useCallback(() => {
    if (recorder.current?.state === "recording") recorder.current.stop();
  }, []);

  /** Discard the current take (or the one in progress) and count in again. */
  const retake = useCallback(() => {
    if (recorder.current?.state === "recording") {
      recorder.current.onstop = null;
      recorder.current.stop();
    }
    start();
  }, [start]);

  return { supported: support.current.ok, status, error, level, countdown, elapsed, take, open, start, stop, retake };
}
