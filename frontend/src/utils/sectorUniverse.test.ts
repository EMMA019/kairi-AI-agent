/** toTradingViewSymbol / sector universe unit tests. */
import { describe, expect, it } from "vitest";
import {
  JP_SECTOR_BAR,
  US_SECTOR_BAR,
  toTradingViewSymbol,
  jpCodeFromSymbol,
} from "./sectorUniverse";

describe("sectorUniverse", () => {
  it("has SPDR 11 + XBI", () => {
    const codes = US_SECTOR_BAR.map((x) => x.symbol);
    for (const s of ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC", "XBI"]) {
      expect(codes).toContain(s);
    }
    expect(US_SECTOR_BAR).toHaveLength(12);
  });

  it("has official TOPIX-17 JP sectors 1617-1633", () => {
    expect(JP_SECTOR_BAR).toHaveLength(17);
    expect(JP_SECTOR_BAR.map((x) => x.code)).not.toContain("1615");
    expect(JP_SECTOR_BAR.find((x) => x.code === "1630")?.label).toBe("小売");
    expect(JP_SECTOR_BAR.find((x) => x.code === "1631")?.label).toBe("銀行");
    expect(JP_SECTOR_BAR.find((x) => x.code === "1633")?.label).toBe("不動産");
    expect(JP_SECTOR_BAR.find((x) => x.code === "1617")?.label).toBe("食品");
  });

  it("maps TradingView symbols without bad AMEX prefix", () => {
    expect(toTradingViewSymbol("SPY")).toBe("SPY");
    expect(toTradingViewSymbol("QQQ")).toBe("QQQ");
    expect(toTradingViewSymbol("AAPL")).toBe("AAPL");
    expect(toTradingViewSymbol("1306.T")).toBe("TSE:1306");
    expect(toTradingViewSymbol("^N225")).toBe("TVC:NI225");
    expect(toTradingViewSymbol("TSE:7203")).toBe("TSE:7203");
  });

  it("jpCodeFromSymbol", () => {
    expect(jpCodeFromSymbol("1631.T")).toBe("1631");
    expect(jpCodeFromSymbol("^N225")).toBe("N225");
  });
});
