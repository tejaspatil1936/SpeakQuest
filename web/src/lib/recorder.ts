/**
 * Recording capability detection. Chrome/Firefox produce webm/opus, Safari
 * mp4/aac (system design §2); we ask MediaRecorder which it can actually do.
 */
export const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/ogg;codecs=opus",
  "audio/mp4;codecs=mp4a.40.2",
  "audio/mp4",
  "audio/webm",
] as const;

export const MAX_TAKE_SECONDS = 180;
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

export function pickMimeType(isTypeSupported: (t: string) => boolean): string | null {
  for (const t of MIME_CANDIDATES) {
    try {
      if (isTypeSupported(t)) return t;
    } catch {
      /* some browsers throw for unknown types */
    }
  }
  return null;
}

export type Support = { ok: true; mimeType: string } | { ok: false; reason: string };

export function recordingSupport(win: {
  isSecureContext?: boolean;
  navigator?: { mediaDevices?: { getUserMedia?: unknown } };
  MediaRecorder?: { isTypeSupported?: (t: string) => boolean };
} = globalThis as never): Support {
  if (win.isSecureContext === false) {
    return { ok: false, reason: "Recording needs a secure (https) page." };
  }
  if (!win.navigator?.mediaDevices?.getUserMedia) {
    return { ok: false, reason: "This browser can't open a microphone." };
  }
  if (!win.MediaRecorder?.isTypeSupported) {
    return { ok: false, reason: "This browser can't record audio (no MediaRecorder)." };
  }
  const mimeType = pickMimeType(win.MediaRecorder.isTypeSupported.bind(win.MediaRecorder));
  if (!mimeType) return { ok: false, reason: "This browser can't record Opus or AAC audio." };
  return { ok: true, mimeType };
}

export function micErrorMessage(error: unknown): string {
  const name = error instanceof DOMException || error instanceof Error ? error.name : "";
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
      return "Microphone permission was refused. Allow it in the address bar, then try again.";
    case "NotFoundError":
    case "OverconstrainedError":
      return "No microphone was found. Plug one in and try again.";
    case "NotReadableError":
      return "The microphone is busy in another app.";
    default:
      return "The microphone could not be opened.";
  }
}

/** RMS of a time-domain byte buffer (128 = silence) mapped to 0–1 with a dB curve. */
export function levelFromBytes(buf: Uint8Array): number {
  if (buf.length === 0) return 0;
  let sum = 0;
  for (const v of buf) {
    const x = (v - 128) / 128;
    sum += x * x;
  }
  const rms = Math.sqrt(sum / buf.length);
  const db = 20 * Math.log10(rms || 1e-6);
  return Math.min(1, Math.max(0, (db + 60) / 60));
}

/** Below this meter level the take will likely be rejected as too quiet. */
export const QUIET_LEVEL = 0.25;
