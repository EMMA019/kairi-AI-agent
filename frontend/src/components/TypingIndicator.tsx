import { useState, useEffect } from "react";
import { useLocale, type MessageKey } from "../i18n";

interface TypingIndicatorProps {
  status: "idle" | "thinking" | "searching" | "responding" | "planning_search";
  searchQuery: string | null;
}

const WAITING_KEYS: MessageKey[] = [
  "status.wait.0",
  "status.wait.1",
  "status.wait.2",
  "status.wait.3",
  "status.wait.4",
];

export function TypingIndicator({ status, searchQuery }: TypingIndicatorProps) {
  const { t } = useLocale();
  const [elapsed, setElapsed] = useState(0);
  const [messageIndex, setMessageIndex] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setElapsed((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (elapsed > 0 && elapsed % 8 === 0) {
      setMessageIndex((prev) => (prev + 1) % WAITING_KEYS.length);
    }
  }, [elapsed]);

  const getLabel = () => {
    switch (status) {
      case "thinking":
        return t("status.thinking");
      case "searching":
        return searchQuery
          ? t("status.searchingQuery", { query: searchQuery })
          : t("status.searching");
      case "responding":
        return t("status.generating");
      default:
        return "";
    }
  };

  return (
    <div className="flex flex-col gap-2 animate-fade-in my-2">
      <div className="flex items-center gap-3 bg-[#131825]/80 backdrop-blur-md border border-cyan-500/30 rounded-full px-4 py-2 w-fit shadow-lg shadow-cyan-500/10 pulse-ring-active">
        <div className="relative flex items-center justify-center w-6 h-6 rounded-lg bg-gradient-to-br from-cyan-400 via-blue-500 to-indigo-600 p-[1px]">
          <div className="flex items-center justify-center w-full h-full bg-[#080b11] rounded-[7px]">
            <svg className="w-3.5 h-3.5 text-cyan-400 animate-pulse" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2C12 7.52285 7.52285 12 2 12C7.52285 12 12 16.4772 12 22C12 16.4772 16.4772 12 22 12C16.4772 12 12 7.52285 12 2Z" />
            </svg>
          </div>
        </div>
        <span className="shimmer-text font-medium text-sm tracking-wide">{getLabel()}</span>
        <span className="text-xs text-cyan-500/70 font-mono ml-2">{elapsed}s</span>
      </div>

      {elapsed >= 5 && status !== "responding" && (
        <div className="text-xs text-gray-500 ml-4 animate-fade-in italic">
          {t(WAITING_KEYS[messageIndex])}
        </div>
      )}
    </div>
  );
}
