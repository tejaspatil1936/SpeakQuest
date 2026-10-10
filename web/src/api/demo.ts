/**
 * DEMO ADAPTER — static fixtures only.
 *
 * Used when no API is configured (`VITE_API_URL` unset) or `VITE_DEMO=1`.
 * Every result it returns is a pre-analysed *synthetic TTS* take produced by
 * `scripts/make_demo_fixtures.py` with the real pipeline. It never analyses
 * the visitor's recording, and the UI says so in a persistent banner. This
 * module is imported only by `api/index.ts`; the HTTP adapter never sees it.
 */
import { z } from "zod";
import { levelFor } from "../lib/levels";
import { ApiError } from "./errors";
import {
  AnalysisResult,
  ChallengeList,
  type AnalysisStatusResponse,
  type Challenge,
  type ProgressResponse,
} from "./schema";
import type { LoadedResult, SpeakQuestApi } from "./types";

const FixtureIndex = z.object({
  fixtures: z.array(
    z.object({
      analysisId: z.string(),
      challengeId: z.string(),
      clip: z.string(),
      overall: z.number(),
      codes: z.array(z.string()),
    }),
  ),
});
type FixtureEntry = z.infer<typeof FixtureIndex>["fixtures"][number];

export class DemoApi implements SpeakQuestApi {
  readonly mode = "demo" as const;
  private readonly base: string;
  private readonly fetchImpl: typeof fetch;
  private indexCache: Promise<FixtureEntry[]> | null = null;
  private readonly picks = new Map<string, number>();

  constructor(base = `${import.meta.env.BASE_URL}fixtures/`, fetchImpl?: typeof fetch) {
    this.base = base;
    this.fetchImpl = fetchImpl ?? ((...args) => globalThis.fetch(...args));
  }

  private async json<T extends z.ZodTypeAny>(schema: T, file: string): Promise<z.infer<T>> {
    const res = await this.fetchImpl(`${this.base}${file}`);
    if (!res.ok) throw new ApiError("DEMO_FIXTURE_MISSING", `Demo fixture ${file} is missing.`, res.status);
    return schema.parse(await res.json());
  }

  private index(): Promise<FixtureEntry[]> {
    this.indexCache ??= this.json(FixtureIndex, "index.json").then((i) => i.fixtures);
    return this.indexCache;
  }

  async listChallenges(): Promise<Challenge[]> {
    return (await this.json(ChallengeList, "challenges.json")).challenges;
  }

  createUpload(): never {
    throw new ApiError("DEMO_NO_UPLOAD", "The demo build does not upload recordings.");
  }

  upload(): never {
    throw new ApiError("DEMO_NO_UPLOAD", "The demo build does not upload recordings.");
  }

  /** Returns the next pre-analysed synthetic take for this challenge. */
  async createAnalysis(challengeId: string): Promise<string> {
    const options = (await this.index()).filter((f) => f.challengeId === challengeId);
    if (options.length === 0) {
      throw new ApiError(
        "DEMO_NO_FIXTURE",
        "The demo build has no pre-analysed take for this script. Try The Deadline, Weather Desk, Gallery Four or The Toast.",
      );
    }
    const n = this.picks.get(challengeId) ?? 0;
    this.picks.set(challengeId, n + 1);
    return options[n % options.length]!.analysisId;
  }

  async getStatus(analysisId: string): Promise<AnalysisStatusResponse> {
    const { result } = await this.getResult(analysisId);
    return {
      analysisId,
      challengeId: result.challenge_id,
      status: "DONE",
      stage: "DONE",
      createdAt: result.created_at,
      updatedAt: result.created_at,
      summary: {
        scores: result.scores,
        findingCount: result.findings.length,
        codes: [...new Set(result.findings.map((f) => f.code))],
      },
    };
  }

  async getResult(analysisId: string): Promise<LoadedResult> {
    if (!/^demo-[a-z0-9-]+$/.test(analysisId)) {
      throw new ApiError("NOT_FOUND", "That take is not part of the demo build.", 404);
    }
    const result = await this.json(AnalysisResult, `${analysisId}.result.json`);
    return {
      result,
      audioUrl: `${this.base}${analysisId}.ogg`,
      referenceAudioUrl: `${this.base}${result.challenge_id}.reference.ogg`,
    };
  }

  async getProgress(): Promise<ProgressResponse> {
    const fixtures = await this.index();
    const loaded = await Promise.all(fixtures.map((f) => this.getResult(f.analysisId)));
    const xp = Math.round(loaded.reduce((sum, l) => sum + l.result.take.duration_s, 0));
    const clean = loaded.find((l) => l.result.findings.length === 0);
    const first = loaded[0];
    return {
      xp,
      level: levelFor(xp),
      badges: [
        ...(first
          ? [{ id: "first-take", label: "First take", awarded_at: first.result.created_at, analysis_id: first.result.analysis_id }]
          : []),
        ...(clean
          ? [{ id: "clean-take", label: "Clean take", awarded_at: clean.result.created_at, analysis_id: clean.result.analysis_id }]
          : []),
      ],
      takes: loaded.map((l) => ({
        analysisId: l.result.analysis_id,
        challengeId: l.result.challenge_id,
        createdAt: l.result.created_at,
        status: "DONE" as const,
        durationS: l.result.take.duration_s,
        scores: l.result.scores,
        codes: [...new Set(l.result.findings.map((f) => f.code))],
      })),
    };
  }
}
