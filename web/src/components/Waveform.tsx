import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin, { type Region } from "wavesurfer.js/dist/plugins/regions.esm.js";
import type { Finding } from "../api/schema";
import { tokenColor } from "../lib/theme";

export interface WaveformHandle {
  seek(seconds: number): void;
  playPause(): void;
  play(): void;
}

const MIN_REGION_S = 0.12;

function paintRegion(region: Region, selected: boolean) {
  const tally = tokenColor("--tally");
  const el = region.element;
  el.style.backgroundColor = "transparent";
  el.style.backgroundImage = `repeating-linear-gradient(-45deg, ${tally} 0 1.5px, transparent 1.5px ${selected ? 4 : 7}px)`;
  el.style.borderLeft = `1px solid ${tally}`;
  el.style.borderRight = `1px solid ${tally}`;
  el.style.opacity = selected ? "0.9" : "0.55";
}

/**
 * The take's real audio, ink on paper. Findings are red hatching; the
 * playhead is a 2 px rule (system design §10.5).
 */
export const Waveform = forwardRef<
  WaveformHandle,
  {
    url: string;
    findings: Finding[];
    selectedId: string | null;
    onTime: (t: number) => void;
    onPlayingChange: (playing: boolean) => void;
    onRegionClick: (id: string) => void;
  }
>(function Waveform({ url, findings, selectedId, onTime, onPlayingChange, onRegionClick }, ref) {
  const container = useRef<HTMLDivElement>(null);
  const ws = useRef<WaveSurfer | null>(null);
  const regions = useRef<Map<string, Region>>(new Map());
  const callbacks = useRef({ onTime, onPlayingChange, onRegionClick });
  callbacks.current = { onTime, onPlayingChange, onRegionClick };
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [duration, setDuration] = useState(0);
  const selectedIdRef = useRef(selectedId);

  useImperativeHandle(
    ref,
    () => ({
      seek: (t) => ws.current?.setTime(Math.max(0, t)),
      playPause: () => void ws.current?.playPause(),
      play: () => void ws.current?.play(),
    }),
    [],
  );

  useEffect(() => {
    if (!container.current) return;
    const plugin = RegionsPlugin.create();
    const instance = WaveSurfer.create({
      container: container.current,
      url,
      height: 112,
      waveColor: tokenColor("--ink-2"),
      progressColor: tokenColor("--ink"),
      cursorColor: tokenColor("--ink"),
      cursorWidth: 2,
      barWidth: 2,
      barGap: 1,
      normalize: true,
      dragToSeek: true,
      plugins: [plugin],
    });
    ws.current = instance;
    const map = regions.current;
    instance.on("decode", (d) => {
      setDuration(d);
      plugin.clearRegions();
      map.clear();
      for (const f of findings) {
        const end = Math.max(f.end, f.start + MIN_REGION_S);
        const region = plugin.addRegion({ id: f.id, start: f.start, end, drag: false, resize: false, color: "transparent" });
        paintRegion(region, false);
        map.set(f.id, region);
      }
      setState("ready");
    });
    plugin.on("region-clicked", (region, e) => {
      e.stopPropagation();
      callbacks.current.onRegionClick(region.id);
    });
    instance.on("timeupdate", (t) => callbacks.current.onTime(t));
    instance.on("play", () => callbacks.current.onPlayingChange(true));
    instance.on("pause", () => callbacks.current.onPlayingChange(false));
    instance.on("finish", () => callbacks.current.onPlayingChange(false));
    instance.on("error", () => setState("error"));

    // Re-colour on theme switch: canvas can't read CSS variables.
    const observer = new MutationObserver(() => {
      instance.setOptions({
        waveColor: tokenColor("--ink-2"),
        progressColor: tokenColor("--ink"),
        cursorColor: tokenColor("--ink"),
      });
      map.forEach((r, id) => paintRegion(r, id === selectedIdRef.current));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      observer.disconnect();
      instance.destroy();
      ws.current = null;
      map.clear();
    };
    // Findings are fixed for a result; recreating the waveform per render would reload the audio.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  useEffect(() => {
    selectedIdRef.current = selectedId;
    regions.current.forEach((r, id) => paintRegion(r, id === selectedId));
  }, [selectedId, state]);

  return (
    <figure className="m-0">
      <div
        ref={container}
        className="min-h-[112px] border-y border-rule"
        role="img"
        aria-label={`Waveform of your take${duration ? `, ${duration.toFixed(1)} seconds` : ""}, with ${findings.length} flagged ranges hatched`}
      />
      <figcaption className="label mt-2 flex flex-wrap justify-between gap-x-6 gap-y-1 text-ink-2">
        <span>{state === "loading" ? "Loading audio…" : state === "error" ? "Audio unavailable" : "Your take"}</span>
        <span>Hatched = flagged · click to jump</span>
      </figcaption>
    </figure>
  );
});
