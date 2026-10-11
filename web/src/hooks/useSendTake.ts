import { useCallback, useRef, useState } from "react";
import { useApi } from "../api";
import { ApiError } from "../api/errors";
import type { CreateUploadResponse } from "../api/schema";
import { MAX_UPLOAD_BYTES } from "../lib/recorder";
import type { Take } from "./useRecorder";

export type SendPhase = "idle" | "signing" | "uploading" | "starting" | "error";

/**
 * Take → presigned URL → direct upload → start analysis. A retry resumes from
 * the step that failed (an expired URL is simply re-signed).
 */
export function useSendTake(challengeId: string) {
  const api = useApi();
  const [phase, setPhase] = useState<SendPhase>("idle");
  const [progress, setProgress] = useState({ loaded: 0, total: 0, attempt: 1 });
  const [error, setError] = useState<unknown>(null);
  const uploaded = useRef<{ blob: Blob; presign: CreateUploadResponse } | null>(null);

  const send = useCallback(
    async (take: Take): Promise<string | null> => {
      setError(null);
      try {
        if (api.mode === "demo") {
          setPhase("starting");
          return await api.createAnalysis(challengeId, "demo-local");
        }
        if (take.blob.size > MAX_UPLOAD_BYTES) {
          throw new ApiError("AUDIO_TOO_LARGE", "This take is over the 10 MB limit. Record a shorter take.", 413);
        }
        let presign = uploaded.current?.blob === take.blob ? uploaded.current.presign : null;
        if (!presign) {
          setPhase("signing");
          const signed = await api.createUpload(challengeId, take.mimeType, take.blob.size);
          setPhase("uploading");
          setProgress({ loaded: 0, total: take.blob.size, attempt: 1 });
          await api.upload(signed, take.blob, setProgress);
          uploaded.current = { blob: take.blob, presign: signed };
          presign = signed;
        }
        setPhase("starting");
        return await api.createAnalysis(challengeId, presign.key, Number(take.durationS.toFixed(2)));
      } catch (e) {
        // A rejected upload usually means the URL expired: sign again next time.
        if (e instanceof ApiError && e.code === "UPLOAD_REJECTED") uploaded.current = null;
        setError(e);
        setPhase("error");
        return null;
      }
    },
    [api, challengeId],
  );

  const reset = useCallback(() => {
    uploaded.current = null;
    setPhase("idle");
    setError(null);
  }, []);

  return { phase, progress, error, send, reset };
}
