/**
 * Production adapter: the API Gateway HTTP API described in system design §3.
 * Every response body is validated with Zod before the UI sees it.
 */
import type { z } from "zod";
import { ApiError } from "./errors";
import {
  AnalysisResult,
  AnalysisResultResponse,
  AnalysisStatusResponse,
  ChallengeList,
  CreateAnalysisResponse,
  CreateUploadResponse,
  ErrorResponse,
  ProgressResponse,
} from "./schema";
import { getSessionId } from "./session";
import type { LoadedResult, SpeakQuestApi, UploadProgress } from "./types";
import { uploadWithRetry } from "./upload";

export interface HttpOptions {
  baseUrl: string;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  sessionId?: () => string;
}

export class HttpApi implements SpeakQuestApi {
  readonly mode = "http" as const;
  private readonly base: string;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;
  private readonly sessionId: () => string;

  constructor(opts: HttpOptions) {
    this.base = opts.baseUrl.replace(/\/+$/, "");
    this.fetchImpl = opts.fetchImpl ?? ((...args) => globalThis.fetch(...args));
    this.timeoutMs = opts.timeoutMs ?? 15_000;
    this.sessionId = opts.sessionId ?? (() => getSessionId());
  }

  private async request<T extends z.ZodTypeAny>(
    schema: T,
    path: string,
    init: RequestInit = {},
    absolute = false,
  ): Promise<z.infer<T>> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    const headers = new Headers(init.headers);
    if (!absolute) {
      headers.set("x-session-id", this.sessionId());
      if (init.body) headers.set("content-type", "application/json");
    }
    let response: Response;
    try {
      response = await this.fetchImpl(absolute ? path : `${this.base}${path}`, {
        ...init,
        headers,
        signal: controller.signal,
      });
    } catch (error) {
      if (controller.signal.aborted) throw new ApiError("TIMEOUT", "Request timed out.", 408);
      throw new ApiError("NETWORK", error instanceof Error ? error.message : "Network error", 0);
    } finally {
      clearTimeout(timer);
    }

    let body: unknown = null;
    const text = await response.text();
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        if (response.ok) throw new ApiError("BAD_RESPONSE", "Response was not JSON.", response.status);
      }
    }

    if (!response.ok) {
      const parsed = ErrorResponse.safeParse(body);
      if (parsed.success) {
        const e = parsed.data.error;
        throw new ApiError(e.code, e.message, response.status, e.stage ?? null);
      }
      if (response.status === 429) throw new ApiError("THROTTLED", "Too many requests.", 429);
      throw new ApiError("HTTP_ERROR", `Request failed (HTTP ${response.status}).`, response.status);
    }

    const parsed = schema.safeParse(body);
    if (!parsed.success) {
      throw new ApiError("BAD_RESPONSE", `Unexpected response from ${path}: ${parsed.error.issues[0]?.message ?? ""}`, response.status);
    }
    return parsed.data;
  }

  async listChallenges() {
    return (await this.request(ChallengeList, "/challenges")).challenges;
  }

  createUpload(challengeId: string, contentType: string, bytes: number) {
    return this.request(CreateUploadResponse, "/uploads", {
      method: "POST",
      body: JSON.stringify({ challengeId, contentType, bytes }),
    });
  }

  upload(
    presign: z.infer<typeof CreateUploadResponse>,
    body: Blob,
    onProgress?: (p: UploadProgress) => void,
  ) {
    return uploadWithRetry(presign, body, { onProgress });
  }

  async createAnalysis(challengeId: string, key: string, durationS?: number) {
    const res = await this.request(CreateAnalysisResponse, "/analyses", {
      method: "POST",
      body: JSON.stringify({ challengeId, key, ...(durationS ? { durationS } : {}) }),
    });
    return res.analysisId;
  }

  getStatus(analysisId: string) {
    return this.request(AnalysisStatusResponse, `/analyses/${encodeURIComponent(analysisId)}`);
  }

  async getResult(analysisId: string): Promise<LoadedResult> {
    const urls = await this.request(
      AnalysisResultResponse,
      `/analyses/${encodeURIComponent(analysisId)}/result`,
    );
    const result = await this.request(AnalysisResult, urls.resultUrl, {}, true);
    return { result, audioUrl: urls.audioUrl, referenceAudioUrl: urls.referenceAudioUrl ?? null };
  }

  getProgress() {
    return this.request(ProgressResponse, "/me/progress");
  }
}
