/**
 * TradingView advanced chart modal (ported from personal sentinel-dashboard).
 */
import { useEffect, useRef } from "react";
import { toTradingViewSymbol } from "../utils/sectorUniverse";

export type ChartTarget = {
  symbol: string;
  label?: string;
  code?: string;
};

type Props = {
  target: ChartTarget | null;
  onClose: () => void;
  height?: number;
  interval?: string;
};

function TradingViewEmbed({
  tvSymbol,
  height,
  interval,
}: {
  tvSymbol: string;
  height: number;
  interval: string;
}) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = container.current;
    if (!el) return;
    el.innerHTML = "";

    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.type = "text/javascript";
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: false,
      symbol: tvSymbol,
      interval,
      timezone: "Asia/Tokyo",
      theme: "dark",
      style: "1",
      locale: "ja",
      height,
      width: "100%",
      enable_publishing: false,
      hide_top_toolbar: false,
      hide_legend: false,
      save_image: false,
      backgroundColor: "rgba(11, 15, 25, 1)",
      gridColor: "rgba(24, 32, 48, 0.35)",
      support_host: "https://www.tradingview.com",
    });
    el.appendChild(script);

    return () => {
      el.innerHTML = "";
    };
  }, [tvSymbol, height, interval]);

  return (
    <div
      className="tradingview-widget-container"
      ref={container}
      style={{ height: `${height}px`, overflow: "hidden" }}
    >
      <div className="tradingview-widget-container__widget" />
    </div>
  );
}

export default function TradingViewChartModal({
  target,
  onClose,
  height = 420,
  interval = "D",
}: Props) {
  if (!target) return null;
  const tv = toTradingViewSymbol(target.symbol);
  const title = target.label || target.symbol;
  const code = target.code || target.symbol;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl overflow-hidden rounded-xl border border-white/15 bg-[#0b0f19] shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-white">{title}</div>
            <div className="font-mono text-[11px] text-gray-500">
              {code} · {tv} · 日足
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-white/15 px-3 py-1 text-xs text-gray-300 hover:bg-white/5"
          >
            Close
          </button>
        </div>
        <div className="p-2">
          <TradingViewEmbed tvSymbol={tv} height={height} interval={interval} />
        </div>
      </div>
    </div>
  );
}
