/**
 * ModeBadge — モード状態表示 + 切替トグル
 */
import { useLocale } from "../i18n";

interface ModeBadgeProps {
  mode: "chat" | "task" | "stocks" | "char" | "market";
  status: "idle" | "thinking" | "searching" | "responding" | "planning_search";
  onToggle: () => void;
}

export function ModeBadge({ mode, status, onToggle }: ModeBadgeProps) {
  const { t } = useLocale();

  const getBadgeInfo = () => {
    if (status === "thinking") {
      return { className: "thinking", label: t("mode.thinking") };
    }
    if (status === "searching") {
      return { className: "searching", label: t("mode.searching") };
    }
    if (mode === "stocks" || mode === "market") {
      return { className: "stocks", label: t("mode.market") };
    }
    if (mode === "task") {
      return { className: "task", label: t("mode.workspace") };
    }
    if (mode === "char") {
      return { className: "char", label: t("mode.char") };
    }
    return { className: "chat", label: t("mode.chat") };
  };

  const { className, label } = getBadgeInfo();

  return (
    <button
      className={`mode-badge ${className}`}
      onClick={onToggle}
      title={t("mode.title", { label })}
      aria-label={`${label} mode`}
      id="mode-badge"
    >
      <span className="dot" />
      <span>{label}</span>
    </button>
  );
}
