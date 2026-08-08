import { memo, useState, useRef, useEffect } from "react";
import { ChatArea } from "./ChatArea";
import { InputArea } from "./InputArea";
import type { ChatMessage } from "../types";
import { CodePanel } from "./CodePanel";
import { apiFetch } from "../utils/api";
import { WorkspaceSidePanel } from "./WorkspaceSidePanel";
import type { CodeBlock } from "./CodePanel";

interface ActivityItem {
  kind: string;
  detail: string;
  ts: number;
}

interface IDEViewProps {
  sessionId: string;
  messages: ChatMessage[];
  streamingContent: string;
  streamingReasoning?: string;
  streamingSources?: Array<{ title: string; url: string; tier?: number }>;
  streamingChart?: any;
  pipelineStages?: Array<{ stage: string; detail: string; status: "pending" | "active" | "done" }>;
  status: "idle" | "thinking" | "searching" | "responding" | "planning_search";
  searchQuery: string | null;
  isFetchingHistory: boolean;
  codeBlocks: CodeBlock[];
  error: string | null;
  onSend: (message: string, forceSearch?: boolean) => void;
  onStop: () => void;
  onCloseIDE: () => void;
}

export const IDEView = memo(({
  sessionId,
  messages,
  streamingContent,
  streamingReasoning,
  streamingSources,
  streamingChart,
  pipelineStages,
  status,
  searchQuery,
  isFetchingHistory,
  error,
  codeBlocks,
  onSend,
  onStop,
  onCloseIDE
}: IDEViewProps) => {
  const [chatWidth, setChatWidth] = useState(380);
  const [showExplorer, setShowExplorer] = useState(true);
  const [openedFiles, setOpenedFiles] = useState<CodeBlock[]>([]);
  const [activeTab, setActiveTab] = useState<"chat" | "workspace">("chat");
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const isDragging = useRef(false);

  useEffect(() => {
    let alive = true;
    const pull = async () => {
      try {
        const res = await apiFetch("/api/workspace/activity?limit=8");
        const data = await res.json();
        if (alive) setActivity(data.activity || []);
      } catch {
        /* ignore */
      }
    };
    pull();
    const id = setInterval(pull, 2500);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [status, messages.length]);

  const handleFileSelect = async (path: string) => {
    try {
      const res = await apiFetch(`/api/workspace/file?path=${encodeURIComponent(path)}`);
      const data = await res.json();
      const ext = path.split(".").pop() || "text";
      const newFile: CodeBlock = {
        language: ext,
        code: data.content,
        path: path,
        index: 9999 + openedFiles.length,
      };

      if (!openedFiles.find(f => f.path === path)) {
        setOpenedFiles(prev => [...prev, newFile]);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleMouseDown = () => {
    isDragging.current = true;
    document.body.style.cursor = "col-resize";
  };

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging.current) return;
      setChatWidth(Math.max(300, Math.min(e.clientX, window.innerWidth * 0.8)));
    };

    const handleMouseUp = () => {
      if (isDragging.current) {
        isDragging.current = false;
        document.body.style.cursor = "";
      }
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, []);

  return (
    <div className="flex-1 flex flex-col md:flex-row w-full h-full overflow-hidden bg-[#0b0f19]">
      {/* モバイル用タブ（md:hidden） */}
      <div className="flex md:hidden bg-[#0d1117] border-b border-[#3c4043] shrink-0 p-1">
        <button
          onClick={() => setActiveTab("chat")}
          className={`flex-1 py-1.5 text-xs font-bold rounded-md ${activeTab === "chat" ? "bg-[#1e1f20] text-white" : "text-gray-400"}`}
        >
          CHAT
        </button>
        <button
          onClick={() => setActiveTab("workspace")}
          className={`flex-1 py-1.5 text-xs font-bold rounded-md ${activeTab === "workspace" ? "bg-[#1e1f20] text-blue-400" : "text-gray-400"}`}
        >
          WORKSPACE
        </button>
      </div>

      {/* 左側: チャットエリア */}
      <div
        className={`${activeTab === "chat" ? "flex" : "hidden"} md:flex flex-col h-full md:border-r border-[#3c4043] shrink-0 bg-[#0d1117] relative w-full md:w-auto`}
        style={{ width: typeof window !== "undefined" && window.innerWidth < 768 ? '100%' : `${chatWidth}px` }}
      >
        {/* ヘッダー */}
        <header
          className="flex justify-between items-center px-3 py-2 border-b border-[#3c4043] bg-[#0b0f19] shrink-0"
        >
          <div className="flex items-center gap-2">
            {/* エクスプローラーが閉じている時だけ、開くためのボタンを表示 */}
            {!showExplorer && (
              <button
                onClick={() => setShowExplorer(true)}
                className="p-1.5 rounded-lg transition-colors text-gray-400 hover:text-white hover:bg-[#1e1f20]"
                title="エクスプローラーを開く"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                </svg>
              </button>
            )}
          </div>
        </header>

        {error && (
          <div className="bg-red-500/15 border-b border-red-500/30 text-red-400 text-xs py-1.5 px-3 text-center shrink-0">
            {error}
          </div>
        )}

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
            onSend={onSend}
          />
        </div>

        <div className="shrink-0 pb-[max(0.5rem,env(safe-area-inset-bottom))] pt-2 px-2 border-t border-[#3c4043] bg-[#0d1117]">
          <InputArea
            onSend={onSend}
            onStop={onStop}
            status={status}
          />
        </div>

        {/* リサイザー */}
        <div
          className="hidden md:block absolute right-0 top-0 bottom-0 w-1.5 cursor-col-resize hover:bg-blue-500/50 active:bg-blue-500 transition-colors z-20"
          style={{ transform: "translateX(50%)" }}
          onMouseDown={handleMouseDown}
        />
      </div>
      
      {/* 中央・右側: ワークスペース (モバイルではタブ切替) */}
      <div className={`${activeTab === "workspace" ? "flex" : "hidden"} md:flex flex-1 flex-col md:flex-row h-full min-w-0 relative w-full`}>
        {/* 中央: アクティビティ + コードパネル */}
        <div className="flex-1 h-full min-w-0 relative flex flex-col">
          {activity.length > 0 && (
            <div className="shrink-0 flex items-center gap-2 px-3 py-1 border-b border-[#3c4043] bg-[#0b0f19] overflow-x-auto text-[11px] text-gray-400">
              <span className="text-gray-600 shrink-0">Activity</span>
              {[...activity].reverse().slice(0, 6).map((a, i) => (
                <span
                  key={`${a.ts}-${i}`}
                  className="shrink-0 px-1.5 py-0.5 rounded bg-[#161b22] text-gray-300 max-w-[12rem] truncate"
                  title={`${a.kind}: ${a.detail}`}
                >
                  <span className="text-sky-400">{a.kind}</span> {a.detail}
                </span>
              ))}
            </div>
          )}
          <div className="flex-1 min-h-0 relative">
            <CodePanel
              codeBlocks={[...openedFiles, ...codeBlocks]}
              isOpen={true}
              onClose={onCloseIDE}
            />
          </div>
        </div>

        {/* 右側: Workspace パネル（Files / Spec / Changes） */}
        {showExplorer && (
          <div className="hidden md:block h-full shrink-0">
            <WorkspaceSidePanel
              sessionId={sessionId}
              onFileSelect={handleFileSelect}
              onToggle={() => setShowExplorer(false)}
              refreshTrigger={`${messages.length}-${codeBlocks.length}-${status}`}
              lastAssistantContent={[...messages].reverse().find((m) => m.role === "assistant")?.content}
            />
          </div>
        )}
      </div>
    </div>
  );
});