import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { AnalysisResult, type Finding } from "../src/api/schema";
import { findingHeadline } from "../src/lib/copy";
import {
  buildReferenceLine,
  buildTakeLine,
  spokenLabel,
  wordAt,
  wordStyle,
} from "../src/lib/transcript";

const dir = resolve(__dirname, "../public/fixtures");
const fixtures = readdirSync(dir)
  .filter((f) => f.endsWith(".result.json"))
  .map((f) => AnalysisResult.parse(JSON.parse(readFileSync(resolve(dir, f), "utf8"))));

describe("wordStyle maps measurements onto type", () => {
  const base = { rate_ratio: 1, loudness_db: 0, pitch_st: 0, pause_before_ms: 0 };

  test("neutral measurements give neutral type", () => {
    expect(wordStyle(base)).toEqual({ wdth: 100, wght: 450, shiftEm: 0, pauseEm: 0 });
  });

  test("rushed words condense and dragged words expand, within the axis", () => {
    expect(wordStyle({ ...base, rate_ratio: 1.4 }).wdth).toBeLessThan(70);
    expect(wordStyle({ ...base, rate_ratio: 3 }).wdth).toBe(62);
    expect(wordStyle({ ...base, rate_ratio: 0.7 }).wdth).toBe(125);
  });

  test("loud is heavy, fading is hairline", () => {
    expect(wordStyle({ ...base, loudness_db: 6 }).wght).toBeGreaterThan(650);
    expect(wordStyle({ ...base, loudness_db: -12 }).wght).toBe(100);
  });

  test("pitch shifts the baseline by at most 0.15em, up for high pitch", () => {
    expect(wordStyle({ ...base, pitch_st: 4 }).shiftEm).toBe(-0.1);
    expect(wordStyle({ ...base, pitch_st: -20 }).shiftEm).toBe(0.15);
  });

  test("pauses become literal space; tiny gaps don't", () => {
    expect(wordStyle({ ...base, pause_before_ms: 970 }).pauseEm).toBeCloseTo(1.55, 2);
    expect(wordStyle({ ...base, pause_before_ms: 100 }).pauseEm).toBe(0);
    expect(wordStyle({ ...base, pause_before_ms: 9000 }).pauseEm).toBe(6);
  });

  test("missing measurements fall back to neutral", () => {
    expect(wordStyle({ rate_ratio: null, loudness_db: null, pitch_st: null, pause_before_ms: 0 })).toEqual({
      wdth: 100,
      wght: 450,
      shiftEm: 0,
      pauseEm: 0,
    });
  });
});

describe("buildTakeLine follows the alignment", () => {
  test.each(fixtures.map((f) => [f.analysis_id, f] as const))("%s renders every op once", (_id, result) => {
    const line = buildTakeLine(result);
    expect(line).toHaveLength(result.alignment.length);
    const counts = { word: 0, insert: 0, skip: 0 };
    line.forEach((item) => counts[item.type]++);
    expect(counts.word).toBe(result.alignment.filter((o) => o.op === "match" || o.op === "sub").length);
    expect(counts.insert).toBe(result.alignment.filter((o) => o.op === "ins").length);
    expect(counts.skip).toBe(result.alignment.filter((o) => o.op === "del").length);
    expect(new Set(line.map((i) => i.key)).size).toBe(line.length);
  });

  test("skips attach to their SKIP finding and inserts keep their word", () => {
    const base = fixtures[0]!;
    const synthetic = AnalysisResult.parse({
      ...base,
      alignment: [
        { op: "match", script_index: 0, take_index: 0 },
        { op: "ins", take_index: 1 },
        { op: "del", script_index: 1 },
      ],
      take: {
        ...base.take,
        words: [
          { ...base.take.words[0]!, index: 0, finding_ids: [] },
          { ...base.take.words[0]!, index: 1, text: "um", norm: "um", kind: "filler", script_index: null, finding_ids: ["f1"] },
        ],
      },
      findings: [
        { id: "f1", code: "FILLER", dimension: "accuracy", start: 1, end: 1.3, words: ["um"], evidence: { count: 1, kind: "filler" }, severity: 1, rubric_version: "1.0.0" },
        { id: "f2", code: "SKIP", dimension: "accuracy", start: 1.3, end: 1.3, words: ["x"], evidence: { skipped_words: 1 }, severity: 1, rubric_version: "1.0.0", script_span: [1, 1] },
      ],
    });
    const line = buildTakeLine(synthetic);
    expect(line.map((i) => i.type)).toEqual(["word", "insert", "skip"]);
    expect(line[1]!.findings.map((f) => f.id)).toEqual(["f1"]);
    expect(line[2]!.findings.map((f) => f.id)).toEqual(["f2"]);
  });

  test("reference line is in spoken order", () => {
    const ref = buildReferenceLine(fixtures[0]!);
    expect(ref.map((w) => w.start)).toEqual([...ref.map((w) => w.start)].sort((a, b) => a - b));
  });
});

describe("labels and lookup", () => {
  const hes = { id: "f3", code: "HESITATE", evidence: { pause_ms: 970, reference_pause_ms: 140 }, words: ["before", "deadline"] } as unknown as Finding;

  test("screen readers hear the measurement and the flag", () => {
    expect(spokenLabel("deadline", 970, [hes])).toBe("deadline, 0.97 second pause, hesitation flag");
    expect(spokenLabel("the", 40, [])).toBe("the");
  });

  test("wordAt finds the sounding word", () => {
    const words = [
      { start: 0, end: 0.5 },
      { start: 0.6, end: 1 },
    ];
    expect(wordAt(words, 0.7)).toBe(1);
    expect(wordAt(words, 0.55)).toBe(-1);
  });

  test("headlines quote evidence in the director's voice", () => {
    expect(findingHeadline(hes)).toBe("You stopped for 0.97 s before 'deadline' — the reference doesn't.");
    const rush = { code: "RUSH", evidence: { rate_ratio: 1.42 }, words: ["before", "the", "deadline"] } as unknown as Finding;
    expect(findingHeadline(rush)).toBe("You rushed 'before the deadline' — 1.4× the reference pace.");
    for (const result of fixtures) {
      for (const f of result.findings) expect(findingHeadline(f).length).toBeGreaterThan(8);
    }
  });
});
