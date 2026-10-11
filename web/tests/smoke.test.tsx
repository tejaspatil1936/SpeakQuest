import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { App, ROUTER_FUTURE } from "../src/App";
import { DemoApi } from "../src/api/demo";
import { HttpApi } from "../src/api/http";
import type { SpeakQuestApi } from "../src/api/types";

// WaveSurfer needs a real canvas and audio decoding; jsdom has neither.
const seeks: number[] = [];
vi.mock("wavesurfer.js", () => ({
  default: {
    create: () => ({
      on: () => undefined,
      setOptions: () => undefined,
      destroy: () => undefined,
      setTime: (t: number) => seeks.push(t),
      playPause: () => Promise.resolve(),
      play: () => Promise.resolve(),
    }),
  },
}));
vi.mock("wavesurfer.js/dist/plugins/regions.esm.js", () => ({
  default: { create: () => ({ on: () => undefined, addRegion: () => undefined, clearRegions: () => undefined }) },
}));

const dir = resolve(__dirname, "../public/fixtures");
const fixtureFetch = (async (url: RequestInfo | URL) => {
  try {
    return new Response(readFileSync(resolve(dir, String(url).replace("/fixtures/", ""))));
  } catch {
    return new Response("", { status: 404 });
  }
}) as typeof fetch;

function renderAt(path: string, api: SpeakQuestApi = new DemoApi("/fixtures/", fixtureFetch)) {
  return render(
    <MemoryRouter initialEntries={[path]} future={ROUTER_FUTURE}>
      <App api={api} router={false} />
    </MemoryRouter>,
  );
}

test("challenge index lists cue cards and says it is a demo", async () => {
  renderAt("/");
  expect(await screen.findByRole("link", { name: /The Deadline/ })).toHaveAttribute("href", "/c/deadline");
  expect(screen.getByRole("note")).toHaveTextContent(/synthetic TTS/);
  expect(within(screen.getByRole("list", { name: "Scripts" })).getAllByRole("listitem").length).toBeGreaterThanOrEqual(6);
});

test("cue page shows the script and an honest message without a microphone", async () => {
  renderAt("/c/deadline");
  expect(await screen.findByRole("heading", { name: "The Deadline" })).toBeInTheDocument();
  expect(screen.getByText(/We ship the final build/)).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent(/can't|secure|microphone|MediaRecorder/i);
});

test("take page renders the playback and steps findings with the arrow keys", async () => {
  const api = new DemoApi("/fixtures/", fixtureFetch);
  const id = await api.createAnalysis("deadline");
  const { result } = await api.getResult(id);
  renderAt(`/take/${id}`, api);
  expect(await screen.findByLabelText(`Overall score ${result.scores.overall} out of 100`)).toBeInTheDocument();
  expect(screen.getByRole("table", { name: "Slate" })).toBeInTheDocument();
  const findings = screen.getByRole("list", { name: "Findings" });
  const buttons = within(findings).getAllByRole("button", { pressed: false });
  expect(buttons).toHaveLength(result.findings.length);

  await userEvent.keyboard("{ArrowRight}");
  await waitFor(() => expect(within(findings).getAllByRole("button", { pressed: true })).toHaveLength(1));
  expect(seeks.at(-1)).toBeCloseTo(Math.max(0, result.findings[0]!.start - 0.25), 3);
  await userEvent.keyboard("{ArrowRight}");
  expect(seeks.at(-1)).toBeCloseTo(Math.max(0, result.findings[1]!.start - 0.25), 3);
  await userEvent.keyboard("{ArrowLeft}{ArrowLeft}{ArrowLeft}");
  expect(seeks.at(-1)).toBeCloseTo(Math.max(0, result.findings[0]!.start - 0.25), 3);

  // Words are buttons with spoken labels; the plain-text toggle swaps the view.
  expect(screen.getAllByRole("button", { name: /flag/ }).length).toBeGreaterThan(0);
  await userEvent.click(screen.getByLabelText("Plain text"));
  expect(screen.getByLabelText("Plain transcript of your take")).toBeInTheDocument();
});

test("take page polls until done and shows the failure reason", async () => {
  let calls = 0;
  const base = { analysisId: "a1", challengeId: "deadline", createdAt: "2026-10-15T00:00:00Z", updatedAt: "2026-10-15T00:00:00Z" };
  const fetchImpl = (async (url: RequestInfo | URL) => {
    if (String(url).endsWith("/challenges")) return new Response(readFileSync(resolve(dir, "challenges.json")));
    calls++;
    const body =
      calls < 2
        ? { ...base, status: "RUNNING", stage: "TRANSCRIBE" }
        : { ...base, status: "FAILED", stage: "NORMALIZE", error: { code: "AUDIO_SILENT", message: "The recording is silent. Check your microphone.", stage: "NORMALIZE" } };
    return new Response(JSON.stringify(body), { status: 200 });
  }) as typeof fetch;
  renderAt("/take/a1", new HttpApi({ baseUrl: "https://api.test", fetchImpl, sessionId: () => "s" }));
  expect(await screen.findByRole("heading", { name: "In the edit." })).toBeInTheDocument();
  // The second poll (one 1.5 s interval later) reports the failure.
  expect(await screen.findByText("Code AUDIO_SILENT", {}, { timeout: 4000 })).toBeInTheDocument();
  expect(calls).toBe(2);
  expect(screen.getByRole("link", { name: "Record it again" })).toHaveAttribute("href", "/c/deadline");
});

test("me page shows air time, the ladder and labelled demo data", async () => {
  renderAt("/me");
  expect(await screen.findByText(/Demo data/)).toBeInTheDocument();
  expect(screen.getByRole("list", { name: "Levels" })).toHaveTextContent(/Rehearsal.*Read-through.*Dress.*Opening night.*Headliner/);
  expect(screen.getByRole("heading", { name: "Takes" })).toBeInTheDocument();
});

test("unknown routes show the dead-air page", async () => {
  renderAt("/nowhere");
  expect(await screen.findByRole("heading", { name: "Dead air." })).toBeInTheDocument();
});
