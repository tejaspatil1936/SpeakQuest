import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { z } from "zod";
import {
  AnalysisResult,
  ChallengeList,
  CONTRACTS,
  DIMENSIONS,
  FLAW_CODES,
  STAGES,
} from "../src/api/schema";

const ROOT = resolve(__dirname, "..", "..");
const FIXTURES = resolve(__dirname, "..", "public", "fixtures");

interface JsonSchemaObject {
  properties?: Record<string, unknown>;
  required?: string[];
  enum?: string[];
}
const jsonSchema = JSON.parse(readFileSync(resolve(ROOT, "contracts", "schema.json"), "utf8")) as {
  $defs: Record<string, JsonSchemaObject>;
};

describe("Zod contracts mirror contracts/schema.json", () => {
  const defs = jsonSchema.$defs;
  const objectDefs = Object.entries(defs).filter(([, d]) => d.properties);

  test("every JSON Schema object has a Zod counterpart and vice versa", () => {
    expect(Object.keys(CONTRACTS).sort()).toEqual(objectDefs.map(([name]) => name).sort());
  });

  test.each(Object.entries(CONTRACTS))("%s has identical keys and required-ness", (name, schema) => {
    const def = defs[name];
    expect(def, `${name} missing from schema.json`).toBeDefined();
    const shape = (schema as z.AnyZodObject).shape as Record<string, z.ZodTypeAny>;
    expect(Object.keys(shape).sort()).toEqual(Object.keys(def!.properties ?? {}).sort());
    const required = Object.entries(shape)
      .filter(([, s]) => !s.isOptional())
      .map(([k]) => k)
      .sort();
    expect(required).toEqual([...(def!.required ?? [])].sort());
  });

  test("enumerations match", () => {
    const enumOf = (fragment: string) =>
      Object.values(defs)
        .flatMap((d) => Object.values(d.properties ?? {}))
        .map((p) => JSON.stringify(p))
        .find((p) => p.includes(fragment));
    expect(enumOf('"RUSH"')).toContain(JSON.stringify([...FLAW_CODES]));
    expect(enumOf('"pauses"')).toContain(JSON.stringify([...DIMENSIONS]));
    expect(enumOf('"NORMALIZE"')).toContain(JSON.stringify([...STAGES]));
  });
});

describe("fixtures parse with the runtime contracts", () => {
  const files = readdirSync(FIXTURES).filter((f) => f.endsWith(".result.json"));

  test("there are result fixtures", () => {
    expect(files.length).toBeGreaterThan(0);
  });

  test.each(files)("%s is a valid AnalysisResult", (file) => {
    const raw: unknown = JSON.parse(readFileSync(resolve(FIXTURES, file), "utf8"));
    const parsed = AnalysisResult.safeParse(raw);
    expect(parsed.success, parsed.success ? "" : parsed.error.message).toBe(true);
  });

  test("challenges.json is a valid ChallengeList", () => {
    const raw: unknown = JSON.parse(readFileSync(resolve(FIXTURES, "challenges.json"), "utf8"));
    const parsed = ChallengeList.parse(raw);
    expect(parsed.challenges.length).toBeGreaterThanOrEqual(6);
  });
});
