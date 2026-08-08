/** Paper swing/day positions (localStorage only — no real orders). */

import type { PaperSide } from "./paperJournal";
import { MAX_OPEN_POSITIONS } from "./swingSizing";

export type PaperPositionStatus = "open" | "closed";

export type PaperPosition = {
  id: string;
  symbol: string;
  side: PaperSide;
  qty: number;
  entryPrice: number;
  stopPrice: number;
  targetPrice: number;
  openedAt: string;
  note: string;
  source?: string;
  status: PaperPositionStatus;
  closedAt?: string;
  exitPrice?: number;
  realizedPnlUsd?: number;
};

const STORAGE_KEY = "kairi_paper_positions_v1";

export function loadPaperPositions(): PaperPosition[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function savePaperPositions(entries: PaperPosition[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
}

export function openPositions(entries: PaperPosition[] = loadPaperPositions()): PaperPosition[] {
  return entries.filter((e) => e.status === "open");
}

export function unrealizedPnlUsd(pos: PaperPosition, mark: number | null | undefined): number | null {
  if (mark == null || !Number.isFinite(mark)) return null;
  const diff = pos.side === "long" ? mark - pos.entryPrice : pos.entryPrice - mark;
  return diff * pos.qty;
}

export function realizedTotalUsd(entries: PaperPosition[]): number {
  return entries
    .filter((e) => e.status === "closed" && e.realizedPnlUsd != null)
    .reduce((s, e) => s + (e.realizedPnlUsd || 0), 0);
}

export function addPaperPosition(
  input: Omit<PaperPosition, "id" | "openedAt" | "status">,
  existing: PaperPosition[] = loadPaperPositions(),
): { ok: true; entries: PaperPosition[] } | { ok: false; reason: string; entries: PaperPosition[] } {
  const open = openPositions(existing);
  if (open.length >= MAX_OPEN_POSITIONS) {
    return {
      ok: false,
      reason: `同時紙ポジは最大 ${MAX_OPEN_POSITIONS} まで`,
      entries: existing,
    };
  }
  if (!(input.qty > 0) || !(input.entryPrice > 0)) {
    return { ok: false, reason: "qty / entry が無効", entries: existing };
  }
  const entry: PaperPosition = {
    ...input,
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    openedAt: new Date().toISOString(),
    status: "open",
  };
  const next = [entry, ...existing].slice(0, 200);
  savePaperPositions(next);
  return { ok: true, entries: next };
}

export function closePaperPosition(
  id: string,
  exitPrice: number,
  existing: PaperPosition[] = loadPaperPositions(),
): PaperPosition[] {
  const next = existing.map((e) => {
    if (e.id !== id || e.status !== "open") return e;
    const diff = e.side === "long" ? exitPrice - e.entryPrice : e.entryPrice - exitPrice;
    return {
      ...e,
      status: "closed" as const,
      closedAt: new Date().toISOString(),
      exitPrice,
      realizedPnlUsd: diff * e.qty,
    };
  });
  savePaperPositions(next);
  return next;
}

export function removePaperPosition(
  id: string,
  existing: PaperPosition[] = loadPaperPositions(),
): PaperPosition[] {
  const next = existing.filter((e) => e.id !== id);
  savePaperPositions(next);
  return next;
}
