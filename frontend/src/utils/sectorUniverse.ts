/** US / JP sector universe for Market Desk swing overview. */

export type SectorItem = {
  symbol: string;
  label: string;
  /** Display code (JP: 4-digit; US: ticker) */
  code: string;
};

/** Broad US indices (SOXX kept as semi theme next to indices). */
export const US_INDEX_BAR: SectorItem[] = [
  { symbol: "DIA", label: "Dow", code: "DIA" },
  { symbol: "SPY", label: "S&P500", code: "SPY" },
  { symbol: "QQQ", label: "Nasdaq", code: "QQQ" },
  { symbol: "SOXX", label: "SOX", code: "SOXX" },
];

/** SPDR Select Sector 11 + XBI theme. */
export const US_SECTOR_BAR: SectorItem[] = [
  { symbol: "XLK", label: "Tech", code: "XLK" },
  { symbol: "XLF", label: "Fin", code: "XLF" },
  { symbol: "XLE", label: "Energy", code: "XLE" },
  { symbol: "XLV", label: "Health", code: "XLV" },
  { symbol: "XLI", label: "Indust", code: "XLI" },
  { symbol: "XLY", label: "Disc", code: "XLY" },
  { symbol: "XLP", label: "Staples", code: "XLP" },
  { symbol: "XLU", label: "Utils", code: "XLU" },
  { symbol: "XLB", label: "Materials", code: "XLB" },
  { symbol: "XLRE", label: "RE", code: "XLRE" },
  { symbol: "XLC", label: "Comm", code: "XLC" },
  { symbol: "XBI", label: "Biotech", code: "XBI" },
];

export const JP_INDEX_BAR: SectorItem[] = [
  { symbol: "^N225", label: "日経平均", code: "N225" },
  { symbol: "1306.T", label: "TOPIX連動", code: "1306" },
];

/** NEXT FUNDS TOPIX-17 sector ETFs (Yahoo: ####.T).
 * 公式: 1617–1633。1615 は東証33銀行業で別銘柄（含めない）。
 * 出典: NEXT FUNDS / JPX
 */
export const JP_SECTOR_BAR: SectorItem[] = [
  { symbol: "1617.T", label: "食品", code: "1617" },
  { symbol: "1618.T", label: "エネルギー資源", code: "1618" },
  { symbol: "1619.T", label: "建設・資材", code: "1619" },
  { symbol: "1620.T", label: "素材・化学", code: "1620" },
  { symbol: "1621.T", label: "医薬品", code: "1621" },
  { symbol: "1622.T", label: "自動車・輸送機", code: "1622" },
  { symbol: "1623.T", label: "鉄鋼・非鉄", code: "1623" },
  { symbol: "1624.T", label: "機械", code: "1624" },
  { symbol: "1625.T", label: "電機・精密", code: "1625" },
  { symbol: "1626.T", label: "情報通信・サービス他", code: "1626" },
  { symbol: "1627.T", label: "電力・ガス", code: "1627" },
  { symbol: "1628.T", label: "運輸・物流", code: "1628" },
  { symbol: "1629.T", label: "商社・卸売", code: "1629" },
  { symbol: "1630.T", label: "小売", code: "1630" },
  { symbol: "1631.T", label: "銀行", code: "1631" },
  { symbol: "1632.T", label: "金融（除く銀行）", code: "1632" },
  { symbol: "1633.T", label: "不動産", code: "1633" },
];

/** Legacy aliases used by MarketDesk / watchlist imports. */
export const INDEX_BAR = US_INDEX_BAR;
export const SECTOR_BAR = US_SECTOR_BAR;

/**
 * Map Kairi / Yahoo tickers to TradingView symbols.
 * 米国は裸ティッカー（誤った AMEX: 接頭辞で QQQ 等が未検出になるのを防ぐ）。
 * 日本は TSE:、指数は明示マップ。
 */
export function toTradingViewSymbol(raw: string): string {
  const s = (raw || "").trim();
  if (!s) return "SPY";
  if (s.includes(":")) return s;

  const upper = s.toUpperCase();
  if (upper === "^N225" || upper === "N225" || upper === "NI225") return "TVC:NI225";
  if (upper === "^GSPC" || upper === "SPX") return "SP:SPX";
  if (upper === "^DJI" || upper === "DJI") return "DJ:DJI";
  if (upper === "^IXIC" || upper === "COMP") return "NASDAQ:IXIC";

  if (upper.endsWith(".T")) {
    const code = upper.slice(0, -2);
    return `TSE:${code}`;
  }
  if (/^\d{4}$/.test(upper)) return `TSE:${upper}`;

  // US equities / ETFs: bare ticker (TradingView resolves exchange)
  if (/^[A-Z]{1,5}$/.test(upper)) return upper;
  return upper;
}

export function jpCodeFromSymbol(symbol: string): string {
  const s = symbol.trim().toUpperCase();
  if (s.endsWith(".T")) return s.slice(0, -2);
  if (s === "^N225") return "N225";
  return s;
}
