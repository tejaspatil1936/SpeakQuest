/**
 * Tailwind is used for layout utilities only. The palette is *replaced*, not
 * extended: the five On Air tokens are the only colours that exist, so a stray
 * `bg-purple-500` cannot compile into the bundle (system design §10.4, §10.7).
 *
 * @type {import('tailwindcss').Config}
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["selector", '[data-theme="booth"]'],
  theme: {
    colors: {
      transparent: "transparent",
      current: "currentColor",
      paper: "var(--paper)",
      ink: "var(--ink)",
      "ink-2": "var(--ink-2)",
      tally: "var(--tally)",
      rule: "var(--rule)",
    },
    fontFamily: {
      display: ["Archivo", "Arial Narrow", "sans-serif"],
      voice: ["Newsreader", "Georgia", "serif"],
      mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
    },
    fontSize: {
      mega: ["var(--t-mega)", { lineHeight: "0.88" }],
      xl: ["var(--t-xl)", { lineHeight: "0.88" }],
      l: ["var(--t-l)", { lineHeight: "1.25" }],
      m: ["1.5rem", { lineHeight: "1.2" }],
      body: ["var(--t-body)", { lineHeight: "1.5" }],
      sm: ["0.9375rem", { lineHeight: "1.45" }],
      label: ["var(--t-label)", { lineHeight: "1.3", letterSpacing: "0.08em" }],
    },
    borderRadius: {
      none: "0",
      card: "10px",
      full: "9999px",
    },
    boxShadow: { none: "none" },
    extend: {
      gridTemplateColumns: { 12: "repeat(12, minmax(0, 1fr))" },
      transitionTimingFunction: { out: "cubic-bezier(0.16, 1, 0.3, 1)" },
    },
  },
  plugins: [],
};
