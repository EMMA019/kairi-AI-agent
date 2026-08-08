import { useEffect, useState, useCallback } from "react";
import { en, type MessageKey } from "./en";
import { ja } from "./ja";

export type Locale = "en" | "ja";

const STORAGE_KEY = "kairi_locale";
export const LOCALE_EVENT = "kairi-locale";

const catalogs: Record<Locale, Record<MessageKey, string>> = { en, ja };

let currentLocale: Locale = "en";

function normalizeLocale(raw: string | null | undefined): Locale {
  const v = (raw || "en").trim().toLowerCase();
  return v.startsWith("ja") ? "ja" : "en";
}

try {
  if (typeof localStorage !== "undefined") {
    currentLocale = normalizeLocale(localStorage.getItem(STORAGE_KEY));
  }
} catch {
  /* ignore */
}

export function getLocale(): Locale {
  return currentLocale;
}

export function setLocaleLocal(locale: string | null | undefined): Locale {
  const next = normalizeLocale(locale);
  currentLocale = next;
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    /* ignore */
  }
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(LOCALE_EVENT, { detail: next }));
  }
  return next;
}

type Vars = Record<string, string | number | undefined>;

export function t(key: MessageKey, vars?: Vars, locale?: Locale): string {
  const loc = locale ?? currentLocale;
  let text = catalogs[loc][key] ?? catalogs.en[key] ?? String(key);
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      text = text.replaceAll(`{{${k}}}`, String(v ?? ""));
    }
  }
  return text;
}

export function useLocale(): { locale: Locale; t: typeof t; setLocale: typeof setLocaleLocal } {
  const [locale, setLocaleState] = useState<Locale>(() => getLocale());

  useEffect(() => {
    const onChange = (e: Event) => {
      const detail = (e as CustomEvent<string>).detail;
      setLocaleState(normalizeLocale(detail ?? getLocale()));
    };
    window.addEventListener(LOCALE_EVENT, onChange);
    return () => window.removeEventListener(LOCALE_EVENT, onChange);
  }, []);

  const setLocale = useCallback((raw: string | null | undefined) => {
    const next = setLocaleLocal(raw);
    setLocaleState(next);
    return next;
  }, []);

  const translate = useCallback(
    (key: MessageKey, vars?: Vars) => t(key, vars, locale),
    [locale]
  );

  return { locale, t: translate, setLocale };
}

export type { MessageKey };
