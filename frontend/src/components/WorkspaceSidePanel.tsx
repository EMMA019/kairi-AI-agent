import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../utils/api";
import { FileExplorer } from "./FileExplorer";

type SideTab = "files" | "spec" | "changes";

interface WorkspaceStatus {
  root: string;
  name: string;
  project_type: string;
  exists: boolean;
}

interface WorkspaceChange {
  path: string;
  before: string;
  after: string;
  op: string;
  ts: number;
}

interface WorkspaceActivity {
  kind: string;
  detail: string;
  ts: number;
}

interface WorkspaceSidePanelProps {
  sessionId: string;
  onFileSelect: (path: string) => void;
  onToggle: () => void;
  refreshTrigger?: string | number;
  lastAssistantContent?: string;
}

function shortDiff(before: string, after: string, max = 8): string {
  const b = before.split("\n");
  const a = after.split("\n");
  const lines: string[] = [];
  const n = Math.max(b.length, a.length);
  for (let i = 0; i < n && lines.length < max; i++) {
    if (b[i] !== a[i]) {
      if (b[i] != null) lines.push(`- ${b[i]}`);
      if (a[i] != null) lines.push(`+ ${a[i]}`);
    }
  }
  if (!lines.length) {
    return after.slice(0, 240) || "(empty)";
  }
  return lines.join("\n");
}

export function WorkspaceSidePanel({
  sessionId,
  onFileSelect,
  onToggle,
  refreshTrigger,
  lastAssistantContent,
}: WorkspaceSidePanelProps) {
  const [tab, setTab] = useState<SideTab>("files");
  const [status, setStatus] = useState<WorkspaceStatus | null>(null);
  const [openPath, setOpenPath] = useState("");
  const [openError, setOpenError] = useState<string | null>(null);
  const [showOpen, setShowOpen] = useState(false);
  const [opening, setOpening] = useState(false);
  const [spec, setSpec] = useState("");
  const [specMsg, setSpecMsg] = useState<string | null>(null);
  const [changes, setChanges] = useState<WorkspaceChange[]>([]);
  const [activity, setActivity] = useState<WorkspaceActivity[]>([]);
  const [selectedChange, setSelectedChange] = useState<string | null>(null);
  const [treeBump, setTreeBump] = useState(0);

  const refreshMeta = useCallback(async () => {
    try {
      const [st, ch, act] = await Promise.all([
        apiFetch("/api/workspace/status").then((r) => r.json()),
        apiFetch("/api/workspace/changes").then((r) => r.json()),
        apiFetch("/api/workspace/activity?limit=20").then((r) => r.json()),
      ]);
      setStatus(st);
      setChanges(ch.changes || []);
      setActivity(act.activity || []);
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    refreshMeta();
    const id = setInterval(refreshMeta, 2500);
    return () => clearInterval(id);
  }, [refreshMeta, refreshTrigger]);

  const handleOpen = async () => {
    setOpening(true);
    setOpenError(null);
    try {
      const res = await apiFetch("/api/workspace/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: openPath.trim() }),
      });
      const data = await res.json();
      if (!res.ok) {
        setOpenError(data.detail || "Failed to open folder");
        return;
      }
      setStatus(data);
      setShowOpen(false);
      setTreeBump((n) => n + 1);
      await refreshMeta();
    } catch (e: any) {
      setOpenError(e?.message || "Failed to open folder");
    } finally {
      setOpening(false);
    }
  };

  const loadLatestSpec = async () => {
    setSpecMsg(null);
    try {
      const res = await apiFetch(
        `/api/workspace/latest-spec?session_id=${encodeURIComponent(sessionId)}`
      );
      const data = await res.json();
      if (data.content) {
        setSpec(data.content);
        setSpecMsg(`Loaded from ${data.source}`);
      } else {
        setSpecMsg("No spec found in this chat yet");
      }
    } catch {
      setSpecMsg("Failed to load spec");
    }
  };

  const useLastAssistant = async () => {
    if (lastAssistantContent?.trim()) {
      setSpec(lastAssistantContent);
      setSpecMsg("Loaded from last reply");
      return;
    }
    await loadLatestSpec();
  };

  const saveSpec = async () => {
    setSpecMsg(null);
    try {
      const res = await apiFetch("/api/workspace/save-spec", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: spec, filename: "SPEC.md" }),
      });
      const data = await res.json();
      if (!res.ok) {
        setSpecMsg(data.detail || "Save failed");
        return;
      }
      setSpecMsg(`Saved ${data.path}`);
      setTreeBump((n) => n + 1);
      await refreshMeta();
    } catch {
      setSpecMsg("Save failed");
    }
  };

  const discard = async (path: string) => {
    try {
      await apiFetch("/api/workspace/discard", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      if (selectedChange === path) setSelectedChange(null);
      setTreeBump((n) => n + 1);
      await refreshMeta();
    } catch (e) {
      console.error(e);
    }
  };

  const active = changes.find((c) => c.path === selectedChange);

  return (
    <div className="w-72 h-full flex flex-col bg-[#0d1117] border-l border-[#3c4043] shrink-0">
      {/* Status / Open folder */}
      <div className="px-3 py-2 border-b border-[#3c4043] space-y-1.5">
        <div className="flex items-center justify-between gap-1">
          <button
            onClick={onToggle}
            className="p-1 rounded hover:bg-[#2a2d2e] text-blue-400"
            title="Close panel"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
          </button>
          <button
            onClick={() => {
              setOpenPath(status?.root || "");
              setShowOpen((v) => !v);
              setOpenError(null);
            }}
            className="flex-1 text-left text-xs text-blue-300 hover:text-blue-200 truncate px-1"
            title={status?.root || "Open folder"}
          >
            {status?.name || "Open folder…"}
          </button>
          {status?.project_type && (
            <span
              className="max-w-[6.5rem] truncate text-[10px] px-1.5 py-0.5 rounded bg-[#1e293b] text-sky-300 border border-sky-900/60"
              title={status.project_type}
            >
              {status.project_type.split(" / ")[0].split(" + ")[0]}
            </span>
          )}
        </div>
        {showOpen && (
          <div className="space-y-1.5">
            <input
              value={openPath}
              onChange={(e) => setOpenPath(e.target.value)}
              placeholder="D:/path/to/project"
              className="w-full text-xs bg-[#161b22] border border-[#3c4043] rounded px-2 py-1.5 text-gray-200 outline-none focus:border-blue-500"
              onKeyDown={(e) => e.key === "Enter" && handleOpen()}
            />
            <div className="flex gap-1">
              <button
                onClick={handleOpen}
                disabled={opening || !openPath.trim()}
                className="flex-1 text-xs py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white"
              >
                {opening ? "Opening…" : "Open"}
              </button>
              <button
                onClick={() => setShowOpen(false)}
                className="text-xs px-2 py-1 rounded text-gray-400 hover:bg-[#2a2d2e]"
              >
                Cancel
              </button>
            </div>
            {openError && <p className="text-[11px] text-red-400">{openError}</p>}
          </div>
        )}
        {activity.length > 0 && (
          <div className="text-[10px] text-gray-500 truncate" title={activity[activity.length - 1]?.detail}>
            {activity[activity.length - 1]?.kind}: {activity[activity.length - 1]?.detail}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-[#3c4043] text-[11px]">
        {([
          ["files", "Files"],
          ["spec", "Spec"],
          ["changes", `Changes${changes.length ? ` (${changes.length})` : ""}`],
        ] as const).map(([id, label]) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex-1 py-1.5 ${
              tab === id ? "text-white border-b-2 border-blue-500" : "text-gray-500 hover:text-gray-300"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "files" && (
        <div className="flex-1 min-h-0 overflow-hidden [&_>div]:w-full [&_>div]:border-l-0">
          <FileExplorer
            onFileSelect={onFileSelect}
            onToggle={onToggle}
            refreshTrigger={`${refreshTrigger}-${treeBump}`}
            embedded
          />
        </div>
      )}

      {tab === "spec" && (
        <div className="flex-1 min-h-0 flex flex-col p-2 gap-2">
          <div className="flex gap-1 flex-wrap">
            <button
              onClick={useLastAssistant}
              className="text-[11px] px-2 py-1 rounded bg-[#21262d] text-gray-300 hover:bg-[#30363d]"
            >
              Load from chat
            </button>
            <button
              onClick={saveSpec}
              className="text-[11px] px-2 py-1 rounded bg-blue-600 text-white hover:bg-blue-500"
            >
              Save SPEC.md
            </button>
          </div>
          {specMsg && <p className="text-[11px] text-gray-400">{specMsg}</p>}
          <textarea
            value={spec}
            onChange={(e) => setSpec(e.target.value)}
            placeholder="Surface spec (user-facing). Hearing → Spec → Plan → Task."
            className="flex-1 min-h-0 resize-none text-xs bg-[#161b22] border border-[#3c4043] rounded p-2 text-gray-200 outline-none focus:border-blue-500 font-mono"
          />
        </div>
      )}

      {tab === "changes" && (
        <div className="flex-1 min-h-0 flex flex-col">
          <div className="flex-1 overflow-y-auto">
            {changes.length === 0 ? (
              <p className="px-3 py-3 text-xs text-gray-500">No AI file changes yet.</p>
            ) : (
              changes.map((c) => (
                <div
                  key={c.path}
                  className={`px-2 py-1.5 border-b border-[#21262d] cursor-pointer hover:bg-[#161b22] ${
                    selectedChange === c.path ? "bg-[#161b22]" : ""
                  }`}
                  onClick={() => setSelectedChange(c.path)}
                >
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-xs text-gray-200 truncate" title={c.path}>
                      {c.path}
                    </span>
                    <span className="text-[10px] text-amber-400 shrink-0">{c.op}</span>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      discard(c.path);
                    }}
                    className="mt-1 text-[10px] text-red-400 hover:text-red-300"
                  >
                    Discard
                  </button>
                </div>
              ))
            )}
          </div>
          {active && (
            <pre className="max-h-40 overflow-auto text-[10px] p-2 border-t border-[#3c4043] bg-[#0b0f19] text-gray-400 whitespace-pre-wrap">
              {shortDiff(active.before, active.after)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
