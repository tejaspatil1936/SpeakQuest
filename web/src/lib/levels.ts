/** The level ladder (system design §10.5). XP is air time in seconds. */
export const LEVELS = [
  { name: "Rehearsal", floor_s: 0 },
  { name: "Read-through", floor_s: 120 },
  { name: "Dress", floor_s: 360 },
  { name: "Opening night", floor_s: 900 },
  { name: "Headliner", floor_s: 1800 },
] as const;

export function levelFor(xp: number) {
  let index = 0;
  LEVELS.forEach((l, i) => {
    if (xp >= l.floor_s) index = i;
  });
  const current = LEVELS[index]!;
  const next = LEVELS[index + 1];
  return {
    index,
    name: current.name,
    floor_s: current.floor_s,
    next_name: next?.name ?? null,
    next_at_s: next?.floor_s ?? null,
  };
}

/** "4 min 05 s" style air-time label. */
export function airTime(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const m = Math.floor(s / 60);
  const rest = String(s % 60).padStart(2, "0");
  return m > 0 ? `${m} min ${rest} s` : `${s % 60} s`;
}
