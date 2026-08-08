/**
 * Antigravity Chat AI — メインアプリケーション
 * Gemini ライクなモバイルファースト UI
 */
import { useState, useCallback, useEffect, useMemo } from "react";
import { useChat } from "./hooks/useChat";
import { ChatArea } from "./components/ChatArea";
import { InputArea } from "./components/InputArea";
import { ModeBadge } from "./components/ModeBadge";
import { KVMemoryPanel } from "./components/KVMemoryPanel";
import { SettingsModal } from "./components/SettingsModal";
import { AuthModal } from "./components/AuthModal";
import { FirstRunWizard } from "./components/FirstRunWizard";
import { IntegrityBadge } from "./components/IntegrityBadge";
import { Sidebar } from "./components/Sidebar";
import { ActivityBar } from "./components/ActivityBar";
import { IDEView } from "./components/IDEView";
import { MarketView } from "./components/MarketView";
import { ToolPanel } from "./components/ToolPanel";
import type { CodeBlock } from "./components/CodePanel";
import { apiFetch, AUTH_REQUIRED_EVENT } from "./utils/api";
import { getCharBackgroundStyle } from "./utils/charBackground";
import { getShowAdvancedModes } from "./utils/advancedModes";
import { useLocale, setLocaleLocal } from "./i18n";
import "./index.css";

// コードブロック抽出（閉じタグ ``` が確認できたもののみ、および <file> タグ）
function extractCodeBlocks(text: string): CodeBlock[] {
  const blocks: CodeBlock[] = [];
  let index = 0;
  
  // Markdown code blocks
  const mdRegex = /```([^\n]*)\n([\s\S]*?)(?:```|$)/g;
  let match;
  while ((match = mdRegex.exec(text)) !== null) {
    blocks.push({
      language: match[1].trim() || "text",
      code: match[2].trimEnd(),
      index: index++,
    });
  }

  // <file path="...">...</file> blocks
  const fileRegex = /<file path="([^"]+)">\n?([\s\S]*?)(?:<\/file>|$)/g;
  while ((match = fileRegex.exec(text)) !== null) {
    const filePath = match[1];
    const ext = filePath.split('.').pop() || "text";
    blocks.push({
      language: ext,
      code: match[2].trimEnd(),
      path: filePath,
      index: index++,
    });
  }
  
  return blocks;
}

// セッションIDの管理（ローカルストレージで永続化）
function getOrCreateSessionId(): string {
  const key = "antigravity_session_id";
  let sessionId = localStorage.getItem(key);
  if (!sessionId) {
    if (typeof crypto !== "undefined" && crypto.randomUUID) {
      sessionId = crypto.randomUUID();
    } else {
      sessionId = "session-" + Math.random().toString(36).substring(2, 15) + Date.now().toString(36);
    }
    localStorage.setItem(key, sessionId);
  }
  return sessionId;
}

function App() {
  const { locale, t, setLocale } = useLocale();
  const [sessionId, setSessionId] = useState(getOrCreateSessionId);
  const [mode, setMode] = useState<"chat" | "task" | "char" | "market">("chat");
  const [isKVPanelOpen, setIsKVPanelOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [historyRefreshTrigger, setHistoryRefreshTrigger] = useState(0);
  const [userClosedPanel, setUserClosedPanel] = useState(false);
  const [isCodePanelOpen, setIsCodePanelOpen] = useState(false);
  const [isToolPanelOpen, setIsToolPanelOpen] = useState(false);
  const [isAuthOpen, setIsAuthOpen] = useState(false);
  const [charBackground, setCharBackground] = useState("");
  const [showAdvancedModes, setShowAdvancedModesState] = useState(getShowAdvancedModes);

  useEffect(() => {
    const onAdv = (e: Event) => {
      const detail = (e as CustomEvent<boolean>).detail;
      setShowAdvancedModesState(typeof detail === "boolean" ? detail : getShowAdvancedModes());
    };
    window.addEventListener("kairi-advanced-modes", onAdv);
    return () => window.removeEventListener("kairi-advanced-modes", onAdv);
  }, []);

  const fetchCharBackground = useCallback(async () => {
    try {
      const res = await apiFetch("/api/settings");
      if (res.ok) {
        const data = await res.json();
        setCharBackground(data.char_background || "");
        if (data.locale) setLocaleLocal(data.locale);
      }
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    fetchCharBackground();
  }, [fetchCharBackground]);

  const switchLocale = useCallback(
    async (next: "en" | "ja") => {
      setLocale(next);
      try {
        await apiFetch("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ locale: next }),
        });
      } catch (e) {
        console.error(e);
      }
    },
    [setLocale]
  );

  useEffect(() => {
    if (window.innerWidth >= 768) {
      setIsSidebarOpen(true);
    }
    
    // Wake up backend ping
    const wakeBackend = async () => {
      try {
        await apiFetch("/api/ping");
      } catch (e) {
        console.error(e)
      }
    };
    wakeBackend();
    const interval = setInterval(wakeBackend, 10000);

    const onAuthRequired = () => setIsAuthOpen(true);
    window.addEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);

    return () => {
      clearInterval(interval);
      window.removeEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
    };
  }, []);

  const {
    messages,
    status,
    streamingContent,
    streamingReasoning,
    streamingSources,
    streamingChart,
    pipelineStages,
    searchQuery,
    error,
    isFetchingHistory,
    sendMessage,
    cancelStream,
    loadHistory,
  } = useChat(sessionId, () => {
    setHistoryRefreshTrigger(prev => prev + 1);
  });

  useEffect(() => {
    setUserClosedPanel(false);
    setIsCodePanelOpen(false);
  }, [sessionId]);

  useEffect(() => {
    loadHistory();
  }, [sessionId, loadHistory]);

  const codeBlocks = useMemo(() => {
    const allBlocks: CodeBlock[] = [];
    messages.filter(m => m.role === "assistant").forEach(m => {
      allBlocks.push(...extractCodeBlocks(m.content));
    });
    if (streamingContent) {
      allBlocks.push(...extractCodeBlocks(streamingContent));
    }
    return allBlocks;
  }, [messages, streamingContent]);

  useEffect(() => {
    if (codeBlocks.length > 0 && !userClosedPanel) {
      setIsCodePanelOpen(true);
    }
  }, [codeBlocks.length, userClosedPanel]);

  const handleCloseCodePanel = useCallback(() => {
    setIsCodePanelOpen(false);
    setUserClosedPanel(true);
  }, []);

  const handleOpenCodePanel = useCallback(() => {
    setIsCodePanelOpen(true);
    setUserClosedPanel(false);
    setMode("task");
    setIsSidebarOpen(false);
  }, []);

  const handleSend = useCallback(
    (content: string, forceSearch: boolean = false) => {
      // Market は UI モードのみ。API には chat として送る
      const apiMode = mode === "market" ? "chat" : mode;
      sendMessage(content, apiMode, forceSearch);
    },
    [sendMessage, mode]
  );

  const handleToggleMode = useCallback(() => {
    setMode((prev) => {
      // 本命: chat ↔ market。上級ON時のみ IDE/Char を挟む
      let nextMode: "chat" | "task" | "char" | "market" = "chat";
      if (!showAdvancedModes) {
        nextMode = prev === "chat" ? "market" : "chat";
      } else if (prev === "chat") nextMode = "task";
      else if (prev === "task") nextMode = "char";
      else if (prev === "char") nextMode = "market";
      else nextMode = "chat";

      if (nextMode === "task" || nextMode === "market") {
        setIsSidebarOpen(false);
      }

      return nextMode;
    });
  }, [showAdvancedModes]);

  useEffect(() => {
    if (!showAdvancedModes && (mode === "task" || mode === "char")) {
      setMode("chat");
    }
  }, [showAdvancedModes, mode]);

  const handleNewSession = async () => {
    try {
      const res = await apiFetch("/api/history", { 
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (res.ok) {
        const data = await res.json();
        const newId = data.session_id;
        setSessionId(newId);
        localStorage.setItem("antigravity_session_id", newId);
        setHistoryRefreshTrigger(prev => prev + 1);
        // 新規チャットは必ずチャット画面で開始する
        setMode("chat");
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleSelectSession = (id: string) => {
    setSessionId(id);
    localStorage.setItem("antigravity_session_id", id);
    // チャット履歴を開いたら必ずチャット画面に戻す（マーケットままになるのを防止）
    setMode("chat");
  };

  const handleDeleteSession = async (id: string) => {
    try {
      const res = await apiFetch(`/api/history/${id}`, { method: "DELETE" });
      if (res.ok) {
        setHistoryRefreshTrigger(prev => prev + 1);
        if (id === sessionId) {
          handleNewSession();
        }
      }
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="flex h-[100dvh] w-full bg-gradient-to-br from-[#070e20] via-[#0a142c] to-[#081126] text-gray-100 overflow-hidden font-sans relative">
      <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] rounded-full bg-cyan-600/10 blur-[120px] pointer-events-none"></div>
      <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] rounded-full bg-indigo-600/10 blur-[120px] pointer-events-none"></div>

      {/* 左端 Gemini風スマート・アクティビティバー (縦長ナビゲーションレール) */}
      <ActivityBar
        isSidebarOpen={isSidebarOpen}
        onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
        onNewSession={handleNewSession}
        mode={mode}
        showAdvancedModes={showAdvancedModes}
        onToggleMode={handleToggleMode}
        onOpenKVMemory={() => setIsKVPanelOpen(true)}
        onOpenSettings={() => setIsSettingsOpen(true)}
        onOpenToolPanel={() => setIsToolPanelOpen(true)}
        onOpenAuth={() => setIsAuthOpen(true)}
      />

      <Sidebar
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        currentSessionId={sessionId}
        onSelectSession={handleSelectSession}
        onNewSession={handleNewSession}
        onDeleteSession={handleDeleteSession}
        refreshTrigger={historyRefreshTrigger}
      />
      
      <div className="flex-1 flex flex-col h-full overflow-hidden z-10 min-w-0">
        {/* スタイリッシュで洗練されたメインヘッダー */}
        <header 
          className="flex justify-between items-center px-4 md:px-6 border-b border-indigo-500/10 bg-[#070e20]/80 backdrop-blur-md shrink-0 z-[100] relative shadow-sm"
          style={{ 
            paddingTop: 'max(0.75rem, env(safe-area-inset-top))', 
            paddingBottom: '0.75rem',
            height: 'calc(56px + env(safe-area-inset-top))',
            minHeight: '56px'
          }}
        >
          <div className="flex items-center gap-3 overflow-hidden">
            {/* モバイル時のみ表示するハンバーガー開閉ボタン */}
            <button 
              className="md:hidden shrink-0 p-2 text-gray-400 hover:text-white transition-all rounded-lg hover:bg-white/5"
              onClick={() => setIsSidebarOpen(!isSidebarOpen)}
              title={t("nav.toggleSidebar")}
              aria-label={t("nav.toggleSidebar")}
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="3" y1="7" x2="21" y2="7"></line>
                <line x1="3" y1="12" x2="15" y2="12"></line>
                <line x1="3" y1="17" x2="19" y2="17"></line>
              </svg>
            </button>
            <div className="flex items-center gap-2.5">
              <div className="flex items-center justify-center w-6 h-6 rounded-md bg-gradient-to-br from-cyan-400 via-blue-500 to-indigo-600 p-[1px] shadow-sm">
                <div className="w-full h-full bg-[#0b0f19] rounded-[5px] flex items-center justify-center">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none">
                    <path
                      d="M12 2C12 7.52285 7.52285 12 2 12C7.52285 12 12 16.4772 12 22C12 16.4772 16.4772 12 22 12C16.4772 12 12 7.52285 12 2Z"
                      fill="url(#kairi-ocean-grad-header)"
                    />
                    <defs>
                      <linearGradient id="kairi-ocean-grad-header" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stopColor="#22d3ee" />
                        <stop offset="100%" stopColor="#3b82f6" />
                      </linearGradient>
                    </defs>
                  </svg>
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                <h1 className="text-base md:text-lg font-extrabold tracking-tight bg-gradient-to-r from-white via-cyan-100 to-blue-200 bg-clip-text text-transparent truncate">Kairi</h1>
                <span className="hidden sm:inline-flex text-[10px] font-medium text-cyan-400 bg-cyan-500/10 px-2 py-0.5 rounded-full border border-cyan-500/20">{t("brand.subtitle")}</span>
              </div>
            </div>
          </div>

          <div className="shrink-0 ml-4 flex items-center gap-2">
            <div
              className="inline-flex items-center rounded-lg border border-white/10 bg-white/5 p-0.5 text-[10px] font-semibold"
              title={t("nav.localeHint")}
            >
              <button
                type="button"
                onClick={() => void switchLocale("en")}
                className={`px-2 py-1 rounded-md transition-colors ${
                  locale === "en" ? "bg-cyan-500/25 text-cyan-200" : "text-gray-500 hover:text-gray-300"
                }`}
              >
                {t("nav.localeEn")}
              </button>
              <button
                type="button"
                onClick={() => void switchLocale("ja")}
                className={`px-2 py-1 rounded-md transition-colors ${
                  locale === "ja" ? "bg-cyan-500/25 text-cyan-200" : "text-gray-500 hover:text-gray-300"
                }`}
              >
                {t("nav.localeJa")}
              </button>
            </div>
            {/* コードパネル展開バッジ・ボタン */}
            {codeBlocks.length > 0 && (
              <button
                onClick={isCodePanelOpen ? handleCloseCodePanel : handleOpenCodePanel}
                className={`shrink-0 relative p-2 rounded-xl transition-colors ${
                  isCodePanelOpen
                    ? "text-blue-400 bg-blue-500/15 border border-blue-500/30"
                    : "text-gray-400 hover:text-white hover:bg-white/5"
                }`}
                title="Code Panel"
                aria-label="Code Panel"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
                <span className="absolute -top-1 -right-1 min-w-[16px] h-4 flex items-center justify-center rounded-full bg-blue-500 text-[10px] text-white font-medium px-1 shadow">
                  {codeBlocks.length}
                </span>
              </button>
            )}
            <IntegrityBadge />
            <ModeBadge mode={mode} status={status} onToggle={handleToggleMode} />
          </div>
        </header>

        {/* エラー表示 */}
        {error && (
          <div className="bg-red-500/15 border-b border-red-500/30 text-red-400 text-sm py-2 px-4 text-center shrink-0">
            {error}
          </div>
        )}

        <div className="flex-1 flex flex-col overflow-hidden relative min-h-0 min-w-0 w-full">
          {mode === "task" ? (
            <IDEView
              sessionId={sessionId}
              messages={messages}
              streamingContent={streamingContent}
              streamingReasoning={streamingReasoning}
              streamingSources={streamingSources}
              streamingChart={streamingChart}
              pipelineStages={pipelineStages}
              status={status}
              searchQuery={searchQuery}
              isFetchingHistory={isFetchingHistory}
              codeBlocks={codeBlocks}
              error={error}
              onSend={handleSend}
              onStop={cancelStream}
              onCloseIDE={() => setMode("chat")}
            />
          ) : mode === "market" ? (
            <MarketView
              sessionId={sessionId}
              messages={messages}
              streamingContent={streamingContent}
              streamingReasoning={streamingReasoning}
              streamingSources={streamingSources}
              streamingChart={streamingChart}
              pipelineStages={pipelineStages}
              status={status}
              searchQuery={searchQuery}
              isFetchingHistory={isFetchingHistory}
              error={error}
              onSend={handleSend}
              onStop={cancelStream}
              onCloseMarket={() => setMode("chat")}
            />
          ) : (
            <div
              className="flex-1 flex flex-col h-full overflow-hidden relative min-w-0 min-h-0 transition-[background-image] duration-500"
              style={mode === "char" ? getCharBackgroundStyle(charBackground) : undefined}
            >

              <div className="flex-1 overflow-hidden flex flex-col relative min-h-0">
                <ChatArea
                  sessionId={sessionId}
                  messages={messages}
                  streamingContent={streamingContent}
                  streamingReasoning={streamingReasoning}
                  streamingSources={streamingSources}
                  streamingChart={streamingChart}
                  pipelineStages={pipelineStages}
                  status={status}
                  searchQuery={searchQuery}
                  isFetchingHistory={isFetchingHistory}
                  onSend={handleSend}
                />
              </div>

              {/* 入力エリア */}
              <div className="shrink-0 pb-[max(1rem,env(safe-area-inset-bottom))] pt-2">
                <InputArea 
                  onSend={handleSend} 
                  onStop={cancelStream} 
                  status={status} 
                />
              </div>
            </div>
          )}

          {/* KVメモリパネル */}
          <KVMemoryPanel 
            isOpen={isKVPanelOpen} 
            onClose={() => setIsKVPanelOpen(false)} 
          />

          {/* ツールパネル */}
          <ToolPanel
            isOpen={isToolPanelOpen}
            onClose={() => setIsToolPanelOpen(false)}
            messages={messages}
          />

          {/* 設定モーダル */}
          <SettingsModal
            isOpen={isSettingsOpen}
            onClose={() => {
              setIsSettingsOpen(false);
              fetchCharBackground();
            }}
          />

          {/* 初回: DeepSeek キーだけ */}
          <FirstRunWizard onComplete={() => {}} />

          {/* 認証・セキュリティモーダル */}
          <AuthModal
            isOpen={isAuthOpen}
            onClose={() => setIsAuthOpen(false)}
          />

          {/* 📱 モバイル専用 ボトム・ナビゲーションバー (Capacitor/PWA/スマホ最適化) */}
          <nav className="md:hidden shrink-0 bg-[#1e1f20]/95 backdrop-blur-lg border-t border-white/10 px-2 py-1.5 flex items-center justify-around z-30 pb-[max(0.375rem,env(safe-area-inset-bottom))] shadow-lg">
            <button
              onClick={() => setMode("chat")}
              className={`flex flex-col items-center gap-0.5 py-1 px-3 rounded-xl transition-all ${
                mode === "chat" ? "text-blue-400 bg-blue-500/15 scale-105 font-bold" : "text-gray-400 hover:text-white"
              }`}
            >
              <span className="text-base">💬</span>
              <span className="text-[10px] tracking-tight">Chat</span>
            </button>
            {showAdvancedModes && (
              <button
                onClick={() => setMode("task")}
                className={`flex flex-col items-center gap-0.5 py-1 px-3 rounded-xl transition-all ${
                  mode === "task" ? "text-purple-400 bg-purple-500/15 scale-105 font-bold" : "text-gray-400 hover:text-white"
                }`}
              >
                <span className="text-base">💻</span>
                <span className="text-[10px] tracking-tight">Workspace</span>
              </button>
            )}
            <button
              onClick={() => setMode("market")}
              className={`flex flex-col items-center gap-0.5 py-1 px-3 rounded-xl transition-all ${
                mode === "market" ? "text-cyan-400 bg-cyan-500/15 scale-105 font-bold" : "text-gray-400 hover:text-white"
              }`}
            >
              <span className="text-base">📈</span>
              <span className="text-[10px] tracking-tight">Market</span>
            </button>
            {showAdvancedModes && (
              <button
                onClick={() => setMode("char")}
                className={`flex flex-col items-center gap-0.5 py-1 px-3 rounded-xl transition-all ${
                  mode === "char" ? "text-pink-400 bg-pink-500/15 scale-105 font-bold" : "text-gray-400 hover:text-white"
                }`}
              >
                <span className="text-base">🎭</span>
                <span className="text-[10px] tracking-tight">Char</span>
              </button>
            )}
            <button
              onClick={() => setIsKVPanelOpen(true)}
              className={`flex flex-col items-center gap-0.5 py-1 px-3 rounded-xl transition-all ${
                isKVPanelOpen ? "text-amber-400 bg-amber-500/15 scale-105 font-bold" : "text-gray-400 hover:text-white"
              }`}
            >
              <span className="text-base">🧠</span>
              <span className="text-[10px] tracking-tight">Memory</span>
            </button>
            <button
              onClick={() => setIsSettingsOpen(true)}
              className={`flex flex-col items-center gap-0.5 py-1 px-3 rounded-xl transition-all ${
                isSettingsOpen ? "text-gray-200 bg-white/15 scale-105 font-bold" : "text-gray-400 hover:text-white"
              }`}
            >
              <span className="text-base">⚙️</span>
              <span className="text-[10px] tracking-tight">Settings</span>
            </button>
          </nav>
        </div>
      </div>
    </div>
  );
}

export default App;