import { useCallback, useEffect, useState } from "react";

export type Theme = "paper" | "booth";
const KEY = "sq.theme";

function current(): Theme {
  return document.documentElement.dataset.theme === "booth" ? "booth" : "paper";
}

/** Paper (light) / Booth (dark). Defaults to the OS preference until chosen. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(current);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((t) => {
      const next = t === "paper" ? "booth" : "paper";
      try {
        localStorage.setItem(KEY, next);
      } catch {
        /* storage blocked: theme still applies for this visit */
      }
      return next;
    });
  }, []);

  return [theme, toggle];
}

/** Read a token's computed colour (canvas libraries can't take CSS variables). */
export function tokenColor(name: "--paper" | "--ink" | "--ink-2" | "--tally" | "--rule"): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#121212";
}
