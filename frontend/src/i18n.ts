import { useSyncExternalStore } from "react";
import en, { type Messages } from "./locales/en";
import fr from "./locales/fr";
import ru from "./locales/ru";

/**
 * The interface language: English, French or Russian. Until someone picks one in the
 * language menu, the browser's own language decides (English when it is none of the three);
 * the choice is then remembered in this browser, like the dark mode toggle (theme.ts).
 *
 * Components read their texts with `useT()`, which also re-renders them when the language
 * changes. Code outside React (the API client, image tools) calls `messages()` instead.
 */
export type Lang = "en" | "fr" | "ru";
export type { Messages };

export const LANGUAGES: { code: Lang; name: string }[] = [
  { code: "en", name: "English" },
  { code: "fr", name: "Français" },
  { code: "ru", name: "Русский" },
];

const MESSAGES: Record<Lang, Messages> = { en, fr, ru };
const STORAGE_KEY = "tujya-lang";
const listeners = new Set<() => void>();

function isLang(value: unknown): value is Lang {
  return value === "en" || value === "fr" || value === "ru";
}

function savedLang(): Lang | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return isLang(value) ? value : null;
  } catch {
    return null; // storage blocked: use the browser's language
  }
}

function browserLang(): Lang {
  for (const tag of navigator.languages ?? [navigator.language]) {
    const base = tag.slice(0, 2).toLowerCase();
    if (isLang(base)) return base;
  }
  return "en";
}

let current: Lang = savedLang() ?? browserLang();
document.documentElement.lang = current;

function apply(lang: Lang) {
  if (lang === current) return;
  current = lang;
  document.documentElement.lang = lang; // screen readers and hyphenation follow it
  listeners.forEach((listener) => listener());
}

export function setLang(lang: Lang) {
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // Not remembered, but still applied for this visit.
  }
  apply(lang);
}

// Keep other open tabs in step.
window.addEventListener("storage", (event) => {
  if (event.key === STORAGE_KEY && isLang(event.newValue)) apply(event.newValue);
});

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getLang(): Lang {
  return current;
}

/** The texts of the current language, for code outside React components. */
export function messages(): Messages {
  return MESSAGES[current];
}

export function useLang() {
  const lang = useSyncExternalStore(subscribe, getLang);
  return { lang, setLang };
}

/** The texts of the current language; the component re-renders when it changes. */
export function useT(): Messages {
  return MESSAGES[useSyncExternalStore(subscribe, getLang)];
}

const numberFormats = new Map<string, Intl.NumberFormat>();

function numberFormat(key: string, options?: Intl.NumberFormatOptions): Intl.NumberFormat {
  const id = `${current}|${key}`;
  let format = numberFormats.get(id);
  if (!format) {
    format = new Intl.NumberFormat(current, options);
    numberFormats.set(id, format);
  }
  return format;
}

/** 40,508 in English, 40 508 in French and Russian. */
export function formatNumber(value: number): string {
  return numberFormat("number").format(value);
}

/** A share from 0 to 1 as a whole percentage: 85% in English, 85 % in French and Russian. */
export function formatPercent(share: number): string {
  return numberFormat("percent", { style: "percent", maximumFractionDigits: 0 }).format(share);
}

export function formatDate(iso: string | null, withTime = false): string {
  if (!iso) return messages().common.never;
  return new Date(iso).toLocaleString(current, {
    dateStyle: "medium",
    timeStyle: withTime ? "short" : undefined,
  });
}
