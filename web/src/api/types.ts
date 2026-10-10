import type {
  AnalysisResult,
  AnalysisStatusResponse,
  Challenge,
  CreateUploadResponse,
  ProgressResponse,
} from "./schema";

export interface LoadedResult {
  result: AnalysisResult;
  audioUrl: string;
  referenceAudioUrl: string | null;
}

export interface UploadProgress {
  loaded: number;
  total: number;
  attempt: number;
}

/**
 * Everything the UI needs from a backend. Two implementations exist: the HTTP
 * adapter (production) and the demo adapter (static fixtures), chosen once in
 * `api/index.ts`. Components never know which one they talk to beyond `mode`.
 */
export interface SpeakQuestApi {
  readonly mode: "http" | "demo";
  listChallenges(): Promise<Challenge[]>;
  createUpload(challengeId: string, contentType: string, bytes: number): Promise<CreateUploadResponse>;
  upload(
    presign: CreateUploadResponse,
    body: Blob,
    onProgress?: (p: UploadProgress) => void,
  ): Promise<void>;
  createAnalysis(challengeId: string, key: string, durationS?: number): Promise<string>;
  getStatus(analysisId: string): Promise<AnalysisStatusResponse>;
  getResult(analysisId: string): Promise<LoadedResult>;
  getProgress(): Promise<ProgressResponse>;
}
