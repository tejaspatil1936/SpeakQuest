#!/usr/bin/env node
/**
 * Browser smoke test of the production build in demo mode, driving the
 * system Chrome over the DevTools protocol (no downloaded browsers).
 *
 * For every route at desktop (1280 px) and phone (375 px, emulated with
 * Emulation.setDeviceMetricsOverride — a headless window can't be narrower
 * than ~500 px) it waits for the app to render, checks for expected text,
 * checks there is no horizontal page overflow, and saves a full-page
 * screenshot to smoke-output/. Exits non-zero on any failure.
 *
 * Usage: npm run build && npm run smoke   (CHROME=/path/to/chrome to override)
 */
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const out = resolve(root, "smoke-output");
mkdirSync(out, { recursive: true });
const chromeBin = process.env.CHROME ?? "google-chrome";
const appPort = 4173;
const cdpPort = 9333;
const base = `http://localhost:${appPort}`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const ROUTES = [
  { name: "index", path: "/", expect: ["Read it.", "The Deadline", "Demo build"] },
  { name: "cue", path: "/c/deadline", expect: ["We ship the final build", "Open the mic"] },
  { name: "take", path: "/take/demo-deadline-flawed-2", expect: ["Take score", "Slate", "Director", "The playback"] },
  { name: "me", path: "/me", expect: ["Air time", "Rehearsal", "Headliner", "Stamps"] },
];
const SIZES = [
  { label: "1280", width: 1280, height: 900, mobile: false, scale: 1, scheme: "dark" },
  { label: "375", width: 375, height: 812, mobile: true, scale: 2, scheme: "dark" },
  { label: "1280-paper", width: 1280, height: 900, mobile: false, scale: 1, scheme: "light" },
];

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

const server = spawn(resolve(root, "node_modules/.bin/vite"), ["preview", "--port", String(appPort), "--strictPort"], {
  cwd: root,
  stdio: ["ignore", "pipe", "pipe"],
});
const profile = mkdtempSync(join(tmpdir(), "sq-smoke-"));
const chrome = spawn(
  chromeBin,
  [
    "--headless=new",
    `--remote-debugging-port=${cdpPort}`,
    `--user-data-dir=${profile}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-gpu",
    "--mute-audio",
    "--autoplay-policy=no-user-gesture-required",
    "about:blank",
  ],
  { stdio: ["ignore", "pipe", "pipe"] },
);

let failures = 0;
const report = [];
try {
  await waitForOutput(server, String(appPort), 20000);
  await waitForOutput(chrome, "DevTools listening", 20000);
  const version = await (await fetch(`http://127.0.0.1:${cdpPort}/json/version`)).json();
  const cdp = new Cdp(version.webSocketDebuggerUrl);
  await cdp.open();

  for (const size of SIZES) {
    for (const r of ROUTES) {
      const { targetId } = await cdp.send("Target.createTarget", { url: "about:blank" });
      const { sessionId } = await cdp.send("Target.attachToTarget", { targetId, flatten: true });
      const s = (m, p) => cdp.send(m, p, sessionId);
      await s("Page.enable");
      await s("Runtime.enable");
      await s("Emulation.setDeviceMetricsOverride", {
        width: size.width,
        height: size.height,
        deviceScaleFactor: size.scale,
        mobile: size.mobile,
      });
      await s("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: size.scheme }] });
      await s("Page.navigate", { url: `${base}${r.path}` });

      // Wait (up to 10 s) for every expected string to appear.
      let text = "";
      for (let i = 0; i < 40; i++) {
        const { result } = await s("Runtime.evaluate", { expression: "document.body.innerText", returnByValue: true });
        // innerText applies text-transform, so compare case-insensitively.
        text = String(result.value ?? "").toLowerCase();
        if (r.expect.every((t) => text.includes(t.toLowerCase()))) break;
        await sleep(250);
      }
      await sleep(1200); // let entrance motion and fonts settle
      const { result: m } = await s("Runtime.evaluate", {
        returnByValue: true,
        expression: `(() => {
          const vw = document.documentElement.clientWidth;
          const wide = [...document.querySelectorAll('body *')]
            .filter(el => { const b = el.getBoundingClientRect(); return b.width > 0 && b.right > vw + 1 && getComputedStyle(el).position !== 'fixed'; })
            .filter(el => !el.closest('[data-scroll-x]'))
            .slice(0, 5).map(el => el.tagName.toLowerCase() + '.' + (el.className.baseVal ?? el.className).toString().split(' ').slice(0,3).join('.'));
          return { scrollWidth: document.documentElement.scrollWidth, vw, height: document.documentElement.scrollHeight, wide,
                   waveform: document.querySelector('figcaption')?.innerText ?? null };
        })()`,
      });
      const missing = r.expect.filter((t) => !text.includes(t.toLowerCase()));
      const overflow = m.value.scrollWidth > m.value.vw || m.value.wide.length > 0;
      const height = Math.min(m.value.height, 6000);
      await s("Emulation.setDeviceMetricsOverride", {
        width: size.width,
        height,
        deviceScaleFactor: size.mobile ? 1 : 1,
        mobile: size.mobile,
      });
      await sleep(300);
      const shot = await s("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
      const file = resolve(out, `${r.name}-${size.label}.png`);
      writeFileSync(file, Buffer.from(shot.data, "base64"));
      await cdp.send("Target.closeTarget", { targetId });

      const ok = missing.length === 0 && !overflow;
      if (!ok) failures++;
      const line = `${ok ? "PASS" : "FAIL"} ${r.path} @${size.label}px` +
        (missing.length ? ` missing: ${missing.join(", ")}` : "") +
        (overflow ? ` horizontal overflow: scrollWidth=${m.value.scrollWidth} vw=${m.value.vw} ${m.value.wide.join(" ")}` : "") +
        (m.value.waveform ? ` [waveform: ${m.value.waveform.split("\n")[0]}]` : "");
      report.push(line);
      console.log(line);
    }
  }
  cdp.ws.close();
} catch (e) {
  failures++;
  console.error("smoke run failed:", e);
} finally {
  chrome.kill();
  server.kill();
  await sleep(300);
  rmSync(profile, { recursive: true, force: true });
}
writeFileSync(resolve(out, "report.txt"), report.join("\n") + "\n");
process.exit(failures ? 1 : 0);
