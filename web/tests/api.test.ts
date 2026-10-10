import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createApi } from "../src/api";
import { DemoApi } from "../src/api/demo";
import { ApiError, describeError } from "../src/api/errors";
import { HttpApi } from "../src/api/http";
import { getSessionId } from "../src/api/session";
import { uploadWithRetry, type XhrLike } from "../src/api/upload";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const status = {
  analysisId: "a1",
  challengeId: "deadline",
  status: "RUNNING",
  stage: "TRANSCRIBE",
  createdAt: "2026-10-15T00:00:00Z",
  updatedAt: "2026-10-15T00:00:02Z",
};

function api(fetchImpl: typeof fetch) {
  return new HttpApi({ baseUrl: "https://api.test/", fetchImpl, sessionId: () => "sess-1" });
}

describe("HttpApi", () => {
  test("sends the session header and validates the body", async () => {
    const fetchImpl = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      expect(new Headers(init?.headers).get("x-session-id")).toBe("sess-1");
      return json(200, status);
    });
    const res = await api(fetchImpl as unknown as typeof fetch).getStatus("a1");
    expect(res.stage).toBe("TRANSCRIBE");
    expect(fetchImpl.mock.calls[0]![0]).toBe("https://api.test/analyses/a1");
  });

  test("surfaces API error envelopes with code and stage", async () => {
    const fetchImpl = async () =>
      json(422, { error: { code: "VALIDATION", message: "bytes too large", stage: null } });
    await expect(api(fetchImpl).createUpload("deadline", "audio/webm", 1)).rejects.toMatchObject({
      code: "VALIDATION",
      status: 422,
      retryable: false,
    });
  });

  test("maps 429 without a body to a retryable THROTTLED error", async () => {
    const err = await api(async () => new Response("", { status: 429 })).listChallenges().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("THROTTLED");
    expect(err.retryable).toBe(true);
    expect(describeError(err)).toMatch(/Too many takes/);
  });

  test("network failures are retryable NETWORK errors", async () => {
    const err = await api(async () => {
      throw new TypeError("Failed to fetch");
    })
      .getProgress()
      .catch((e) => e);
    expect(err.code).toBe("NETWORK");
    expect(err.retryable).toBe(true);
  });

  test("rejects bodies that break the contract", async () => {
    const err = await api(async () => json(200, { ...status, stage: "DANCING" }))
      .getStatus("a1")
      .catch((e) => e);
    expect(err.code).toBe("BAD_RESPONSE");
  });

  test("getResult follows the presigned result URL without the session header", async () => {
    const fixture = JSON.parse(
      readFileSync(resolve(__dirname, "../public/fixtures/demo-deadline-flawed-2.result.json"), "utf8"),
    );
    const calls: string[] = [];
    const fetchImpl = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      calls.push(String(url));
      if (String(url).endsWith("/result")) {
        return json(200, { resultUrl: "https://s3.test/r.json?sig=1", audioUrl: "https://s3.test/a.webm", expiresIn: 600 });
      }
      expect(new Headers(init?.headers).has("x-session-id")).toBe(false);
      return json(200, fixture);
    });
    const loaded = await api(fetchImpl as unknown as typeof fetch).getResult("a1");
    expect(calls).toEqual(["https://api.test/analyses/a1/result", "https://s3.test/r.json?sig=1"]);
    expect(loaded.referenceAudioUrl).toBeNull();
    expect(loaded.result.findings.length).toBeGreaterThanOrEqual(0);
  });
});

describe("uploadWithRetry", () => {
  const presign = {
    uploadUrl: "https://s3.test/up",
    key: "uploads/s/a.webm",
    method: "PUT" as const,
    headers: { "Content-Type": "audio/webm" },
    expiresIn: 300,
  };

  function fakeXhr(outcomes: Array<number | "error" | "timeout">) {
    const made: Array<XhrLike & { headers: Record<string, string> }> = [];
    const factory = () => {
      const outcome = outcomes[made.length] ?? 200;
      const xhr = {
        headers: {} as Record<string, string>,
        status: 0,
        timeout: 0,
        upload: { onprogress: null },
        onload: null,
        onerror: null,
        ontimeout: null,
        open: vi.fn(),
        abort: vi.fn(),
        setRequestHeader(name: string, value: string) {
          this.headers[name] = value;
        },
        send(body: Blob) {
          queueMicrotask(() => {
            this.upload.onprogress?.({ loaded: body.size / 2, total: body.size, lengthComputable: true });
            if (outcome === "error") this.onerror?.();
            else if (outcome === "timeout") this.ontimeout?.();
            else {
              this.status = outcome;
              this.onload?.();
            }
          });
        },
      } as XhrLike & { headers: Record<string, string> };
      made.push(xhr);
      return xhr;
    };
    return { factory, made };
  }

  const body = new Blob([new Uint8Array(1000)], { type: "audio/webm" });

  test("retries transient failures with backoff and reports progress", async () => {
    const { factory, made } = fakeXhr(["error", 503, 200]);
    const sleeps: number[] = [];
    const progress: number[] = [];
    await uploadWithRetry(presign, body, {
      makeXhr: factory,
      sleep: async (ms) => void sleeps.push(ms),
      backoffMs: 100,
      onProgress: (p) => progress.push(p.attempt),
    });
    expect(made).toHaveLength(3);
    expect(sleeps).toEqual([100, 200]);
    expect(made[2]!.headers["Content-Type"]).toBe("audio/webm");
    expect(progress).toContain(3);
  });

  test("does not retry a 403 (expired or mismatched signature)", async () => {
    const { factory, made } = fakeXhr([403]);
    await expect(uploadWithRetry(presign, body, { makeXhr: factory, sleep: async () => {} })).rejects.toMatchObject({
      code: "UPLOAD_REJECTED",
    });
    expect(made).toHaveLength(1);
  });

  test("gives up after the attempt budget", async () => {
    const { factory, made } = fakeXhr(["timeout", "timeout", "timeout", 200]);
    await expect(
      uploadWithRetry(presign, body, { makeXhr: factory, sleep: async () => {}, attempts: 3 }),
    ).rejects.toMatchObject({ code: "TIMEOUT" });
    expect(made).toHaveLength(3);
  });
});

describe("session and adapter selection", () => {
  test("session id is a stable UUID", () => {
    const store = new Map<string, string>();
    const storage = {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
    } as unknown as Storage;
    const a = getSessionId(storage);
    expect(a).toMatch(/^[0-9a-f-]{36}$/);
    expect(getSessionId(storage)).toBe(a);
  });

  test("demo mode when no API URL or when forced", () => {
    expect(createApi({}).mode).toBe("demo");
    expect(createApi({ VITE_API_URL: "https://x", VITE_DEMO: "1" }).mode).toBe("demo");
    expect(createApi({ VITE_API_URL: "https://x" }).mode).toBe("http");
  });
});

describe("DemoApi", () => {
  const dir = resolve(__dirname, "../public/fixtures");
  const fetchImpl = (async (url: RequestInfo | URL) => {
    try {
      return new Response(readFileSync(resolve(dir, String(url).replace("/fixtures/", ""))));
    } catch {
      return new Response("", { status: 404 });
    }
  }) as typeof fetch;
  const demo = () => new DemoApi("/fixtures/", fetchImpl);

  test("serves fixture results for challenges that have them", async () => {
    const api = demo();
    const id = await api.createAnalysis("deadline");
    expect(id).toMatch(/^demo-deadline/);
    const status = await api.getStatus(id);
    expect(status.status).toBe("DONE");
    const loaded = await api.getResult(id);
    expect(loaded.audioUrl).toBe(`/fixtures/${id}.ogg`);
  });

  test("explains when a challenge has no fixture and never uploads", async () => {
    await expect(demo().createAnalysis("closing-argument")).rejects.toMatchObject({ code: "DEMO_NO_FIXTURE" });
    expect(() => demo().createUpload()).toThrow(ApiError);
  });

  test("derives labelled demo progress from fixtures", async () => {
    const progress = await demo().getProgress();
    expect(progress.takes.length).toBeGreaterThan(0);
    expect(progress.xp).toBeGreaterThan(0);
  });
});
