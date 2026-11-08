import { useSyncExternalStore } from "react";

/**
 * Light or dark mode. The page's colours are keyed off `data-theme` on <html> (styles.css).
 * Until someone presses the toggle, the page follows the system setting; after that their
 * choice is remembered in this browser. index.html sets the attribute before the first paint
 * with the same rules, so a dark page never flashes white while the app loads.
 */
export type Theme = "light" | "dark";

const STORAGE_KEY = "tujya-theme"; // also read by the inline script in index.html
const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
const listeners = new Set<() => void>();

function savedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null; // storage blocked: just follow the system
  }
}

function preferredTheme(): Theme {
  return savedTheme() ?? (systemDark.matches ? "dark" : "light");
}

function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function apply(theme: Theme) {
  if (theme === currentTheme()) return;
  const update = () => {
    document.documentElement.dataset.theme = theme;
    listeners.forEach((listener) => listener());
  };
  // A short cross-fade where the browser supports it, unless the visitor asked for less motion.
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (document.startViewTransition && !reduceMotion) document.startViewTransition(update);
  else update();
}

export function setTheme(theme: Theme) {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Not remembered, but still applied for this visit.
  }
  apply(theme);
}

// In case index.html's script did not run (it always should).
if (!document.documentElement.dataset.theme) {
  document.documentElement.dataset.theme = preferredTheme();
}

// Follow the system setting while no choice is saved.
systemDark.addEventListener("change", () => {
  if (!savedTheme()) apply(preferredTheme());
});

// Keep other open tabs in step.
window.addEventListener("storage", (event) => {
  if (event.key === STORAGE_KEY) apply(preferredTheme());
});

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, currentTheme);
  const toggle = () => setTheme(theme === "dark" ? "light" : "dark");
  return { theme, setTheme, toggle };
}
