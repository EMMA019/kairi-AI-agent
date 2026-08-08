import { type PipelineStage } from "../hooks/useChat";
import { useLocale } from "../i18n";

interface PipelineIndicatorProps {
  stages: PipelineStage[];
}

export function PipelineIndicator({ stages }: PipelineIndicatorProps) {
  const { t } = useLocale();
  if (!stages || stages.length === 0) return null;

  return (
    <div className="flex flex-col gap-2 my-4 mx-2 animate-fade-in max-w-sm w-full">
      <div className="bg-[#131825]/90 backdrop-blur-xl border border-white/10 rounded-2xl overflow-hidden shadow-2xl">
        <div className="flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-cyan-500/10 to-purple-500/10 border-b border-white/5">
          <div className="relative flex items-center justify-center w-5 h-5 rounded-[6px] bg-gradient-to-br from-cyan-400 to-indigo-600 p-[1px]">
            <div className="w-full h-full bg-[#080b11] rounded-[5px] flex items-center justify-center">
              <svg className="w-3 h-3 text-cyan-400 animate-pulse" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C12 7.52285 7.52285 12 2 12C7.52285 12 16.4772 12 22C12 16.4772 16.4772 12 22 12C16.4772 12 12 7.52285 12 2Z" />
              </svg>
            </div>
          </div>
          <span className="text-xs font-semibold text-gray-300 tracking-wide">{t("status.pipelineHeader")}</span>
        </div>

        <div className="flex flex-col gap-0.5 p-2">
          {stages.map((stage, idx) => (
            <div
              key={idx}
              className={`flex items-start gap-3 px-2 py-1.5 rounded-lg transition-colors duration-300 ${
                stage.status === "active" ? "bg-white/5" : ""
              }`}
            >
              <div className="flex-shrink-0 mt-0.5">
                {stage.status === "done" ? (
                  <svg
                    className="w-3.5 h-3.5 text-emerald-400"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="3"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <polyline points="20 6 9 17 4 12"></polyline>
                  </svg>
                ) : stage.status === "active" ? (
                  <div className="w-3.5 h-3.5 rounded-full border-2 border-cyan-500 border-t-transparent animate-spin"></div>
                ) : (
                  <div className="w-3.5 h-3.5 rounded-full border-2 border-gray-600"></div>
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div
                  className={`text-xs font-medium truncate ${
                    stage.status === "active"
                      ? "text-gray-200 shimmer-text"
                      : stage.status === "done"
                      ? "text-gray-400"
                      : "text-gray-500"
                  }`}
                >
                  {stage.detail}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
