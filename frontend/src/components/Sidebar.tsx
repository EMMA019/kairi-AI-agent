import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import type { SessionInfo } from "../types";
import { useLocale } from "../i18n";

interface ProjectInfo {
  id: string;
  name: string;
  description: string;
  file_count: number;
  active: boolean;
}

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  currentSessionId: string;
  onSelectSession: (sessionId: string) => void;
  onNewSession: () => void;
  onDeleteSession: (sessionId: string) => void;
  refreshTrigger: number;
}


export function Sidebar({
  isOpen,
  onClose,
  currentSessionId,
  onSelectSession,
  onNewSession,
  onDeleteSession,
  refreshTrigger,
}: SidebarProps) {
  const { t } = useLocale();
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [_activeProject, setActiveProject] = useState<string>("main");

  // APIから履歴を取得
  const fetchSessions = async () => {
    try {
      setIsLoading(true);
      const res = await apiFetch("/api/history");
      if (res.ok) {
        const data = await res.json();
        setSessions(data.sessions || []);
      }
    } catch (e) {
      console.error("履歴取得エラー:", e);
    } finally {
      setIsLoading(false);
    }
  };


  // プロジェクト一覧をAPIから取得
  const fetchProjects = async () => {
    try {
      const res = await apiFetch("/api/project");
      if (res.ok) {
        const data = await res.json();
        setProjects(data.projects || []);
        const active = data.projects?.find((p: ProjectInfo) => p.active);
        if (active) setActiveProject(active.id);
      }
    } catch (e) {
      console.error("プロジェクト取得エラー:", e);
    }
  };

  const handleSwitchProject = async (projectId: string) => {
    try {
      const res = await apiFetch("/api/project/switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId }),
      });
      if (res.ok) {
        setActiveProject(projectId);
        fetchProjects();
      }
    } catch (e) {
      console.error("プロジェクト切替エラー:", e);
    }
  };

  const handleCreateProject = async () => {
    const name = prompt(t("sidebar.projectNamePrompt"));
    if (!name || !name.trim()) return;
    try {
      const res = await apiFetch("/api/project", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim() }),
      });
      if (res.ok) {
        fetchProjects();
      }
    } catch (e) {
      console.error("プロジェクト作成エラー:", e);
    }
  };

  useEffect(() => {
    fetchSessions();
    fetchProjects();
  }, [isOpen, currentSessionId, refreshTrigger]);


  return (
    <>
      {/* モバイル用オーバーレイ */}
      <div 
        className={`fixed inset-0 bg-black/50 z-30 transition-opacity md:hidden ${isOpen ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
        onClick={onClose}
      />

      <div 
        className={`fixed inset-y-0 left-0 bg-[#0b0f19]/80 backdrop-blur-2xl border-white/5 flex flex-col z-40 transition-all duration-300 md:relative overflow-hidden ${isOpen ? 'translate-x-0 w-64 border-r shadow-xl' : '-translate-x-full w-64 md:w-0 md:translate-x-0 border-r md:border-r-0'}`}
        style={{
          paddingTop: 'env(safe-area-inset-top)',
          paddingBottom: 'env(safe-area-inset-bottom)'
        }}
      >
        
        {/* Kairi ブランドヘッダー */}
        <div className="p-4 pt-6 border-b border-white/5 shrink-0">
          <div className="flex items-center gap-3">
            {/* スタイリッシュな海里（Kairi）オーシャン・スパークルスター AI ロゴ */}
            <div className="relative flex items-center justify-center w-9 h-9 rounded-xl bg-gradient-to-br from-cyan-400 via-blue-500 to-indigo-600 p-[1.5px] shadow-lg shadow-cyan-500/20 shrink-0">
              <div className="flex items-center justify-center w-full h-full bg-[#080c14] rounded-[10px]">
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none">
                  <defs>
                    <linearGradient id="kairi-ocean-grad" x1="0%" y1="0%" x2="100%" y2="100%">
                      <stop offset="0%" stopColor="#22d3ee" />
                      <stop offset="50%" stopColor="#38bdf8" />
                      <stop offset="100%" stopColor="#818cf8" />
                    </linearGradient>
                    <filter id="ocean-glow" x="-20%" y="-20%" width="140%" height="140%">
                      <feGaussianBlur stdDeviation="1.5" result="blur" />
                      <feComposite in="SourceGraphic" in2="blur" operator="over" />
                    </filter>
                  </defs>
                  <path
                    d="M12 2C12 7.52285 7.52285 12 2 12C7.52285 12 12 16.4772 12 22C12 16.4772 16.4772 12 22 12C16.4772 12 12 7.52285 12 2Z"
                    fill="url(#kairi-ocean-grad)"
                    filter="url(#ocean-glow)"
                  />
                </svg>
              </div>
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <h2 className="text-base font-extrabold tracking-tight bg-gradient-to-r from-white via-gray-100 to-gray-300 bg-clip-text text-transparent">Kairi</h2>
                <span className="px-1.5 py-0.5 text-[9px] font-bold rounded-full bg-gradient-to-r from-cyan-500/20 to-purple-500/20 border border-cyan-500/30 text-cyan-300">AI</span>
              </div>
              <p className="text-[10px] text-gray-400 font-medium tracking-wide">{t("brand.subtitle")}</p>
            </div>
            {/* モバイル用閉じるボタン */}
            <button 
              className="md:hidden text-gray-400 hover:text-white shrink-0"
              onClick={onClose}
              aria-label={t("sidebar.closeMenu")}
            >
              ✕
            </button>
          </div>
        </div>

        {/* プロジェクト管理枠 */}
        <div className="p-4 border-b border-white/5 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">{t("sidebar.project")}</span>
            <button 
              onClick={handleCreateProject}
              className="text-xs text-blue-400 hover:text-blue-300 font-medium transition-colors"
            >
              {t("sidebar.newProject")}
            </button>
          </div>
          
          {/* プロジェクト一覧（APIから動的取得） */}
          <div className="flex flex-col gap-1">
            {projects.map((p) => (
              <button
                key={p.id}
                onClick={() => handleSwitchProject(p.id)}
                className={`w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl transition-all duration-200 text-sm border ${
                  p.active
                    ? "bg-blue-500/10 hover:bg-blue-500/15 text-blue-300 border-blue-500/20"
                    : "hover:bg-white/5 text-gray-400 border-transparent hover:border-white/10"
                }`}
              >
                <span className={`w-5 h-5 rounded-md flex items-center justify-center text-[9px] font-bold shadow-sm ${
                  p.active
                    ? "bg-gradient-to-br from-cyan-500 to-blue-600 text-white"
                    : "bg-white/10 text-gray-500"
                }`}>
                  {p.name.charAt(0).toUpperCase()}
                </span>
                <span className={`truncate flex-1 text-left font-medium ${
                  p.active ? "text-blue-200" : "text-gray-400"
                }`}>
                  {p.name}
                </span>
                {p.active && (
                  <span className="text-[10px] text-blue-400/60 bg-blue-500/10 px-1.5 py-0.5 rounded">{t("sidebar.active")}</span>
                )}
                {p.file_count > 0 && (
                  <span className="text-[10px] text-gray-500">{p.file_count}f</span>
                )}
              </button>
            ))}
            
            {projects.length === 0 && (
              <div className="text-gray-500 text-xs text-center py-2">{t("sidebar.noProjects")}</div>
            )}
          </div>
        </div>

        {/* 新規チャットボタン */}
        <div className="p-4">
          <button 
            onClick={() => {
              onNewSession();
              if (window.innerWidth < 768) onClose();
            }}
            className="w-full flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-blue-500 to-purple-500 hover:from-blue-400 hover:to-purple-400 text-white rounded-xl font-medium transition-all duration-300 shadow-md hover:shadow-lg hover:-translate-y-0.5 border border-white/10"
          >
            <span className="text-lg leading-none">+</span>
            <span>{t("sidebar.newChat")}</span>
          </button>
        </div>

        {/* チャット履歴一覧 */}
        <div className="flex-1 overflow-y-auto px-2">
          <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 px-2 mt-2">{t("sidebar.chatHistory")}</div>
          {isLoading && sessions.length === 0 ? (
            <div className="text-gray-500 text-sm text-center py-4">{t("sidebar.loading")}</div>
          ) : sessions.length === 0 ? (
            <div className="text-gray-500 text-sm text-center py-4">{t("sidebar.noHistory")}</div>
          ) : (
            <div className="flex flex-col gap-1">
              {sessions.map((s) => (
                <div 
                  key={s.session_id}
                  className={`group flex items-center justify-between px-3 py-2.5 rounded-xl cursor-pointer transition-all duration-200 ${
                    s.session_id === currentSessionId 
                      ? 'bg-blue-500/15 text-blue-100 border border-blue-500/30' 
                      : 'text-gray-400 hover:bg-white/5 hover:text-gray-200 border border-transparent'
                  }`}
                  onClick={() => {
                    onSelectSession(s.session_id);
                    if (window.innerWidth < 768) onClose();
                  }}
                >
                  <div className="truncate flex-1 text-sm">
                    {s.title || t("sidebar.newChat")}
                  </div>
                  <button 
                    onClick={(e) => {
                      e.stopPropagation();
                      if (confirm("Delete this chat?")) {
                        onDeleteSession(s.session_id);
                      }
                    }}
                    className="opacity-0 group-hover:opacity-100 text-gray-500 hover:text-red-400 p-1"
                    title="Delete"
                    aria-label="Delete chat"
                  >
                    🗑️
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
        

      </div>
    </>
  );
}

