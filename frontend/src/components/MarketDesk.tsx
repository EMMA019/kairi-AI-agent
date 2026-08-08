/**
 * MarketDesk — 市況参照パネル（紙のみ・実発注なし）。
 * チャット本命の補助。レーダーは上級モード時のみ。
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { executeMarketTool } from "../hooks/useMarketTool";
import TradingViewChartModal, { type ChartTarget } from "./TradingViewChartModal";
import { getShowAdvancedModes } from "../utils/advancedModes";
import {
  JP_INDEX_BAR,
  JP_SECTOR_BAR,
  jpCodeFromSymbol,
} from "../utils/sectorUniverse";
import {
  addPaperJournalEntry,
  loadPaperJournal,
  removePaperJournalEntry,
  type PaperJournalEntry,
  type PaperSide,
} from "../utils/paperJournal";
import {
  addPaperPosition,
  closePaperPosition,
  loadPaperPositions,
  openPositions,
  realizedTotalUsd,
  removePaperPosition,
  unrealizedPnlUsd,
  type PaperPosition,
} from "../utils/paperPositions";
import {
  MAX_OPEN_POSITIONS,
  annualTargetUsd,
  suggestedStopTarget,
  type SwingSettings,
} from "../utils/swingSizing";
import {
  INDEX_BAR,
  SECTOR_BAR,
  WATCHLIST_MAX,
  addWatchSymbol,
  buildWatchRow,
  loadSwingSettings,
  loadWatchlist,
  removeWatchSymbol,
  saveSwingSettings,
  saveWatchlist,
  type QuotePayload,
  type WatchRow,
} from "../utils/watchlist";
import { BriefingPanel } from "./BriefingPanel";

type DeskTab = "overview" | "radar" | "signals" | "briefing";

type BarQuote = {
  symbol: string;
  label: string;
  code?: string;
  price: number | null;
  changePct: number | null;
  source: string | null;
  error?: string;
};

const QUOTE_POLL_MS = 60_000;
const HEAVY_POLL_MS = 300_000;

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

function asQuote(v: unknown): QuotePayload | null {
  const rec = asRecord(v);
  return rec ? (rec as QuotePayload) : null;
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300 whitespace-pre-wrap">
      {message}
    </div>
  );
}

function Section({
  title,
  action,
  children,
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-white/10 bg-[#0d1117]/80 p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold tracking-wide text-cyan-100">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  );
}

function KvTable({ rows }: { rows: Array<[string, string]> }) {
  if (!rows.length) {
    return <p className="text-xs text-gray-500">データなし</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k} className="border-b border-white/5">
              <th className="py-1.5 pr-3 font-medium text-gray-400 whitespace-nowrap">{k}</th>
              <td className="py-1.5 text-gray-100 font-mono">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatVal(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return "—";
    return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  return String(v);
}

function formatPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function formatUsd(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}$${v.toFixed(2)}`;
}

function pctColor(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "text-gray-400";
  if (v > 0) return "text-emerald-300";
  if (v < 0) return "text-rose-300";
  return "text-gray-400";
}

function QuoteTile({
  q,
  onOpen,
}: {
  q: BarQuote;
  onOpen: (t: ChartTarget) => void;
}) {
  return (
    <button
      type="button"
      onClick={() =>
        onOpen({
          symbol: q.symbol,
          label: q.label,
          code: q.code || q.symbol,
        })
      }
      className="rounded-lg border border-white/5 bg-black/25 px-3 py-2 text-left transition hover:border-cyan-500/40 hover:bg-cyan-500/5"
      title="チャートを開く"
    >
      <div className="flex items-baseline justify-between gap-1">
        <span className="text-[10px] text-gray-500">{q.label}</span>
        <span className="font-mono text-[10px] text-cyan-600/80">{q.code || q.symbol}</span>
      </div>
      <div className="mt-1 font-mono text-sm text-gray-100">{formatVal(q.price)}</div>
      <div className={`font-mono text-[11px] ${pctColor(q.changePct)}`}>{formatPct(q.changePct)}</div>
    </button>
  );
}

function volumeWarn(ratio: number | null | undefined): boolean {
  if (ratio == null || !Number.isFinite(ratio)) return false;
  return ratio < 0.5 || ratio >= 1.8;
}

export function MarketDesk() {
  const [tab, setTab] = useState<DeskTab>("overview");
  const [showAdvanced, setShowAdvanced] = useState(getShowAdvancedModes);
  const [loading, setLoading] = useState<string | null>(null);

  useEffect(() => {
    const onAdv = () => {
      const on = getShowAdvancedModes();
      setShowAdvanced(on);
      if (!on) setTab((t) => (t === "radar" ? "overview" : t));
    };
    window.addEventListener("kairi-advanced-modes", onAdv);
    return () => window.removeEventListener("kairi-advanced-modes", onAdv);
  }, []);
  const [ibkrSummary, setIbkrSummary] = useState<unknown>(null);
  const [ibkrPositions, setIbkrPositions] = useState<unknown>(null);
  const [ibkrFills, setIbkrFills] = useState<unknown>(null);
  const [ibkrError, setIbkrError] = useState<string | null>(null);
  const [jpSnap, setJpSnap] = useState<unknown>(null);
  const [jpError, setJpError] = useState<string | null>(null);
  const [radarType, setRadarType] = useState<"rejected" | "alert">("alert");
  const [radarText, setRadarText] = useState<string>("");
  const [radarError, setRadarError] = useState<string | null>(null);
  const [leadLag, setLeadLag] = useState<string>("");
  const [leadLagParsed, setLeadLagParsed] = useState<Record<string, unknown> | null>(null);
  const [leadLagError, setLeadLagError] = useState<string | null>(null);
  const [journal, setJournal] = useState<PaperJournalEntry[]>([]);
  const [paperSymbol, setPaperSymbol] = useState("");
  const [paperSide, setPaperSide] = useState<PaperSide>("long");
  const [paperNote, setPaperNote] = useState("");

  const [indexQuotes, setIndexQuotes] = useState<BarQuote[]>([]);
  const [sectorQuotes, setSectorQuotes] = useState<BarQuote[]>([]);
  const [watchSymbols, setWatchSymbols] = useState<string[]>(() => loadWatchlist());
  const [watchRows, setWatchRows] = useState<Record<string, WatchRow>>({});
  const [addTicker, setAddTicker] = useState("");
  const [watchError, setWatchError] = useState<string | null>(null);
  const [swing, setSwing] = useState<SwingSettings>(() => loadSwingSettings());
  const [positions, setPositions] = useState<PaperPosition[]>(() => loadPaperPositions());
  const [posError, setPosError] = useState<string | null>(null);
  const [lastQuoteAt, setLastQuoteAt] = useState<string | null>(null);
  const [quoteFeed, setQuoteFeed] = useState<string | null>(null);
  const [chartTarget, setChartTarget] = useState<ChartTarget | null>(null);
  const [pageVisible, setPageVisible] = useState(
    () => typeof document === "undefined" || document.visibilityState === "visible",
  );

  const quoteBusyRef = useRef(false);
  const heavyBusyRef = useRef(false);
  const watchSymbolsRef = useRef(watchSymbols);
  const swingRef = useRef(swing);
  watchSymbolsRef.current = watchSymbols;
  swingRef.current = swing;

  useEffect(() => {
    setJournal(loadPaperJournal());
  }, []);

  useEffect(() => {
    saveSwingSettings(swing);
  }, [swing]);

  useEffect(() => {
    setWatchRows((prev) => {
      const next: Record<string, WatchRow> = {};
      for (const sym of watchSymbols) {
        const old = prev[sym];
        next[sym] = buildWatchRow(sym, old?.quote ?? null, swing, old?.error);
      }
      return next;
    });
  }, [swing, watchSymbols]);

  useEffect(() => {
    const onVis = () => setPageVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  const run = useCallback(async (key: string, fn: () => Promise<void>) => {
    setLoading(key);
    try {
      await fn();
    } finally {
      setLoading(null);
    }
  }, []);

  const fetchOneQuote = async (
    ticker: string,
    opts?: { preferYfinance?: boolean; enrich?: boolean },
  ): Promise<{ quote: QuotePayload | null; error?: string }> => {
    // 既定は IBKR ライブ優先（本番リアルタイム）。未購読時は backend が速失敗→yfinance。
    const r = await executeMarketTool("get_stock_quote", {
      ticker,
      prefer_yfinance: opts?.preferYfinance === true,
      enrich_vol_atr: opts?.enrich !== false,
    });
    if (r.error) return { quote: null, error: r.error };
    const q = asQuote(r.parsed);
    if (!q) return { quote: null, error: "parse failed" };
    if (q.error) return { quote: q, error: String(q.error) };
    return { quote: q };
  };

  const fetchQuotesBatch = async (
    tickers: string[],
    opts?: { preferYfinance?: boolean; enrich?: boolean },
  ): Promise<{ quotes: Record<string, QuotePayload>; error?: string; source?: string }> => {
    if (!tickers.length) return { quotes: {} };
    const r = await executeMarketTool("get_stock_quotes", {
      tickers,
      prefer_yfinance: opts?.preferYfinance === true,
      enrich_vol_atr: opts?.enrich !== false,
    });
    if (r.error) return { quotes: {}, error: r.error };
    const root = asRecord(r.parsed);
    if (!root) return { quotes: {}, error: "parse failed" };
    const rawQuotes = asRecord(root.quotes) || {};
    const quotes: Record<string, QuotePayload> = {};
    for (const [sym, val] of Object.entries(rawQuotes)) {
      const q = asQuote(val);
      if (q) quotes[sym] = q;
    }
    return {
      quotes,
      source: typeof root.source === "string" ? root.source : undefined,
      error: typeof root.error === "string" ? root.error : undefined,
    };
  };

  const refreshUsdJpy = async (settings: SwingSettings): Promise<SwingSettings> => {
    if (settings.usdjpyManual) return settings;
    const { quote } = await fetchOneQuote("USDJPY=X", { enrich: false });
    const px = quote?.current_price;
    if (px != null && Number.isFinite(px) && px > 0) {
      const next = { ...settings, usdjpy: px };
      setSwing(next);
      return next;
    }
    return settings;
  };

  const refreshQuotesCore = useCallback(async () => {
    if (quoteBusyRef.current) return;
    quoteBusyRef.current = true;
    try {
      setWatchError(null);
      const settings = await refreshUsdJpy(swingRef.current);
      const barItems = [...INDEX_BAR, ...SECTOR_BAR];
      const barSymbols = barItems.map((b) => b.symbol);
      const watchSymbols = watchSymbolsRef.current.slice(0, WATCHLIST_MAX);

      // セクター拡大時: バーは軽量、ウォッチだけ ATR enrich。直列で IB 競合回避。
      const barBatch = await fetchQuotesBatch(barSymbols, { enrich: false });
      const watchBatch = await fetchQuotesBatch(watchSymbols, { enrich: true });

      const barResults: BarQuote[] = barItems.map(({ symbol, label, code }) => {
        const quote = barBatch.quotes[symbol];
        const err =
          quote?.error != null
            ? String(quote.error)
            : quote?.current_price == null
              ? barBatch.error || "no price"
              : undefined;
        return {
          symbol,
          label,
          code,
          price: quote?.current_price ?? null,
          changePct: quote?.change_pct ?? null,
          source: quote?.source ?? null,
          error: err,
        };
      });
      setIndexQuotes(barResults.slice(0, INDEX_BAR.length));
      setSectorQuotes(barResults.slice(INDEX_BAR.length));

      const map: Record<string, WatchRow> = {};
      const results = watchSymbols.map((symbol) => {
        const quote = watchBatch.quotes[symbol] ?? null;
        const err =
          quote?.error != null
            ? String(quote.error)
            : quote?.current_price == null
              ? watchBatch.error || "no price"
              : undefined;
        const row = buildWatchRow(symbol, quote, settings, err);
        map[symbol] = row;
        return row;
      });
      setWatchRows(map);

      const feedSrc = watchBatch.source || barBatch.source || null;
      const anyLive = [
        ...Object.values(barBatch.quotes),
        ...Object.values(watchBatch.quotes),
      ].some((q) => q.realtime === true || q.source === "ibkr");
      setQuoteFeed(
        anyLive ? "IBKR live" : feedSrc === "yfinance" ? "Yahoo ~15m" : feedSrc || "mixed",
      );
      setLastQuoteAt(new Date().toLocaleTimeString());
      const fails = results.filter((r) => r.error || r.quote?.current_price == null);
      if (fails.length) {
        setWatchError(
          `${fails.length} 銘柄で価格未取得（休場でも前日終値は出る想定。再取得するかバックエンドログを確認）`,
        );
      }
    } catch (e) {
      setWatchError(e instanceof Error ? e.message : String(e));
    } finally {
      quoteBusyRef.current = false;
    }
  }, []);

  const refreshIbkr = useCallback(
    () =>
      run("ibkr", async () => {
        setIbkrError(null);
        const [s, p, f] = await Promise.all([
          executeMarketTool("ibkr_account_summary"),
          executeMarketTool("ibkr_positions"),
          executeMarketTool("ibkr_recent_fills", { limit: 20 }),
        ]);
        const fail =
          s.error ||
          p.error ||
          f.error ||
          (asRecord(s.parsed)?.ok === false
            ? String(asRecord(s.parsed)?.message || asRecord(s.parsed)?.error)
            : null);
        if (fail) setIbkrError(fail);
        setIbkrSummary(s.parsed ?? s.raw);
        setIbkrPositions(p.parsed ?? p.raw);
        setIbkrFills(f.parsed ?? f.raw);
      }),
    [run],
  );

  const refreshJapan = useCallback(
    () =>
      run("japan", async () => {
        setJpError(null);
        const r = await executeMarketTool("get_jp_market_snapshot", {
          prefer_yfinance: false,
        });
        if (r.error) setJpError(r.error);
        setJpSnap(r.parsed ?? r.raw);
      }),
    [run],
  );

  const refreshHeavy = useCallback(async () => {
    if (heavyBusyRef.current) return;
    heavyBusyRef.current = true;
    try {
      await Promise.all([
        (async () => {
          setJpError(null);
          const r = await executeMarketTool("get_jp_market_snapshot", {
            prefer_yfinance: false,
          });
          if (r.error) setJpError(r.error);
          setJpSnap(r.parsed ?? r.raw);
        })(),
        (async () => {
          setIbkrError(null);
          const [s, p, f] = await Promise.all([
            executeMarketTool("ibkr_account_summary"),
            executeMarketTool("ibkr_positions"),
            executeMarketTool("ibkr_recent_fills", { limit: 20 }),
          ]);
          const fail =
            s.error ||
            p.error ||
            f.error ||
            (asRecord(s.parsed)?.ok === false
              ? String(asRecord(s.parsed)?.message || asRecord(s.parsed)?.error)
              : null);
          if (fail) setIbkrError(fail);
          setIbkrSummary(s.parsed ?? s.raw);
          setIbkrPositions(p.parsed ?? p.raw);
          setIbkrFills(f.parsed ?? f.raw);
        })(),
      ]);
    } finally {
      heavyBusyRef.current = false;
    }
  }, []);

  // Auto refresh quotes
  useEffect(() => {
    if (!swing.autoRefresh || !pageVisible || tab !== "overview") return;
    void refreshQuotesCore();
    const id = window.setInterval(() => {
      void refreshQuotesCore();
    }, QUOTE_POLL_MS);
    return () => window.clearInterval(id);
  }, [swing.autoRefresh, pageVisible, tab, refreshQuotesCore]);

  // Auto refresh Japan / IBKR (sparse)
  useEffect(() => {
    if (!swing.autoRefresh || !pageVisible || tab !== "overview") return;
    void refreshHeavy();
    const id = window.setInterval(() => {
      void refreshHeavy();
    }, HEAVY_POLL_MS);
    return () => window.clearInterval(id);
  }, [swing.autoRefresh, pageVisible, tab, refreshHeavy]);

  // Signals tab: run lead-lag once on enter (not every minute — v2)
  useEffect(() => {
    if (tab !== "signals" || leadLagParsed || leadLag) return;
    void run("leadlag", async () => {
      setLeadLagError(null);
      setLeadLagParsed(null);
      const r = await executeMarketTool("analyze_sector_lead_lag");
      if (r.error) setLeadLagError(r.error);
      if (/sklearn|No module named/i.test(r.raw)) {
        setLeadLagError("scikit-learn 未導入のため実行できません（pip install scikit-learn）");
      }
      const rec = asRecord(r.parsed);
      if (rec?.error) setLeadLagError(String(rec.error));
      else if (rec) setLeadLagParsed(rec);
      setLeadLag(r.raw);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only on tab enter
  }, [tab]);

  const fetchRadar = () =>
    run("radar", async () => {
      setRadarError(null);
      const r = await executeMarketTool("check_radar_logs", { log_type: radarType, limit: 15 });
      if (r.error) setRadarError(r.error);
      setRadarText(r.raw);
    });

  const fetchLeadLag = () =>
    run("leadlag", async () => {
      setLeadLagError(null);
      setLeadLagParsed(null);
      const r = await executeMarketTool("analyze_sector_lead_lag");
      if (r.error) setLeadLagError(r.error);
      if (/sklearn|No module named/i.test(r.raw)) {
        setLeadLagError("scikit-learn 未導入のため実行できません（pip install scikit-learn）");
      }
      const rec = asRecord(r.parsed);
      if (rec?.error) setLeadLagError(String(rec.error));
      else if (rec) setLeadLagParsed(rec);
      setLeadLag(r.raw);
    });

  const addJournal = (symbol: string, side: PaperSide, note: string, source?: string) => {
    const sym = symbol.trim();
    if (!sym) return;
    setJournal(
      addPaperJournalEntry({
        symbol: sym.toUpperCase(),
        side,
        note: note.trim() || (side === "long" ? "Paper LONG" : "Paper SHORT"),
        source,
      }),
    );
  };

  const openPaperFromWatch = (symbol: string, side: PaperSide = "long") => {
    setPosError(null);
    const row = watchRows[symbol];
    const price = row?.quote?.current_price;
    const atr = row?.metrics.atr;
    const sizing = row?.sizing;
    if (price == null || !(price > 0)) {
      setPosError("現値が無いため紙ポジを開けません（更新待ち）");
      return;
    }
    const qty = sizing?.recommended && sizing.recommended > 0 ? sizing.recommended : 1;
    const st = suggestedStopTarget(side, price, atr, swing);
    if (!st) {
      setPosError("ストップ/目標を計算できません");
      return;
    }
    const res = addPaperPosition({
      symbol,
      side,
      qty,
      entryPrice: price,
      stopPrice: st.stop,
      targetPrice: st.target,
      note: `Auto stop ATR×${swing.atrMult}`,
      source: "watchlist",
    });
    setPositions(res.entries);
    if (!res.ok) setPosError(res.reason);
  };

  const openPaperFromSignal = (name: string, side: PaperSide, score: unknown) => {
    setPosError(null);
    // Sector names are not always tickers — journal note + try open if looks like ticker
    addJournal(name, side, `Lead-lag ${side} score ${formatVal(score)}`, "lead_lag");
    const sym = name.trim().toUpperCase();
    if (/^[A-Z.]{1,6}$/.test(sym) || /^\d{4}\.T$/.test(sym)) {
      void (async () => {
        const { quote } = await fetchOneQuote(sym);
        const price = quote?.current_price;
        const atr = quote?.atr ?? null;
        if (price == null) {
          setPosError(`${sym}: 価格取得失敗（ジャーナルのみ記録）`);
          return;
        }
        const st = suggestedStopTarget(side, price, atr, swing);
        if (!st) return;
        const riskUsd = swing.capitalUsd * swing.riskPct;
        const stopDist = Math.abs(price - st.stop) || price * 0.03;
        const qty = Math.max(1, Math.min(Math.floor(swing.capitalUsd / price), Math.floor(riskUsd / stopDist)));
        const res = addPaperPosition({
          symbol: sym,
          side,
          qty,
          entryPrice: price,
          stopPrice: st.stop,
          targetPrice: st.target,
          note: `Lead-lag score ${formatVal(score)}`,
          source: "lead_lag",
        });
        setPositions(res.entries);
        if (!res.ok) setPosError(res.reason);
      })();
    }
  };

  const onAddWatch = () => {
    const next = addWatchSymbol(watchSymbols, addTicker);
    setWatchSymbols(next);
    saveWatchlist(next);
    setAddTicker("");
  };

  const onRemoveWatch = (symbol: string) => {
    setWatchSymbols(removeWatchSymbol(watchSymbols, symbol));
  };

  const markFor = (symbol: string): number | null => {
    const q = watchRows[symbol]?.quote?.current_price;
    if (q != null) return q;
    return null;
  };

  const openPos = openPositions(positions);
  let unrealizedSum = 0;
  let unrealizedOk = true;
  for (const p of openPos) {
    const u = unrealizedPnlUsd(p, markFor(p.symbol));
    if (u == null) unrealizedOk = false;
    else unrealizedSum += u;
  }
  const realized = realizedTotalUsd(positions);
  const ytd = realized + (unrealizedOk ? unrealizedSum : unrealizedSum);
  const target = annualTargetUsd(swing);
  const progress = target > 0 ? Math.min(100, Math.max(0, (ytd / target) * 100)) : 0;

  const summaryRec = asRecord(ibkrSummary);
  const summaryData = asRecord(summaryRec?.data);
  const tags = asRecord(summaryData?.tags) || {};
  const posData = asRecord(asRecord(ibkrPositions)?.data);
  const ibkrPosList = Array.isArray(posData?.positions) ? (posData!.positions as any[]) : [];
  const fillData = asRecord(asRecord(ibkrFills)?.data);
  const fills = Array.isArray(fillData?.fills) ? (fillData!.fills as any[]) : [];
  const jpRec = asRecord(jpSnap);
  const jpIndices = asRecord(jpRec?.indices) || {};
  const jpSectors = asRecord(jpRec?.sectors) || {};

  const tabs: Array<{ id: DeskTab; label: string }> = [
    { id: "overview", label: "Overview" },
    { id: "signals", label: "Signals" },
    { id: "briefing", label: "Briefing" },
    ...(showAdvanced
      ? [{ id: "radar" as const, label: "Radar（上級）" }]
      : []),
  ];

  const quotesBusy = loading === "overview_quotes" || quoteBusyRef.current;

  return (
    <div className="flex h-full flex-col bg-[#0b0f19] text-gray-100">
      <header className="flex shrink-0 items-center justify-between border-b border-white/10 px-4 py-3">
        <div>
          <h2 className="text-base font-bold tracking-tight text-white">Market Desk</h2>
          <p className="text-[11px] text-gray-500">
            指数・個別の参照パネル（実発注なし）
            {lastQuoteAt && (
              <span className="ml-2 text-cyan-500/80">
                Updated {lastQuoteAt}
                {quoteFeed ? ` · ${quoteFeed}` : ""}
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-[11px] text-gray-400">
            <input
              type="checkbox"
              checked={swing.autoRefresh}
              onChange={(e) => setSwing((s) => ({ ...s, autoRefresh: e.target.checked }))}
            />
            Auto
          </label>
          <div className="flex gap-1 rounded-lg bg-black/30 p-1">
            {tabs.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                className={`rounded-md px-3 py-1 text-xs font-semibold transition ${
                  tab === t.id ? "bg-cyan-500/20 text-cyan-200" : "text-gray-400 hover:text-white"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {tab === "overview" && (
          <>
            <Section
              title="US Index / Sector"
              action={
                <button
                  type="button"
                  onClick={() => run("overview_quotes", refreshQuotesCore)}
                  disabled={loading === "overview_quotes"}
                  className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-xs font-medium text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-50"
                >
                  {loading === "overview_quotes" ? "Loading…" : "Refresh now"}
                </button>
              }
            >
              <p className="mb-2 text-[10px] text-gray-600">クリックで TradingView 日足</p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {(indexQuotes.length
                  ? indexQuotes
                  : INDEX_BAR.map((x) => ({
                      ...x,
                      price: null,
                      changePct: null,
                      source: null,
                    }))
                ).map((q) => (
                  <QuoteTile key={q.symbol} q={q} onOpen={setChartTarget} />
                ))}
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
                {(sectorQuotes.length
                  ? sectorQuotes
                  : SECTOR_BAR.map((x) => ({
                      ...x,
                      price: null,
                      changePct: null,
                      source: null,
                    }))
                ).map((q) => (
                  <QuoteTile key={q.symbol} q={q} onOpen={setChartTarget} />
                ))}
              </div>
            </Section>

            <Section title="Swing capital ($700 · 年利10%)">
              <div className="mb-3">
                <div className="mb-1 flex justify-between text-[11px] text-gray-400">
                  <span>
                    YTD P&amp;L {formatUsd(ytd)} / 目標 {formatUsd(target)}
                  </span>
                  <span>{progress.toFixed(0)}%</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-black/40">
                  <div
                    className={`h-full rounded-full ${ytd >= 0 ? "bg-emerald-500/70" : "bg-rose-500/70"}`}
                    style={{ width: `${progress}%` }}
                  />
                </div>
                <p className="mt-1 text-[10px] text-gray-600">
                  実現 {formatUsd(realized)} · 含み {formatUsd(unrealizedOk ? unrealizedSum : null)} ·
                  同時紙ポジ上限 {MAX_OPEN_POSITIONS}
                </p>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                <label className="text-[11px] text-gray-400">
                  元手 (USD)
                  <input
                    type="number"
                    value={swing.capitalUsd}
                    onChange={(e) => setSwing((s) => ({ ...s, capitalUsd: Number(e.target.value) || 0 }))}
                    className="mt-1 w-full rounded-lg border border-white/10 bg-black/40 px-3 py-1.5 font-mono text-sm text-white outline-none focus:border-cyan-500/50"
                  />
                </label>
                <label className="text-[11px] text-gray-400">
                  1トレードリスク (%)
                  <input
                    type="number"
                    step="0.5"
                    value={swing.riskPct * 100}
                    onChange={(e) =>
                      setSwing((s) => ({ ...s, riskPct: (Number(e.target.value) || 0) / 100 }))
                    }
                    className="mt-1 w-full rounded-lg border border-white/10 bg-black/40 px-3 py-1.5 font-mono text-sm text-white outline-none focus:border-cyan-500/50"
                  />
                </label>
                <label className="text-[11px] text-gray-400">
                  ストップ ATR倍数
                  <input
                    type="number"
                    step="0.1"
                    value={swing.atrMult}
                    onChange={(e) => setSwing((s) => ({ ...s, atrMult: Number(e.target.value) || 1.5 }))}
                    className="mt-1 w-full rounded-lg border border-white/10 bg-black/40 px-3 py-1.5 font-mono text-sm text-white outline-none focus:border-cyan-500/50"
                  />
                </label>
                <label className="text-[11px] text-gray-400">
                  利確 R:R
                  <input
                    type="number"
                    step="0.5"
                    value={swing.rewardRisk}
                    onChange={(e) => setSwing((s) => ({ ...s, rewardRisk: Number(e.target.value) || 2 }))}
                    className="mt-1 w-full rounded-lg border border-white/10 bg-black/40 px-3 py-1.5 font-mono text-sm text-white outline-none focus:border-cyan-500/50"
                  />
                </label>
                <label className="text-[11px] text-gray-400">
                  USD/JPY（参考）
                  <input
                    type="number"
                    step="0.01"
                    value={swing.usdjpy}
                    onChange={(e) =>
                      setSwing((s) => ({
                        ...s,
                        usdjpy: Number(e.target.value) || s.usdjpy,
                        usdjpyManual: true,
                      }))
                    }
                    className="mt-1 w-full rounded-lg border border-white/10 bg-black/40 px-3 py-1.5 font-mono text-sm text-white outline-none focus:border-cyan-500/50"
                  />
                </label>
                <label className="flex items-end gap-2 pb-2 text-[11px] text-gray-300">
                  <input
                    type="checkbox"
                    checked={swing.usdjpyManual}
                    onChange={(e) => setSwing((s) => ({ ...s, usdjpyManual: e.target.checked }))}
                  />
                  USD/JPY 手動固定
                </label>
              </div>
            </Section>

            <Section title={`Open paper positions (${openPos.length}/${MAX_OPEN_POSITIONS})`}>
              {posError && (
                <div className="mb-2">
                  <ErrorBanner message={posError} />
                </div>
              )}
              {openPos.length === 0 ? (
                <p className="text-xs text-gray-500">ウォッチリストから Open で紙ポジ作成</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[40rem] text-left text-[11px]">
                    <thead className="text-gray-500">
                      <tr>
                        <th className="pb-2 pr-2">Symbol</th>
                        <th className="pb-2 pr-2">Side</th>
                        <th className="pb-2 pr-2">Qty</th>
                        <th className="pb-2 pr-2">Entry</th>
                        <th className="pb-2 pr-2">Mark</th>
                        <th className="pb-2 pr-2">uPnL</th>
                        <th className="pb-2 pr-2">Stop</th>
                        <th className="pb-2 pr-2">Target</th>
                        <th className="pb-2" />
                      </tr>
                    </thead>
                    <tbody>
                      {openPos.map((p) => {
                        const mark = markFor(p.symbol);
                        const u = unrealizedPnlUsd(p, mark);
                        return (
                          <tr key={p.id} className="border-t border-white/5">
                            <td className="py-1.5 pr-2 font-mono font-semibold">{p.symbol}</td>
                            <td className={`py-1.5 pr-2 ${p.side === "long" ? "text-emerald-300" : "text-rose-300"}`}>
                              {p.side.toUpperCase()}
                            </td>
                            <td className="py-1.5 pr-2 font-mono">{p.qty}</td>
                            <td className="py-1.5 pr-2 font-mono">{formatVal(p.entryPrice)}</td>
                            <td className="py-1.5 pr-2 font-mono">{formatVal(mark)}</td>
                            <td className={`py-1.5 pr-2 font-mono ${pctColor(u)}`}>{formatUsd(u)}</td>
                            <td className="py-1.5 pr-2 font-mono">{formatVal(p.stopPrice)}</td>
                            <td className="py-1.5 pr-2 font-mono">{formatVal(p.targetPrice)}</td>
                            <td className="py-1.5">
                              <button
                                type="button"
                                className="rounded border border-rose-500/30 px-1.5 py-0.5 text-[10px] text-rose-200 hover:bg-rose-500/10"
                                onClick={() => {
                                  const exit = mark ?? p.entryPrice;
                                  setPositions(closePaperPosition(p.id, exit));
                                }}
                              >
                                Close
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </Section>

            <Section
              title="Watchlist"
              action={
                <button
                  type="button"
                  onClick={() => run("overview_quotes", refreshQuotesCore)}
                  disabled={Boolean(quotesBusy) || !watchSymbols.length}
                  className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-xs font-medium text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-50"
                >
                  Refresh list
                </button>
              }
            >
              <div className="mb-3 flex flex-wrap gap-2">
                <input
                  value={addTicker}
                  onChange={(e) => setAddTicker(e.target.value.toUpperCase())}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") onAddWatch();
                  }}
                  className="rounded-lg border border-white/10 bg-black/40 px-3 py-1.5 font-mono text-sm text-white outline-none focus:border-cyan-500/50"
                  placeholder="TICKER"
                />
                <button
                  type="button"
                  onClick={onAddWatch}
                  disabled={!addTicker.trim() || watchSymbols.length >= WATCHLIST_MAX}
                  className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-1.5 text-xs font-medium text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-50"
                >
                  Add
                </button>
                <span className="self-center text-[10px] text-gray-600">
                  {watchSymbols.length}/{WATCHLIST_MAX}
                </span>
              </div>
              {watchError && (
                <div className="mb-2">
                  <ErrorBanner message={watchError} />
                </div>
              )}
              <div className="overflow-x-auto">
                <table className="w-full min-w-[56rem] text-left text-[11px]">
                  <thead className="text-gray-500">
                    <tr>
                      <th className="pb-2 pr-2">Symbol</th>
                      <th className="pb-2 pr-2">Price</th>
                      <th className="pb-2 pr-2">Chg%</th>
                      <th className="pb-2 pr-2">Vol</th>
                      <th className="pb-2 pr-2">ATR</th>
                      <th className="pb-2 pr-2">Px/ATR</th>
                      <th className="pb-2 pr-2">5d</th>
                      <th className="pb-2 pr-2">20d</th>
                      <th className="pb-2 pr-2">Bias</th>
                      <th className="pb-2 pr-2">推奨</th>
                      <th className="pb-2 pr-2">Stop$</th>
                      <th className="pb-2 pr-2">Src</th>
                      <th className="pb-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {watchSymbols.map((sym) => {
                      const row = watchRows[sym];
                      const q = row?.quote;
                      const m = row?.metrics;
                      const sz = row?.sizing;
                      const warn = volumeWarn(m?.volumeRatio);
                      return (
                        <tr
                          key={sym}
                          className={`border-t border-white/5 ${warn ? "bg-amber-500/5" : ""}`}
                        >
                          <td className="py-1.5 pr-2 font-mono font-semibold text-gray-100">
                            <button
                              type="button"
                              className="text-cyan-200 hover:underline"
                              title="チャートを開く"
                              onClick={() =>
                                setChartTarget({
                                  symbol: sym,
                                  label: sym,
                                  code: jpCodeFromSymbol(sym),
                                })
                              }
                            >
                              {sym}
                            </button>
                          </td>
                          <td className="py-1.5 pr-2 font-mono">{formatVal(q?.current_price)}</td>
                          <td className={`py-1.5 pr-2 font-mono ${pctColor(q?.change_pct ?? null)}`}>
                            {formatPct(q?.change_pct)}
                          </td>
                          <td className={`py-1.5 pr-2 font-mono ${warn ? "text-amber-300" : ""}`}>
                            {m?.volumeRatio != null ? m.volumeRatio.toFixed(2) : "—"}
                          </td>
                          <td className="py-1.5 pr-2 font-mono">{formatVal(m?.atr)}</td>
                          <td className="py-1.5 pr-2 font-mono">
                            {m?.priceOverAtr != null ? m.priceOverAtr.toFixed(1) : "—"}
                          </td>
                          <td className={`py-1.5 pr-2 font-mono ${pctColor(m?.ret5d)}`}>
                            {formatPct(m?.ret5d)}
                          </td>
                          <td className={`py-1.5 pr-2 font-mono ${pctColor(m?.ret20d)}`}>
                            {formatPct(m?.ret20d)}
                          </td>
                          <td className="py-1.5 pr-2 font-mono text-cyan-200/80">
                            {m?.bias ?? "—"}
                          </td>
                          <td className="py-1.5 pr-2 font-mono text-emerald-200">
                            {sz ? sz.recommended : "—"}
                          </td>
                          <td className="py-1.5 pr-2 font-mono">
                            {sz?.stopDistance ? sz.stopDistance.toFixed(2) : "—"}
                          </td>
                          <td className="py-1.5 pr-2 font-mono text-gray-500">
                            {q?.source || (row?.error ? "err" : "—")}
                          </td>
                          <td className="py-1.5">
                            <div className="flex gap-1">
                              <button
                                type="button"
                                className="rounded border border-emerald-500/30 px-1.5 py-0.5 text-[10px] text-emerald-200 hover:bg-emerald-500/10"
                                onClick={() => openPaperFromWatch(sym, "long")}
                              >
                                Open
                              </button>
                              <button
                                type="button"
                                className="text-gray-500 hover:text-red-300"
                                onClick={() => onRemoveWatch(sym)}
                                title="Remove"
                              >
                                ×
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Section>

            <Section
              title="IBKR Account"
              action={
                <button
                  type="button"
                  onClick={refreshIbkr}
                  disabled={loading === "ibkr"}
                  className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-xs font-medium text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-50"
                >
                  {loading === "ibkr" ? "Loading…" : "Refresh"}
                </button>
              }
            >
              {ibkrError && (
                <div className="mb-2">
                  <ErrorBanner message={ibkrError} />
                </div>
              )}
              {summaryRec?.ok === true && (
                <KvTable
                  rows={[
                    ["NetLiquidation", formatVal(tags.NetLiquidation)],
                    ["TotalCashValue", formatVal(tags.TotalCashValue)],
                    ["BuyingPower", formatVal(tags.BuyingPower)],
                    ["AvailableFunds", formatVal(tags.AvailableFunds)],
                  ]}
                />
              )}
              {!ibkrSummary && !ibkrError && (
                <p className="text-xs text-gray-500">Auto または Refresh で残高取得</p>
              )}
              {ibkrPosList.length > 0 && (
                <div className="mt-3 text-[11px] text-gray-400">
                  Live positions: {ibkrPosList.length}（参照のみ）
                </div>
              )}
              {fills.length > 0 && (
                <div className="mt-2 max-h-24 overflow-y-auto font-mono text-[10px] text-gray-500">
                  {fills.slice(0, 5).map((row, i) => (
                    <div key={i}>
                      {row.time} {row.side} {row.symbol} ×{formatVal(row.shares)}
                    </div>
                  ))}
                </div>
              )}
            </Section>

            <Section
              title="Japan Market"
              action={
                <button
                  type="button"
                  onClick={refreshJapan}
                  disabled={loading === "japan"}
                  className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-xs font-medium text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-50"
                >
                  {loading === "japan" ? "Loading…" : "Refresh"}
                </button>
              }
            >
              {jpError && (
                <div className="mb-2">
                  <ErrorBanner message={jpError} />
                </div>
              )}
              <p className="mb-2 text-[10px] text-gray-600">証券コード表示 · クリックでチャート</p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {JP_INDEX_BAR.map((item) => {
                  const rec = asRecord(jpIndices[item.symbol]);
                  const q: BarQuote = {
                    symbol: item.symbol,
                    label: item.label,
                    code: item.code,
                    price:
                      typeof rec?.current_price === "number" ? rec.current_price : null,
                    changePct: typeof rec?.change_pct === "number" ? rec.change_pct : null,
                    source: typeof rec?.source === "string" ? rec.source : null,
                  };
                  return <QuoteTile key={item.symbol} q={q} onOpen={setChartTarget} />;
                })}
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
                {JP_SECTOR_BAR.map((item) => {
                  const rec = asRecord(jpSectors[item.symbol]);
                  const q: BarQuote = {
                    symbol: item.symbol,
                    label: item.label,
                    code: item.code,
                    price:
                      typeof rec?.current_price === "number" ? rec.current_price : null,
                    changePct: typeof rec?.change_pct === "number" ? rec.change_pct : null,
                    source: typeof rec?.source === "string" ? rec.source : null,
                  };
                  return <QuoteTile key={item.symbol} q={q} onOpen={setChartTarget} />;
                })}
              </div>
              {!jpError &&
                Object.keys(jpIndices).length === 0 &&
                Object.keys(jpSectors).length === 0 && (
                  <p className="mt-2 text-xs text-gray-500">Auto 5分 or Refresh</p>
                )}
            </Section>
          </>
        )}

        {tab === "radar" && (
          <Section
            title="News Radar Logs"
            action={
              <div className="flex items-center gap-2">
                <select
                  value={radarType}
                  onChange={(e) => setRadarType(e.target.value as "rejected" | "alert")}
                  className="rounded-md border border-white/10 bg-black/40 px-2 py-1 text-xs text-gray-200"
                >
                  <option value="alert">alert</option>
                  <option value="rejected">rejected</option>
                </select>
                <button
                  type="button"
                  onClick={fetchRadar}
                  disabled={loading === "radar"}
                  className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-xs font-medium text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-50"
                >
                  {loading === "radar" ? "Loading…" : "Load"}
                </button>
              </div>
            }
          >
            <p className="mb-2 text-[11px] text-gray-500">
              レーダー×ウォッチリスト本結合は v2。ここではログ閲覧のみ。
            </p>
            {radarError && (
              <div className="mb-2">
                <ErrorBanner message={radarError} />
              </div>
            )}
            <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-lg bg-black/30 p-3 text-[11px] text-gray-300">
              {radarText || "Load でレーダーログを表示"}
            </pre>
          </Section>
        )}

        {tab === "signals" && (
          <>
            <Section
              title="Sector Lead-Lag (swing candidates)"
              action={
                <button
                  type="button"
                  onClick={fetchLeadLag}
                  disabled={loading === "leadlag"}
                  className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-xs font-medium text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-50"
                >
                  {loading === "leadlag" ? "Loading…" : "Run model"}
                </button>
              }
            >
              <p className="mb-2 text-[11px] text-gray-500">
                数日〜数週ホールド向け候補。Open paper で紙ポジ作成（実発注なし）。毎分自動実行は v2。
              </p>
              {leadLagError && (
                <div className="mb-2">
                  <ErrorBanner message={leadLagError} />
                </div>
              )}
              {leadLagParsed && !leadLagParsed.error && (
                <div className="mb-3 grid gap-3 md:grid-cols-2">
                  <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3">
                    <h4 className="mb-2 text-xs font-semibold text-emerald-300">LONG candidates</h4>
                    <ul className="space-y-1 text-xs">
                      {Object.entries(asRecord(leadLagParsed.Recommended_Longs) || {}).map(
                        ([name, score]) => (
                          <li key={name} className="flex items-center justify-between gap-2">
                            <span>
                              {name}{" "}
                              <span className="font-mono text-gray-400">+{formatVal(score)}</span>
                            </span>
                            <button
                              type="button"
                              className="rounded border border-emerald-500/30 px-2 py-0.5 text-[10px] text-emerald-200 hover:bg-emerald-500/10"
                              onClick={() => openPaperFromSignal(name, "long", score)}
                            >
                              Open paper
                            </button>
                          </li>
                        ),
                      )}
                    </ul>
                  </div>
                  <div className="rounded-lg border border-rose-500/20 bg-rose-500/5 p-3">
                    <h4 className="mb-2 text-xs font-semibold text-rose-300">SHORT candidates</h4>
                    <ul className="space-y-1 text-xs">
                      {Object.entries(asRecord(leadLagParsed.Recommended_Shorts) || {}).map(
                        ([name, score]) => (
                          <li key={name} className="flex items-center justify-between gap-2">
                            <span>
                              {name}{" "}
                              <span className="font-mono text-gray-400">{formatVal(score)}</span>
                            </span>
                            <button
                              type="button"
                              className="rounded border border-rose-500/30 px-2 py-0.5 text-[10px] text-rose-200 hover:bg-rose-500/10"
                              onClick={() => openPaperFromSignal(name, "short", score)}
                            >
                              Open paper
                            </button>
                          </li>
                        ),
                      )}
                    </ul>
                  </div>
                </div>
              )}
              {!!leadLag && (
                <details className="text-[11px] text-gray-400">
                  <summary className="cursor-pointer text-gray-500">Raw JSON</summary>
                  <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-black/30 p-3">
                    {leadLag}
                  </pre>
                </details>
              )}
            </Section>

            <Section title="Closed / notes journal">
              <p className="mb-3 text-[11px] text-gray-500">メモ用。ポジション本体は Overview の Open positions。</p>
              <div className="mb-3 flex flex-wrap gap-2">
                <input
                  value={paperSymbol}
                  onChange={(e) => setPaperSymbol(e.target.value)}
                  placeholder="Symbol"
                  className="rounded-lg border border-white/10 bg-black/40 px-3 py-1.5 text-sm text-white outline-none focus:border-cyan-500/50"
                />
                <select
                  value={paperSide}
                  onChange={(e) => setPaperSide(e.target.value as PaperSide)}
                  className="rounded-lg border border-white/10 bg-black/40 px-2 py-1.5 text-xs text-gray-200"
                >
                  <option value="long">LONG</option>
                  <option value="short">SHORT</option>
                </select>
                <input
                  value={paperNote}
                  onChange={(e) => setPaperNote(e.target.value)}
                  placeholder="Note"
                  className="min-w-[12rem] flex-1 rounded-lg border border-white/10 bg-black/40 px-3 py-1.5 text-sm text-white outline-none focus:border-cyan-500/50"
                />
                <button
                  type="button"
                  onClick={() => {
                    addJournal(paperSymbol, paperSide, paperNote, "manual");
                    setPaperSymbol("");
                    setPaperNote("");
                  }}
                  disabled={!paperSymbol.trim()}
                  className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-1.5 text-xs font-medium text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-50"
                >
                  Add note
                </button>
              </div>
              {positions.filter((p) => p.status === "closed").length > 0 && (
                <div className="mb-3">
                  <h4 className="mb-1 text-[11px] font-semibold text-gray-400">Closed paper</h4>
                  <ul className="space-y-1 text-[11px]">
                    {positions
                      .filter((p) => p.status === "closed")
                      .slice(0, 10)
                      .map((p) => (
                        <li key={p.id} className="flex justify-between gap-2 font-mono text-gray-400">
                          <span>
                            {p.symbol} {p.side} ×{p.qty} → {formatUsd(p.realizedPnlUsd)}
                          </span>
                          <button
                            type="button"
                            className="text-gray-600 hover:text-red-300"
                            onClick={() => setPositions(removePaperPosition(p.id))}
                          >
                            ×
                          </button>
                        </li>
                      ))}
                  </ul>
                </div>
              )}
              {journal.length === 0 ? (
                <p className="text-xs text-gray-500">メモなし</p>
              ) : (
                <ul className="space-y-2">
                  {journal.slice(0, 20).map((e) => (
                    <li
                      key={e.id}
                      className="flex items-start justify-between gap-2 rounded-lg border border-white/5 bg-black/20 px-3 py-2 text-xs"
                    >
                      <div>
                        <span className="font-mono text-gray-100">{e.symbol}</span>{" "}
                        <span className="text-gray-500">{e.side}</span>
                        <p className="mt-1 text-gray-400">{e.note}</p>
                      </div>
                      <button
                        type="button"
                        className="text-gray-500 hover:text-red-300"
                        onClick={() => setJournal(removePaperJournalEntry(e.id))}
                      >
                        ×
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </>
        )}

        {tab === "briefing" && (
          <Section title="Market Briefing">
            <p className="mb-3 text-[11px] text-gray-500">
              寄り前 / 大引け後の下書き。目視確認後に Discord へ全文配信されます。
            </p>
            <BriefingPanel />
          </Section>
        )}
      </div>
      <TradingViewChartModal target={chartTarget} onClose={() => setChartTarget(null)} />
    </div>
  );
}
