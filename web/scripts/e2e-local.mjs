/**
 * End-to-end test of the real app against the local backend, in headless
 * Chrome with a fake microphone.
 *
 * Chrome's --use-file-for-fake-audio-capture plays a WAV into getUserMedia,
 * so the actual MediaRecorder → POST /uploads → presigned PUT → POST
 * /analyses → polling → playback path runs with a real voice recording.
 *
 * Preconditions (`make e2e` does all of this):
 *   - the local API is running at API_URL (default http://localhost:8787)
 *   - web/dist was built with VITE_API_URL pointing at it
 *   - MIC_WAV is a 16-bit PCM WAV: lead-in silence, then the take
 *
 * Usage: API_URL=… MIC_WAV=… TAKE_SECONDS=… node scripts/e2e-local.mjs
 */
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "smoke-output");
mkdirSync(out, { recursive: true });
const apiUrl = process.env.API_URL ?? "http://localhost:8787";
const micWav = process.env.MIC_WAV;
const takeSeconds = Number(process.env.TAKE_SECONDS ?? "10");
const challenge = process.env.CHALLENGE ?? "deadline";
const expectCodes = (process.env.EXPECT_CODES ?? "").split(",").filter(Boolean);
const chromeBin = process.env.CHROME ?? "google-chrome";
const appPort = 4174;
const cdpPort = 9334;
if (!micWav) throw new Error("MIC_WAV is required");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function waitForOutput(proc, needle, ms) {
  return new Promise((ok, fail) => {
    const timer = setTimeout(() => fail(new Error(`timed out waiting for "${needle}"`)), ms);
    const on = (d) => {
      if (String(d).includes(needle)) {
        clearTimeout(timer);
        ok();
      }
    };
    proc.stdout?.on("data", on);
    proc.stderr?.on("data", on);
  });
}

class Cdp {
  constructor(url) {
    this.ws = new WebSocket(url);
    this.id = 0;
    this.pending = new Map();
    this.ws.onmessage = (e) => {
      const msg = JSON.parse(String(e.data));
      const p = this.pending.get(msg.id);
      if (p) {
        this.pending.delete(msg.id);
        msg.error ? p.fail(new Error(msg.error.message)) : p.ok(msg.result);
      }
    };
  }
  open() {
    return new Promise((ok, fail) => {
      this.ws.onopen = ok;
      this.ws.onerror = fail;
    });
  }
  send(method, params = {}, sessionId) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params, sessionId }));
    return new Promise((ok, fail) => this.pending.set(id, { ok, fail }));
  }
}

const server = spawn(resolve(root, "node_modules/.bin/vite"), ["preview", "--host", "127.0.0.1", "--port", String(appPort), "--strictPort"], {
  cwd: root,
  stdio: ["ignore", "pipe", "pipe"],
});
const profile = mkdtempSync(join(tmpdir(), "sq-e2e-"));
const chrome = spawn(
  chromeBin,
  [
    "--headless=new",
    `--remote-debugging-port=${cdpPort}`,
    `--user-data-dir=${profile}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-gpu",
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    `--use-file-for-fake-audio-capture=${micWav}`,
    "--autoplay-policy=no-user-gesture-required",
    "about:blank",
  ],
  { stdio: ["ignore", "pipe", "pipe"] },
);

const steps = [];
const log = (msg) => {
  steps.push(msg);
  console.log(msg);
};

let ok = false;
let dump = async () => "";
try {
  await waitForOutput(server, String(appPort), 20000);
  await waitForOutput(chrome, "DevTools listening", 20000);
  const version = await (await fetch(`http://127.0.0.1:${cdpPort}/json/version`)).json();
  const cdp = new Cdp(version.webSocketDebuggerUrl);
  await cdp.open();
  const { targetId } = await cdp.send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await cdp.send("Target.attachToTarget", { targetId, flatten: true });
  const s = (m, p) => cdp.send(m, p, sessionId);
  await s("Page.enable");
  await s("Runtime.enable");
  await s("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const evaluate = async (expression) =>
    (await s("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })).result.value;
  const text = () => evaluate("document.body.innerText");
  dump = async () => `${await evaluate("location.href")}\n${(await text()).slice(0, 800)}`;
  const waitFor = async (predicate, label, ms = 30000) => {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      if (await evaluate(predicate)) return;
      await sleep(250);
    }
    throw new Error(`timed out: ${label}`);
  };
  const click = (expr, label) =>
    evaluate(`(() => { const el = ${expr}; if (!el) return false; el.click(); return true; })()`).then((done) => {
      if (!done) throw new Error(`no element: ${label}`);
    });
  // textContent, not innerText: the design system upper-cases labels with CSS.
  const byText = (t) => `[...document.querySelectorAll('button,a')].find(b => b.textContent.includes(${JSON.stringify(t)}))`;
  const has = (t) => `document.body.textContent.includes(${JSON.stringify(t)})`;
  const shot = async (name) => {
    const { data } = await s("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
    writeFileSync(join(out, name), Buffer.from(data, "base64"));
  };

  await s("Page.navigate", { url: `http://127.0.0.1:${appPort}/c/${challenge}` });
  await waitFor(has("Open the mic"), "cue page");
  if ((await text()).includes("DEMO BUILD")) throw new Error("app was built in demo mode");
  log("cue page loaded from the API");

  await click(byText("Open the mic"), "open mic");
  await waitFor(`!!document.querySelector('button[aria-pressed]')`, "tally button");
  log("microphone opened (fake capture device)");
  await click(`document.querySelector('button[aria-pressed]')`, "tally");
  await waitFor(`document.querySelector('button[aria-pressed]')?.getAttribute('aria-pressed') === 'true'`, "recording", 10000);
  log("count-in finished, recording");
  await sleep(takeSeconds * 1000);
  await click(`document.querySelector('button[aria-pressed]')`, "tally stop");
  await waitFor(has("Send take"), "send button");
  log(`stopped after ${takeSeconds}s`);
  await shot("e2e-recorded.png");

  await click(byText("Send take"), "send");
  await waitFor(`location.pathname.startsWith('/take/')`, "navigate to take", 30000);
  const analysisId = await evaluate("location.pathname.split('/').pop()");
  log(`uploaded and analysis started: ${analysisId}`);
  await waitFor(`/the playback/i.test(document.body.textContent) || /failed/i.test(document.body.textContent)`, "analysis result", 180000);
  await sleep(1500);
  const body = await text();
  await shot("e2e-result.png");
  if (!/the playback/i.test(body)) throw new Error(`analysis failed in the UI:\n${body.slice(0, 600)}`);
  const status = await (
    await fetch(`${apiUrl}/analyses/${analysisId}`, {
      headers: { "x-session-id": await evaluate("localStorage.getItem('sq.session')") },
    })
  ).json();
  log(`status from API: ${status.status} overall=${status.summary?.scores?.overall} codes=${status.summary?.codes?.join("+")}`);
  for (const code of expectCodes) {
    if (!status.summary?.codes?.includes(code)) throw new Error(`expected ${code} in ${status.summary?.codes}`);
  }
  // WaveSurfer v7 draws inside a shadow root.
  const waveOk = await evaluate(
    "[...document.querySelectorAll('*')].some(el => el.shadowRoot && [...el.shadowRoot.querySelectorAll('canvas')].some(c => c.width > 0))",
  );
  log(`waveform rendered from the uploaded recording: ${waveOk}`);
  if (!waveOk) throw new Error("waveform did not render");

  await s("Page.navigate", { url: `http://127.0.0.1:${appPort}/me` });
  await waitFor(`document.body.innerText.includes(${JSON.stringify(challenge.toUpperCase().replace("-", " "))}) || document.body.innerText.toLowerCase().includes('air time')`, "progress page");
  await sleep(1000);
  await shot("e2e-me.png");
  const me = await text();
  log(`progress page shows air time: ${/air time/i.test(me)}`);
  ok = true;
} catch (err) {
  console.error(`E2E FAILED: ${err.message}`);
  console.error(await dump().catch(() => "(no page)"));
} finally {
  writeFileSync(join(out, "e2e-report.txt"), steps.join("\n") + `\n${ok ? "PASS" : "FAIL"}\n`);
  chrome.kill();
  server.kill();
}
console.log(ok ? "E2E PASS" : "E2E FAIL");
process.exit(ok ? 0 : 1);
