/** Watchlist + swing settings (localStorage). Rows keyed by symbol for future newsFlags join. */

import {
  DEFAULT_SWING_SETTINGS,
  type SwingSettings,
  type SwingSizing,
  computeSwingSizing,
} from "./swingSizing";
import { INDEX_BAR, SECTOR_BAR } from "./sectorUniverse";

export { INDEX_BAR, SECTOR_BAR };
export type { SectorItem } from "./sectorUniverse";
export {
  US_INDEX_BAR,
  US_SECTOR_BAR,
  JP_INDEX_BAR,
  JP_SECTOR_BAR,
  toTradingViewSymbol,
  jpCodeFromSymbol,
} from "./sectorUniverse";

export const DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "AMD", "META"];

const WATCHLIST_KEY = "kairi_watchlist_v1";
const SWING_KEY = "kairi_swing_settings_v1";
export const WATCHLIST_MAX = 20;

export type QuotePayload = {
  ticker?: string;
  name?: string;
  current_price?: number | null;
  change_pct?: number | null;
  previous_close?: number | null;
  volume?: number | null;
  average_volume?: number | null;
  volume_ratio?: number | null;
  atr?: number | null;
  day_range?: number | null;
  day_high?: number | null;
  day_low?: number | null;
  ret_5d?: number | null;
  ret_20d?: number | null;
  source?: string;
  realtime?: boolean;
  market_data_type?: number;
  error?: string;
  currency?: string;
};

export type WatchRow = {
  symbol: string;
  quote: QuotePayload | null;
  metrics: {
    volumeRatio: number | null;
    atr: number | null;
    dayRange: number | null;
    priceOverAtr: number | null;
    ret5d: number | null;
    ret20d: number | null;
    bias: "bull" | "bear" | "mixed" | null;
  };
  sizing: SwingSizing | null;
  /** Reserved for future news radar join. v1/v2 bridge: always []. */
  newsFlags: string[];
  updatedAt: string;
  error?: string;
};

function normalizeSymbol(raw: string): string {
  return raw.trim().toUpperCase();
}

export function loadWatchlist(): string[] {
  try {
    const raw = localStorage.getItem(WATCHLIST_KEY);
    if (!raw) return [...DEFAULT_WATCHLIST];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [...DEFAULT_WATCHLIST];
    const syms = parsed.map((s) => normalizeSymbol(String(s))).filter(Boolean);
    return syms.length ? Array.from(new Set(syms)).slice(0, WATCHLIST_MAX) : [...DEFAULT_WATCHLIST];
  } catch {
    return [...DEFAULT_WATCHLIST];
  }
}

export function saveWatchlist(symbols: string[]): void {
  const cleaned = Array.from(new Set(symbols.map(normalizeSymbol).filter(Boolean))).slice(
    0,
    WATCHLIST_MAX,
  );
  localStorage.setItem(WATCHLIST_KEY, JSON.stringify(cleaned));
}

export function addWatchSymbol(symbols: string[], ticker: string): string[] {
  const s = normalizeSymbol(ticker);
  if (!s) return symbols;
  if (symbols.includes(s)) return symbols;
  if (symbols.length >= WATCHLIST_MAX) return symbols;
  const next = [...symbols, s];
  saveWatchlist(next);
  return next;
}

export function removeWatchSymbol(symbols: string[], ticker: string): string[] {
  const next = symbols.filter((s) => s !== normalizeSymbol(ticker));
  saveWatchlist(next);
  return next;
}

export function loadSwingSettings(): SwingSettings {
  try {
    const raw = localStorage.getItem(SWING_KEY);
    if (!raw) return { ...DEFAULT_SWING_SETTINGS };
    const parsed = JSON.parse(raw) as Partial<SwingSettings>;
    return {
      capitalUsd: Number(parsed.capitalUsd) || DEFAULT_SWING_SETTINGS.capitalUsd,
      riskPct: Number(parsed.riskPct) || DEFAULT_SWING_SETTINGS.riskPct,
      atrMult: Number(parsed.atrMult) || DEFAULT_SWING_SETTINGS.atrMult,
      rewardRisk: Number(parsed.rewardRisk) || DEFAULT_SWING_SETTINGS.rewardRisk,
      annualTargetPct: Number(parsed.annualTargetPct) || DEFAULT_SWING_SETTINGS.annualTargetPct,
      usdjpy: Number(parsed.usdjpy) || DEFAULT_SWING_SETTINGS.usdjpy,
      usdjpyManual: Boolean(parsed.usdjpyManual),
      autoRefresh: parsed.autoRefresh !== false,
    };
  } catch {
    return { ...DEFAULT_SWING_SETTINGS };
  }
}

export function saveSwingSettings(settings: SwingSettings): void {
  localStorage.setItem(SWING_KEY, JSON.stringify(settings));
}

function biasFromRets(r5: number | null, r20: number | null): "bull" | "bear" | "mixed" | null {
  if (r5 == null || r20 == null) return null;
  if (r5 > 0 && r20 > 0) return "bull";
  if (r5 < 0 && r20 < 0) return "bear";
  return "mixed";
}

export function buildWatchRow(
  symbol: string,
  quote: QuotePayload | null,
  settings: SwingSettings,
  error?: string,
): WatchRow {
  const atr = quote?.atr ?? null;
  const price = quote?.current_price ?? null;
  const ret5d = quote?.ret_5d ?? null;
  const ret20d = quote?.ret_20d ?? null;
  return {
    symbol,
    quote,
    metrics: {
      volumeRatio: quote?.volume_ratio ?? null,
      atr,
      dayRange: quote?.day_range ?? null,
      priceOverAtr: price != null && atr != null && atr > 0 ? price / atr : null,
      ret5d,
      ret20d,
      bias: biasFromRets(ret5d, ret20d),
    },
    sizing: computeSwingSizing(price, atr, settings),
    newsFlags: [],
    updatedAt: new Date().toISOString(),
    error,
  };
}
