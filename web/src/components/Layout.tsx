import type { ReactNode } from "react";
import { NavLink, Link } from "react-router-dom";
import { useApi } from "../api";
import { useTheme } from "../lib/theme";

function NavItem({ to, children }: { to: string; children: ReactNode }) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        `label inline-flex min-h-[44px] items-center px-2 sm:px-3 ${isActive ? "underline decoration-2 underline-offset-[6px]" : "hover:underline"}`
      }
    >
      {children}
    </NavLink>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const api = useApi();
  const [theme, toggle] = useTheme();
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:bg-paper focus:p-2">
        Skip to content
      </a>
      <header className="border-b-2 border-rule px-[var(--gutter)]">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-3">
          <Link to="/" className="flex items-baseline gap-3" aria-label="SpeakQuest, all scripts">
            <span className="display text-m uppercase tracking-tight sm:text-[2rem]">SpeakQuest</span>
            <span className="label hidden text-ink-2 sm:inline">Speech coaching · take by take</span>
          </Link>
          <nav aria-label="Main" className="-mr-2 flex items-center">
            <NavItem to="/">Scripts</NavItem>
            <NavItem to="/me">Takes</NavItem>
            <button
              type="button"
              onClick={toggle}
              className="label ml-1 min-h-[44px] border border-rule px-3"
              aria-label={`Switch to ${theme === "paper" ? "Booth (dark)" : "Paper (light)"} theme`}
            >
              {theme === "paper" ? "Booth" : "Paper"}
            </button>
          </nav>
        </div>
      </header>
      {api.mode === "demo" && (
        <div role="note" className="label bg-ink px-[var(--gutter)] py-2 text-paper">
          Demo build — results are pre-analysed synthetic TTS takes. Your recording stays in your browser and is not
          analysed.
        </div>
      )}
      <main id="main" className="flex-1">
        {children}
      </main>
      <footer className="rule-t mt-16 px-[var(--gutter)] py-6">
        <p className="label flex flex-wrap gap-x-6 gap-y-1 text-ink-2">
          <span>Scores are measured, not guessed: deterministic rules, versioned rubric.</span>
          <span>Coaching text is written by a model from those measurements only.</span>
        </p>
      </footer>
    </div>
  );
}
