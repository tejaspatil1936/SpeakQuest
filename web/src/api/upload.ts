/**
 * Direct browser → S3 upload through a presigned PUT (audio never passes
 * through Lambda). XHR rather than fetch because only XHR reports upload
 * progress. Transient failures are retried with backoff; 4xx are not.
 */
import { ApiError } from "./errors";
import type { CreateUploadResponse } from "./schema";
import type { UploadProgress } from "./types";

export interface XhrLike {
  open(method: string, url: string): void;
  setRequestHeader(name: string, value: string): void;
  send(body: Blob): void;
  abort(): void;
  status: number;
  timeout: number;
  upload: { onprogress: ((e: { loaded: number; total: number; lengthComputable: boolean }) => void) | null };
  onload: (() => void) | null;
  onerror: (() => void) | null;
  ontimeout: (() => void) | null;
}

export interface UploadOptions {
  attempts?: number;
  backoffMs?: number;
  timeoutMs?: number;
  makeXhr?: () => XhrLike;
  sleep?: (ms: number) => Promise<void>;
  onProgress?: (p: UploadProgress) => void;
}

const defaultSleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

function putOnce(
  presign: CreateUploadResponse,
  body: Blob,
  attempt: number,
  opts: Required<Pick<UploadOptions, "makeXhr" | "timeoutMs">> & Pick<UploadOptions, "onProgress">,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = opts.makeXhr();
    xhr.open(presign.method, presign.uploadUrl);
    for (const [name, value] of Object.entries(presign.headers)) xhr.setRequestHeader(name, value);
    xhr.timeout = opts.timeoutMs;
    xhr.upload.onprogress = (e) => {
      opts.onProgress?.({ loaded: e.loaded, total: e.lengthComputable ? e.total : body.size, attempt });
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        opts.onProgress?.({ loaded: body.size, total: body.size, attempt });
        resolve();
      } else {
        reject(new ApiError("UPLOAD_REJECTED", `Storage refused the upload (HTTP ${xhr.status}).`, xhr.status));
      }
    };
    xhr.onerror = () => reject(new ApiError("NETWORK", "The upload was interrupted.", 0));
    xhr.ontimeout = () => reject(new ApiError("TIMEOUT", "The upload timed out.", 408));
    xhr.send(body);
  });
}

export async function uploadWithRetry(
  presign: CreateUploadResponse,
  body: Blob,
  options: UploadOptions = {},
): Promise<void> {
  const attempts = options.attempts ?? 3;
  const backoff = options.backoffMs ?? 800;
  const sleep = options.sleep ?? defaultSleep;
  const makeXhr = options.makeXhr ?? (() => new XMLHttpRequest() as unknown as XhrLike);
  let last: unknown;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      await putOnce(presign, body, attempt, {
        makeXhr,
        timeoutMs: options.timeoutMs ?? 60_000,
        onProgress: options.onProgress,
      });
      return;
    } catch (error) {
      last = error;
      const retryable = error instanceof ApiError ? error.retryable : true;
      if (!retryable || attempt === attempts) break;
      await sleep(backoff * 2 ** (attempt - 1));
    }
  }
  throw last;
}
