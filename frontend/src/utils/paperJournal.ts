/** Paper trade journal (localStorage only — no real orders). */

export type PaperSide = "long" | "short";

export type PaperJournalEntry = {
  id: string;
  createdAt: string;
  symbol: string;
  side: PaperSide;
  note: string;
  source?: string;
};

const STORAGE_KEY = "kairi_paper_journal_v1";

export function loadPaperJournal(): PaperJournalEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function savePaperJournal(entries: PaperJournalEntry[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
}

export function addPaperJournalEntry(
  input: Omit<PaperJournalEntry, "id" | "createdAt">,
): PaperJournalEntry[] {
  const entry: PaperJournalEntry = {
    ...input,
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    createdAt: new Date().toISOString(),
  };
  const next = [entry, ...loadPaperJournal()].slice(0, 200);
  savePaperJournal(next);
  return next;
}

export function removePaperJournalEntry(id: string): PaperJournalEntry[] {
  const next = loadPaperJournal().filter((e) => e.id !== id);
  savePaperJournal(next);
  return next;
}
