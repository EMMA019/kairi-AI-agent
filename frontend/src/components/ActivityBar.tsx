import React from "react";
import { useLocale } from "../i18n";

interface ActivityBarProps {
  isSidebarOpen: boolean;
  onToggleSidebar: () => void;
  onNewSession: () => void;
  mode: "chat" | "task" | "char" | "market";
  showAdvancedModes?: boolean;
  onToggleMode: () => void;
  onOpenKVMemory: () => void;
  onOpenSettings: () => void;
  onOpenToolPanel: () => void;
  onOpenAuth: () => void;
}

export const ActivityBar: React.FC<ActivityBarProps> = ({
  isSidebarOpen,
  onToggleSidebar,
  onNewSession,
  mode,
  showAdvancedModes = false,
  onToggleMode,
  onOpenKVMemory,
  onOpenSettings,
  onOpenToolPanel,
  onOpenAuth,
}) => {
  const { t } = useLocale();

  const modeTitle = !showAdvancedModes
    ? mode === "market"
      ? t("nav.modeMarketNextChat")
      : t("nav.modeChatNextMarket")
    : mode === "task"
    ? t("nav.modeWorkspaceNextChar")
    : mode === "char"
    ? t("nav.modeCharNextMarket")
    : mode === "market"
    ? t("nav.modeMarketNextChat")
    : t("nav.modeChatNextWorkspace");

  return (
    <aside
      className="hidden md:flex flex-col items-center justify-between w-14 shrink-0 bg-[#080b11] border-r border-white/5 py-4 z-50 select-none shadow-xl"
      style={{
        paddingTop: "max(1rem, env(safe-area-inset-top))",
        paddingBottom: "max(1rem, env(safe-area-inset-bottom))",
      }}
    >
      {/* トップアクティビティ：ロゴ＆メニュー開閉、新規作成、モード切替 */}
      <div className="flex flex-col items-center gap-4">
        {/* 海里オーシャン・スパークル（サイドバートグル） */}
        <button
          onClick={onToggleSidebar}
          className={`group relative flex items-center justify-center w-10 h-10 rounded-xl transition-all duration-300 ${
            isSidebarOpen
              ? "bg-gradient-to-br from-cyan-500/20 to-blue-600/20 border border-cyan-500/40 shadow-lg shadow-cyan-500/10"
              : "hover:bg-white/5 border border-transparent hover:border-white/10"
          }`}
          title={isSidebarOpen ? t("nav.closeSidebar") : t("nav.openSidebar")}
          aria-label={t("nav.toggleSidebar")}
        >
          <div className="flex items-center justify-center w-7 h-7 rounded-lg bg-gradient-to-br from-cyan-400 via-blue-500 to-indigo-600 p-[1.5px]">
            <div className="flex items-center justify-center w-full h-full bg-[#080b11] rounded-[6px]">
              <svg className="w-4 h-4 group-hover:scale-110 transition-transform" viewBox="0 0 24 24" fill="none">
                <defs>
                  <linearGradient id="rail-sparkle" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#22d3ee" />
                    <stop offset="50%" stopColor="#38bdf8" />
                    <stop offset="100%" stopColor="#818cf8" />
                  </linearGradient>
                </defs>
                <path
                  d="M12 2C12 7.52285 7.52285 12 2 12C7.52285 12 12 16.4772 12 22C12 16.4772 16.4772 12 22 12C16.4772 12 12 7.52285 12 2Z"
                  fill="url(#rail-sparkle)"
                />
              </svg>
            </div>
          </div>
        </button>

        {/* 新規チャットボタン（Geminiペンアイコン仕様） */}
        <button
          onClick={onNewSession}
          className="flex items-center justify-center w-9 h-9 rounded-xl text-gray-400 hover:text-white hover:bg-white/10 transition-all duration-200"
          title={t("nav.newChat")}
          aria-label={t("nav.newChat")}
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 20h9"></path>
            <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>
          </svg>
        </button>

        {/* 本命: Chat ↔ Market。上級ON時のみ Workspace/Char を挟む */}
        <button
          onClick={onToggleMode}
          className={`flex items-center justify-center w-9 h-9 rounded-xl transition-all duration-200 ${
            mode === "task"
              ? "bg-purple-500/20 text-purple-300 border border-purple-500/40 shadow-sm"
              : mode === "char"
              ? "bg-pink-500/20 text-pink-300 border border-pink-500/40 shadow-sm"
              : mode === "market"
              ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm"
              : "text-gray-400 hover:text-white hover:bg-white/10"
          }`}
          title={modeTitle}
          aria-label={modeTitle}
        >
          {mode === "task" ? (
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="16 18 22 12 16 6"></polyline>
              <polyline points="8 6 2 12 8 18"></polyline>
            </svg>
          ) : mode === "char" ? (
            <span className="text-base leading-none">🎭</span>
          ) : mode === "market" ? (
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"></polyline>
              <polyline points="16 7 22 7 22 13"></polyline>
            </svg>
          ) : (
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
            </svg>
          )}
        </button>

        {/* ツールパネル */}
        <button
          onClick={onOpenToolPanel}
          className="flex items-center justify-center w-9 h-9 rounded-xl text-gray-400 hover:text-white hover:bg-white/10 transition-all duration-200"
          title={t("nav.tools")}
          aria-label={t("nav.tools")}
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path>
          </svg>
        </button>
      </div>

      {/* ボトムアクティビティ：KVメモリ、設定 */}
      <div className="flex flex-col items-center gap-3">
        {/* KVメモリ（長期記憶） */}
        <button
          onClick={onOpenKVMemory}
          className="flex items-center justify-center w-9 h-9 rounded-xl text-gray-400 hover:text-cyan-300 hover:bg-cyan-500/10 transition-all duration-200"
          title={t("nav.memory")}
          aria-label={t("nav.memory")}
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2a8 8 0 0 1 8 8c0 3.3-2 6.2-5 7.5V20a2 2 0 0 1-2 2h-2a2 2 0 0 1-2-2v-2.5C6 16.2 4 13.3 4 10a8 8 0 0 1 8-8z" />
            <path d="M12 2v4" />
            <path d="m4.9 7.5 3.5 2" />
            <path d="m19.1 7.5-3.5 2" />
          </svg>
        </button>

        {/* 認証・セキュリティセンターボタン */}
        <button
          onClick={onOpenAuth}
          className="flex items-center justify-center w-9 h-9 rounded-xl text-emerald-400 hover:text-emerald-300 hover:bg-emerald-500/10 transition-all duration-200"
          title={t("nav.security")}
          aria-label={t("nav.security")}
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
          </svg>
        </button>

        {/* 設定ボタン */}
        <button
          onClick={onOpenSettings}
          className="flex items-center justify-center w-9 h-9 rounded-xl text-gray-400 hover:text-white hover:bg-white/10 transition-all duration-200"
          title={t("nav.settings")}
          aria-label={t("nav.settings")}
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3"></circle>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
          </svg>
        </button>
      </div>
    </aside>
  );
};
