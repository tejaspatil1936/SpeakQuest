/**
 * Runtime contracts for every payload the app receives.
 *
 * These mirror `services/worker/speakquest/contracts.py`, which is the source
 * of truth. `tests/contract.test.ts` compares every object below with the
 * exported JSON Schema (`contracts/schema.json`): a field added, removed or
 * made optional on either side fails the test suite.
 */
import { z } from "zod";

const opt = <T extends z.ZodTypeAny>(schema: T) => schema.nullable().optional();

export const FLAW_CODES = ["RUSH", "DRAG", "HESITATE", "MONO", "FADE", "SKIP", "FILLER"] as const;
export const DIMENSIONS = ["pace", "pauses", "pitch", "volume", "accuracy"] as const;
export const STAGES = [
  "QUEUED",
  "NORMALIZE",
  "TRANSCRIBE",
  "ANALYZE",
  "EXPLAIN",
  "PERSIST",
  "DONE",
] as const;

export const FlawCode = z.enum(FLAW_CODES);
export const Dimension = z.enum(DIMENSIONS);
export const AnalysisStatus = z.enum(["QUEUED", "RUNNING", "DONE", "FAILED"]);
export const Stage = z.enum(STAGES);
const seconds = z.number().min(0);

export const AlignOp = z.object({
  op: z.enum(["match", "sub", "ins", "del"]),
  script_index: opt(z.number().int()),
  take_index: opt(z.number().int()),
});

export const ScriptToken = z.object({
  index: z.number().int().min(0),
  norm: z.string(),
  display: z.string(),
  phrase: z.number().int().min(0),
});

export const ScriptInfo = z.object({
  text: z.string(),
  tokens: z.array(ScriptToken),
  phrase_count: z.number().int().min(0),
});

export const WordMeasure = z.object({
  index: z.number().int().min(0),
  text: z.string(),
  norm: z.string(),
  start: seconds,
  end: seconds,
  kind: z.enum(["match", "sub", "filler", "repeat", "insert"]),
  script_index: opt(z.number().int()),
  syllables: z.number().int().min(0),
  rate_ratio: opt(z.number()),
  loudness_db: opt(z.number()),
  pitch_st: opt(z.number()),
  pause_before_ms: z.number().int().min(0).default(0),
  finding_ids: z.array(z.string()).default([]),
});

export const Pause = z.object({
  start: seconds,
  end: seconds,
  ms: z.number().int().min(0),
  before_word: z.number().int().min(0),
});

export const Vocalization = z.object({ start: seconds, end: seconds, ms: z.number().int().min(0) });

export const PhraseStat = z.object({
  phrase: z.number().int().min(0),
  start: seconds,
  end: seconds,
  pitch_sd_st: opt(z.number()),
  voiced_frames: z.number().int().min(0).default(0),
});

export const TakeAnalysis = z.object({
  duration_s: seconds,
  words: z.array(WordMeasure),
  pauses: z.array(Pause),
  phrases: z.array(PhraseStat),
  vocalizations: z.array(Vocalization).default([]),
  syllables_per_s: z.number().min(0),
  rate_ratio_global: opt(z.number()),
  pitch_median_hz: opt(z.number()),
  loudness_mean_db: opt(z.number()),
});

export const Finding = z.object({
  id: z.string().regex(/^f\d+$/),
  code: FlawCode,
  dimension: Dimension,
  start: seconds,
  end: seconds,
  words: z.array(z.string()),
  evidence: z.record(z.union([z.number(), z.string()])),
  severity: z.number().int().min(1).max(3),
  rubric_version: z.string(),
  script_span: opt(z.tuple([z.number().int(), z.number().int()])),
});

const score = z.number().int().min(0).max(100);
export const Scores = z.object({
  pace: score,
  pauses: score,
  pitch: score,
  volume: score,
  accuracy: score,
  overall: score,
});

export const Penalty = z.object({
  finding_id: z.string(),
  dimension: Dimension,
  points: z.number().min(0),
});

export const CoachingItem = z.object({
  finding_id: z.string(),
  headline: z.string().min(1).max(160),
  why: z.string().min(1).max(600),
  drill: z.string().min(1).max(600),
});

export const Coaching = z.object({
  source: z.enum(["bedrock", "template"]),
  model_id: opt(z.string()),
  items: z.array(CoachingItem),
  attempts: z.number().int().min(0),
  rejections: z.array(z.string()).default([]),
});

export const Versions = z.object({
  rubric_version: z.string(),
  worker_image_digest: z.string(),
  transcribe_language: z.string(),
  aligner: z.string(),
  model_id: opt(z.string()),
});

export const AnalysisResult = z.object({
  schema_version: z.literal("1").default("1"),
  analysis_id: z.string(),
  challenge_id: z.string(),
  created_at: z.string(),
  versions: Versions,
  script: ScriptInfo,
  take: TakeAnalysis,
  reference: TakeAnalysis,
  alignment: z.array(AlignOp),
  findings: z.array(Finding),
  penalties: z.array(Penalty),
  scores: Scores,
  coaching: opt(Coaching),
  warnings: z.array(z.string()).default([]),
});

// ---------------------------------------------------------------- API envelopes

export const Challenge = z.object({
  id: z.string().regex(/^[a-z0-9-]{3,48}$/),
  title: z.string(),
  script: z.string(),
  difficulty: z.union([z.literal(1), z.literal(2), z.literal(3)]),
  flaw_targets: z.array(FlawCode),
  language: z.string().default("en-US"),
  cue: z.string(),
  reference_duration_s: opt(z.number()),
  reference_audio_url: opt(z.string()),
  reference_ready: z.boolean().default(false),
});

export const ChallengeList = z.object({ challenges: z.array(Challenge) });

export const CreateUploadRequest = z.object({
  challengeId: z.string(),
  contentType: z.string(),
  bytes: z.number().int().positive(),
});

export const CreateUploadResponse = z.object({
  uploadUrl: z.string().url(),
  key: z.string(),
  method: z.literal("PUT").default("PUT"),
  headers: z.record(z.string()),
  expiresIn: z.number().int(),
});

export const CreateAnalysisRequest = z.object({
  challengeId: z.string(),
  key: z.string(),
  durationS: opt(z.number().min(0)),
});

export const CreateAnalysisResponse = z.object({ analysisId: z.string() });

export const ErrorInfo = z.object({
  code: z.string(),
  message: z.string(),
  stage: opt(z.string()),
});

export const ErrorResponse = z.object({ error: ErrorInfo });

export const AnalysisSummary = z.object({
  scores: Scores,
  findingCount: z.number().int(),
  codes: z.array(FlawCode),
});

export const AnalysisStatusResponse = z.object({
  analysisId: z.string(),
  challengeId: z.string(),
  status: AnalysisStatus,
  stage: Stage,
  createdAt: z.string(),
  updatedAt: z.string(),
  summary: opt(AnalysisSummary),
  error: opt(ErrorInfo),
});

export const AnalysisResultResponse = z.object({
  resultUrl: z.string(),
  audioUrl: z.string(),
  referenceAudioUrl: opt(z.string()),
  expiresIn: z.number().int(),
});

export const Level = z.object({
  index: z.number().int().min(0),
  name: z.string(),
  floor_s: z.number().int().min(0),
  next_name: opt(z.string()),
  next_at_s: opt(z.number().int()),
});

export const Badge = z.object({
  id: z.string(),
  label: z.string(),
  awarded_at: z.string(),
  analysis_id: opt(z.string()),
});

export const TakeSummary = z.object({
  analysisId: z.string(),
  challengeId: z.string(),
  createdAt: z.string(),
  status: AnalysisStatus,
  durationS: opt(z.number()),
  scores: opt(Scores),
  codes: z.array(FlawCode).default([]),
});

export const ProgressResponse = z.object({
  xp: z.number().int().min(0),
  level: Level,
  badges: z.array(Badge),
  takes: z.array(TakeSummary),
});

/** Every object schema by its JSON Schema `$defs` name (used by the contract test). */
export const CONTRACTS = {
  AlignOp,
  AnalysisResult,
  AnalysisResultResponse,
  AnalysisStatusResponse,
  AnalysisSummary,
  Badge,
  Challenge,
  ChallengeList,
  Coaching,
  CoachingItem,
  CreateAnalysisRequest,
  CreateAnalysisResponse,
  CreateUploadRequest,
  CreateUploadResponse,
  ErrorInfo,
  ErrorResponse,
  Finding,
  Level,
  Pause,
  Penalty,
  PhraseStat,
  ProgressResponse,
  Scores,
  ScriptInfo,
  ScriptToken,
  TakeAnalysis,
  TakeSummary,
  Versions,
  Vocalization,
  WordMeasure,
} as const;

export type FlawCode = z.infer<typeof FlawCode>;
export type Dimension = z.infer<typeof Dimension>;
export type Stage = z.infer<typeof Stage>;
export type AnalysisStatus = z.infer<typeof AnalysisStatus>;
export type AlignOp = z.infer<typeof AlignOp>;
export type ScriptToken = z.infer<typeof ScriptToken>;
export type WordMeasure = z.infer<typeof WordMeasure>;
export type TakeAnalysis = z.infer<typeof TakeAnalysis>;
export type Finding = z.infer<typeof Finding>;
export type Scores = z.infer<typeof Scores>;
export type Coaching = z.infer<typeof Coaching>;
export type CoachingItem = z.infer<typeof CoachingItem>;
export type AnalysisResult = z.infer<typeof AnalysisResult>;
export type Challenge = z.infer<typeof Challenge>;
export type CreateUploadResponse = z.infer<typeof CreateUploadResponse>;
export type AnalysisStatusResponse = z.infer<typeof AnalysisStatusResponse>;
export type AnalysisResultResponse = z.infer<typeof AnalysisResultResponse>;
export type ErrorInfo = z.infer<typeof ErrorInfo>;
export type ProgressResponse = z.infer<typeof ProgressResponse>;
export type Badge = z.infer<typeof Badge>;
export type TakeSummary = z.infer<typeof TakeSummary>;
export type Level = z.infer<typeof Level>;
