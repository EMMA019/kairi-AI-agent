/**
 * ToolPanel — 生きたアクティビティログ・セキュリティ制御・ツール管理センター
 */
import { useState, useEffect, useMemo } from "react";
import { apiFetch } from "../utils/api";

interface CacheInfo { total: number; recent_30min: number; }
interface MCPServer { name: string; command: string; args: string[]; description: string; type: string; }

export interface ToolPanelProps {
  isOpen: boolean;
  onClose: () => void;
  messages?: Array<{
    role: string;
    content: string;
    timestamp?: Date | string;
  }>;
}

interface ActivityItem {
  id: string;
  type: "search" | "command" | "file" | "url" | "other";
  title: string;
  detail: string;
  time: string;
}

export function ToolPanel({ isOpen, onClose, messages = [] }: ToolPanelProps) {
  const [tools, setTools] = useState<any[]>([]);
  const [cacheStatus, setCacheStatus] = useState<Record<string, CacheInfo> | null>(null);
  const [execResult, setExecResult] = useState<string>("");
  const [selectedTool, setSelectedTool] = useState<string>("");
  const [paramInput, setParamInput] = useState<string>("{}");
  
  // セキュリティ設定 (HITL & サプライチェーン防衛)
  const [hitlEnabled, setHitlEnabled] = useState<boolean>(() => {
    return localStorage.getItem("kairi_hitl_enabled") !== "false";
  });

  // MCP state
  const [mcpServers, setMcpServers] = useState<MCPServer[]>([]);
  const [newServerName, setNewServerName] = useState("");
  const [newServerCmd, setNewServerCmd] = useState("npx");
  const [newServerArgs, setNewServerArgs] = useState("");
  const [newServerDesc, setNewServerDesc] = useState("");
  const [mcpResult, setMcpResult] = useState("");
  const [mcpToolList, setMcpToolList] = useState<Record<string, any[]>>({});
  const [mcpSelectedServer, setMcpSelectedServer] = useState<string>("");
  const [mcpSelectedTool, setMcpSelectedTool] = useState<string>("");
  const [mcpToolArgs, setMcpToolArgs] = useState("{}");

  const tabs = ["⚡ Activity", "🛡️ Security", "🔧 Tools", "📡 MCP"];
  const [tab, setTab] = useState("⚡ Activity");

  useEffect(() => {
    if (!isOpen) return;
    apiFetch("/api/tools").then(r => r.json()).then(d => setTools(d.tools || [])).catch(() => {});
    apiFetch("/api/cache/status").then(r => r.json()).then(d => setCacheStatus(d.status || null)).catch(() => {});
    apiFetch("/api/mcp/servers").then(r => r.json()).then(d => setMcpServers(d.servers || [])).catch(() => {});
  }, [isOpen]);

  const toggleHitl = () => {
    const next = !hitlEnabled;
    setHitlEnabled(next);
    localStorage.setItem("kairi_hitl_enabled", String(next));
  };

  // メッセージ履歴から生きたツール実行アクティビティを抽出
  const activities = useMemo<ActivityItem[]>(() => {
    const list: ActivityItem[] = [];
    messages.forEach((m, idx) => {
      if (m.role !== "assistant") return;
      const text = m.content || "";
      const timeStr = m.timestamp instanceof Date
        ? m.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        : "";

      // 検索アクティビティ
      const searchMatches = text.matchAll(/<search\s+query=(["'])(.*?)\1.*?>/g);
      for (const sm of searchMatches) {
        list.push({
          id: `search-${idx}-${sm[2]}`,
          type: "search",
          title: "🔍 Web Search",
          detail: sm[2],
          time: timeStr,
        });
      }

      // コマンド実行アクティビティ
      const cmdMatches = text.matchAll(/<run_command>(.*?)<\/run_command>/gs);
      for (const cm of cmdMatches) {
        list.push({
          id: `cmd-${idx}-${list.length}`,
          type: "command",
          title: "💻 Command Execution",
          detail: cm[1].trim(),
          time: timeStr,
        });
      }

      // ファイル作成アクティビティ
      const fileMatches = text.matchAll(/<file\s+path=(["'])(.*?)\1.*?>/g);
      for (const fm of fileMatches) {
        list.push({
          id: `file-${idx}-${fm[2]}`,
          type: "file",
          title: "📄 File Creation/Update",
          detail: fm[2],
          time: timeStr,
        });
      }

      // URL読み込み
      const urlMatches = text.matchAll(/<read_url\s+url=(["'])(.*?)\1.*?>/g);
      for (const um of urlMatches) {
        list.push({
          id: `url-${idx}-${um[2]}`,
          type: "url",
          title: "🌐 Page Scraping",
          detail: um[2],
          time: timeStr,
        });
      }
    });
    return list.reverse(); // 最新を上に表示
  }, [messages]);

  const handleExecute = async () => {
    if (!selectedTool) return;
    try {
      const params = JSON.parse(paramInput || "{}");
      const res = await apiFetch("/api/tools/execute", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: selectedTool, params }),
      });
      setExecResult((await res.json()).result || "[no result]");
    } catch (e: any) { setExecResult(`[ERROR] ${e.message}`); }
  };

  const handleAddMCPServer = async () => {
    if (!newServerName || !newServerArgs) return;
    try {
      const res = await apiFetch("/api/mcp/servers", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: newServerName, command: newServerCmd,
          args: newServerArgs.split(" ").filter(Boolean),
          description: newServerDesc,
        }),
      });
      if (res.ok) {
        setNewServerName(""); setNewServerArgs(""); setNewServerDesc("");
        apiFetch("/api/mcp/servers").then(r => r.json()).then(d => setMcpServers(d.servers || []));
      }
    } catch (e: any) { console.error(e); }
  };

  const handleDeleteMCPServer = async (name: string) => {
    await apiFetch(`/api/mcp/servers/${name}`, { method: "DELETE" });
    apiFetch("/api/mcp/servers").then(r => r.json()).then(d => setMcpServers(d.servers || []));
  };

  const handleFetchMCPTools = async (serverName: string) => {
    if (mcpToolList[serverName]) { setMcpToolList({}); return; }
    try {
      const res = await apiFetch(`/api/mcp/servers/${serverName}/tools`);
      const data = await res.json();
      setMcpToolList(prev => ({ ...prev, [serverName]: data.tools || [] }));
    } catch (e: any) { setMcpToolList(prev => ({ ...prev, [serverName]: [] })); }
  };

  const handleCallMCPTool = async () => {
    if (!mcpSelectedServer || !mcpSelectedTool) return;
    setMcpResult("Running...");
    try {
      const args = JSON.parse(mcpToolArgs || "{}");
      const res = await apiFetch(`/api/mcp/servers/${mcpSelectedServer}/call`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool: mcpSelectedTool, arguments: args }),
      });
      setMcpResult((await res.json()).result || "[no result]");
    } catch (e: any) { setMcpResult(`[ERROR] ${e.message}`); }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-[#11141d] border border-[#2d3139] rounded-2xl w-full max-w-3xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
        {/* ヘッダー */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#2d3139] bg-[#161a25]">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-blue-500/20 border border-blue-500/40 flex items-center justify-center text-blue-400">
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path>
              </svg>
            </div>
            <div>
              <h2 className="text-base font-bold text-white tracking-wide">AI Tool & Activity Center</h2>
              <p className="text-[11px] text-gray-400">Real-time Execution History · Security Audit · Tool Sandbox</p>
            </div>
          </div>
          <div className="flex items-center gap-1.5 bg-[#0b0e14] p-1 rounded-xl border border-[#2d3139]">
            {tabs.map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all ${
                  tab === t
                    ? "bg-blue-600 text-white shadow-md shadow-blue-600/30"
                    : "text-gray-400 hover:text-white hover:bg-[#1f2430]"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-white rounded-lg hover:bg-[#232834] transition-colors"
          >
            ✕
          </button>
        </div>

        {/* コンテンツエリア */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {/* タブ 1: ⚡ アクティビティタイムライン (生きた機能) */}
          {tab === "⚡ Activity" && (
            <div>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold text-gray-200 flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse"></span>
                  Real-time Execution Timeline
                </h3>
                <span className="text-xs text-gray-400 bg-[#1a1f2c] px-2.5 py-1 rounded-full border border-[#2d3139]">
                  Count: {activities.length}
                </span>
              </div>

              {activities.length === 0 ? (
                <div className="text-center py-12 bg-[#161a25] rounded-xl border border-dashed border-[#2d3139]">
                  <p className="text-sm text-gray-400 font-medium">No activities recorded yet</p>
                  <p className="text-xs text-gray-500 mt-1">When AI executes searches or commands, they will be logged live here</p>
                </div>
              ) : (
                <div className="space-y-2.5">
                  {activities.map((act) => (
                    <div
                      key={act.id}
                      className="p-3.5 bg-[#161a25] rounded-xl border border-[#2d3139] hover:border-[#3e4452] transition-colors"
                    >
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-xs font-semibold text-blue-400 flex items-center gap-1.5">
                          {act.title}
                        </span>
                        <span className="text-[11px] text-gray-500 font-mono">{act.time}</span>
                      </div>
                      <pre className="text-xs text-gray-300 font-mono bg-[#0b0e14] p-2.5 rounded-lg overflow-x-auto border border-[#232834]">
                        {act.detail}
                      </pre>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* タブ 2: 🛡️ セキュリティ (中立セキュリティエンジニア基準) */}
          {tab === "🛡️ Security" && (
            <div className="space-y-4">
              <div className="bg-[#161a25] p-4 rounded-xl border border-[#2d3139]">
                <div className="flex items-start justify-between">
                  <div>
                    <h4 className="text-sm font-bold text-white flex items-center gap-2">
                      🛡️ Command Execution Approval Mode (HITL)
                    </h4>
                    <p className="text-xs text-gray-400 mt-1 leading-relaxed">
                      Requires user approval before AI runs side-effect commands (npm install, pip install, file operations, etc.).
                    </p>
                  </div>
                  <button
                    onClick={toggleHitl}
                    className={`px-4 py-2 rounded-xl text-xs font-semibold transition-all shadow-md ${
                      hitlEnabled
                        ? "bg-green-600 text-white shadow-green-600/30"
                        : "bg-[#282d3b] text-gray-400 hover:text-white"
                    }`}
                  >
                    {hitlEnabled ? "ACTIVE (Approval Required)" : "OFF (Automatic)"}
                  </button>
                </div>
              </div>

              <div className="bg-[#161a25] p-4 rounded-xl border border-[#2d3139]">
                <h4 className="text-sm font-bold text-white flex items-center gap-2 mb-2">
                  🔒 npm Supply Chain Attack & Malware Defense Shield
                </h4>
                <div className="flex items-center gap-2 text-xs text-green-400 font-medium bg-[#0b0e14] p-3 rounded-lg border border-green-500/20">
                  <span className="w-2 h-2 rounded-full bg-green-400"></span>
                  Active: Automatically injects --ignore-scripts flag into all npm install commands
                </div>
                <p className="text-[11px] text-gray-500 mt-2">
                  Completely blocks malicious postinstall scripts from running malware or exfiltrating data.
                </p>
              </div>

              <div className="bg-[#161a25] p-4 rounded-xl border border-[#2d3139]">
                <h4 className="text-sm font-bold text-white flex items-center gap-2 mb-2">
                  ⚖️ Fact Verification & Anti-Hallucination Engine
                </h4>
                <div className="flex items-center gap-2 text-xs text-cyan-400 font-medium bg-[#0b0e14] p-3 rounded-lg border border-cyan-500/20">
                  <span className="w-2 h-2 rounded-full bg-cyan-400"></span>
                  Active: Filters unverified numeric claims & suppresses completion until build check passes
                </div>
                {cacheStatus && (
                  <div className="mt-3 pt-3 border-t border-[#232834] flex items-center justify-between text-xs text-gray-400">
                    <span>Total cache entries: {Object.keys(cacheStatus).length} categories</span>
                    <span className="text-blue-400">Real-time Sync</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* タブ 3: 🔧 ツール一覧 */}
          {tab === "🔧 Tools" && (
            <div className="space-y-5 animate-in fade-in duration-200">
              <div>
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-bold text-gray-200 flex items-center gap-2 leading-normal">
                    <span className="w-2 h-2 rounded-full bg-blue-400"></span>
                    Registered System Tools ({tools.length})
                  </h3>
                  <span className="text-xs text-gray-400 leading-normal">Click to select parameters</span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
                  {tools.map((t: any) => {
                    const isSelected = selectedTool === t.name;
                    return (
                      <button
                        key={t.name}
                        onClick={() => {
                          setSelectedTool(t.name);
                          setParamInput(JSON.stringify(t.schema?.properties ? Object.fromEntries(Object.keys(t.schema.properties).map(k => [k, ""])) : {}, null, 2));
                          setExecResult("");
                        }}
                        className={`flex flex-col items-start px-4 py-3 rounded-xl border transition-all text-left group ${
                          isSelected
                            ? "border-blue-500 bg-gradient-to-br from-blue-600/25 to-indigo-600/20 shadow-lg shadow-blue-500/10"
                            : "border-[#2d3139] bg-[#161a25] hover:bg-[#1f2432] hover:border-[#3e4452]"
                        }`}
                      >
                        <div className="flex items-center justify-between w-full mb-1">
                          <span className={`text-xs font-bold font-mono leading-normal ${isSelected ? "text-blue-300" : "text-gray-200 group-hover:text-white"}`}>
                            {t.name}
                          </span>
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-black/40 text-gray-400 border border-white/5">
                            Tool
                          </span>
                        </div>
                        <span className="text-[11px] text-gray-400 line-clamp-1 leading-relaxed">
                          {t.name === "echo" && "Test text echo"}
                          {t.name === "list_tools" && "List registered tools"}
                          {t.name === "calc" && "High-precision math calculation"}
                          {!["echo", "list_tools", "calc"].includes(t.name) && "System built-in tool"}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {selectedTool && (
                <div className="p-5 bg-[#161a25] rounded-2xl border border-[#2d3139] shadow-xl space-y-4">
                  <div className="flex items-center justify-between border-b border-[#2d3139] pb-3">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-bold text-blue-400 font-mono bg-blue-500/10 px-2.5 py-1 rounded-md border border-blue-500/20 leading-normal">
                        ⚡ {selectedTool}
                      </span>
                      <span className="text-xs text-gray-400 leading-normal">Test Execution Parameters</span>
                    </div>
                    <span className="text-[11px] text-gray-500 font-mono">JSON Format</span>
                  </div>

                  <div className="relative">
                    <textarea
                      value={paramInput}
                      onChange={e => setParamInput(e.target.value)}
                      className="w-full h-36 bg-[#0b0e14] border border-[#2d3139] rounded-xl p-4 text-xs text-gray-200 font-mono leading-relaxed resize-none focus:outline-none focus:border-blue-500 transition-colors shadow-inner"
                      placeholder='{"key": "value"}'
                    />
                  </div>

                  <div className="flex items-center justify-between pt-1">
                    <button
                      onClick={handleExecute}
                      className="inline-flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl text-xs font-bold leading-normal transition-all shadow-lg shadow-blue-600/25 active:scale-95"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <polygon points="5 3 19 12 5 21 5 3"></polygon>
                      </svg>
                      Run Test
                    </button>
                  </div>

                  {execResult && (
                    <div className="mt-4 border-t border-[#2d3139] pt-4">
                      <div className="text-[11px] font-semibold text-gray-400 mb-1.5">Execution Result Output</div>
                      <pre className="p-4 bg-[#0b0e14] border border-[#232834] rounded-xl text-xs text-green-400 max-h-48 overflow-auto font-mono leading-relaxed">
                        {execResult}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* タブ 4: 📡 MCP */}
          {tab === "📡 MCP" && (
            <div className="space-y-4">
              <div>
                <h3 className="text-sm font-semibold text-gray-300 mb-2">📡 Connected MCP Servers ({mcpServers.length})</h3>
                {mcpServers.map(s => (
                  <div key={s.name} className="flex items-center justify-between bg-[#161a25] rounded-xl px-4 py-3 border border-[#2d3139] mb-2.5">
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-white font-semibold truncate">{s.name}</div>
                      <div className="text-xs text-gray-400 font-mono mt-0.5 truncate">{s.command} {s.args.join(" ")}</div>
                      {s.description && <div className="text-xs text-gray-500 mt-1">{s.description}</div>}
                    </div>
                    <div className="flex items-center gap-2 shrink-0 ml-3">
                      <button
                        onClick={() => { handleFetchMCPTools(s.name); setMcpSelectedServer(s.name); }}
                        className="px-3 py-1.5 text-xs bg-blue-600/20 text-blue-400 border border-blue-500/30 rounded-lg hover:bg-blue-600/30 font-medium"
                      >
                        View Tools
                      </button>
                      <button
                        onClick={() => handleDeleteMCPServer(s.name)}
                        className="p-1.5 text-xs text-red-400 hover:text-red-300 rounded hover:bg-red-500/10"
                      >
                        ✕
                      </button>
                    </div>
                  </div>
                ))}
              </div>

              {/* MCPツール実行パネル */}
              {mcpSelectedServer && (
                <div className="bg-[#161a25] p-4 rounded-xl border border-[#2d3139] space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="text-xs font-bold text-blue-400 font-mono">
                      ⚡ MCP Tools ({mcpSelectedServer})
                    </h4>
                    <span className="text-[11px] text-gray-500">
                      Select tool & test execution
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {(mcpToolList[mcpSelectedServer] || []).map((t: any) => (
                      <button
                        key={t.name}
                        onClick={() => setMcpSelectedTool(t.name)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-mono transition-colors ${
                          mcpSelectedTool === t.name
                            ? "bg-blue-600 text-white"
                            : "bg-[#0b0e14] text-gray-300 border border-[#2d3139]"
                        }`}
                      >
                        {t.name}
                      </button>
                    ))}
                  </div>
                  {mcpSelectedTool && (
                    <div className="space-y-2 pt-2 border-t border-[#232834]">
                      <textarea
                        value={mcpToolArgs}
                        onChange={e => setMcpToolArgs(e.target.value)}
                        className="w-full h-24 bg-[#0b0e14] border border-[#2d3139] rounded-lg p-2.5 text-xs text-gray-200 font-mono resize-none focus:outline-none focus:border-blue-500"
                        placeholder='{"arg": "value"}'
                      />
                      <button
                        onClick={handleCallMCPTool}
                        className="w-full py-2 bg-gradient-to-r from-blue-600 to-indigo-600 text-white rounded-lg text-xs font-bold shadow-md"
                      >
                        Execute MCP Tool
                      </button>
                      {mcpResult && (
                        <pre className="p-3 bg-[#0b0e14] border border-[#232834] rounded-lg text-xs text-green-400 max-h-36 overflow-auto font-mono">
                          {mcpResult}
                        </pre>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* サーバー追加 UI */}
              <div className="bg-[#161a25] p-4 rounded-xl border border-[#2d3139]">
                <h4 className="text-xs font-semibold text-gray-300 mb-3">➕ Register New MCP Server</h4>
                <div className="space-y-2">
                  <input
                    value={newServerName}
                    onChange={e => setNewServerName(e.target.value)}
                    placeholder="Server name (e.g. sqlite-server)"
                    className="w-full bg-[#0b0e14] border border-[#2d3139] rounded-lg px-3 py-2 text-xs text-gray-200 focus:outline-none focus:border-blue-500"
                  />
                  <div className="flex gap-2">
                    <input
                      value={newServerCmd}
                      onChange={e => setNewServerCmd(e.target.value)}
                      placeholder="Command (npx)"
                      className="w-1/3 bg-[#0b0e14] border border-[#2d3139] rounded-lg px-3 py-2 text-xs text-gray-200 focus:outline-none focus:border-blue-500"
                    />
                    <input
                      value={newServerArgs}
                      onChange={e => setNewServerArgs(e.target.value)}
                      placeholder="Args (-y @modelcontextprotocol/server-sqlite db.sqlite)"
                      className="w-2/3 bg-[#0b0e14] border border-[#2d3139] rounded-lg px-3 py-2 text-xs text-gray-200 focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <button
                    onClick={handleAddMCPServer}
                    className="w-full py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold transition-colors mt-1"
                  >
                    Add MCP Server
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}