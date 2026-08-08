/**
 * BriefingPanel — 市場ブリーフィング一覧・プレビュー・手動生成・収集ヘルス
 */
import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { apiFetch } from "../utils/api";

type BriefKind = "preopen" | "postclose";

interface BriefingFile {
  filename: string;
  size: number;
  mtime: string;
}

interface HealthPayload {
  pool_total?: number;
  pool_last_18h?: number;
  feeds_failing?: number;
  retention_hours?: number;
  ok?: boolean;
}

export function BriefingPanel() {
  const [files, setFiles] = useState<BriefingFile[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState("");
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [kind, setKind] = useState<BriefKind>("preopen");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadList = useCallback(async () => {
    try {
      const res = await apiFetch("/api/briefing/list");
      if (!res.ok) throw new Error(`list ${res.status}`);
      const data = await res.json();
      setFiles(Array.isArray(data.files) ? data.files : []);
    } catch (e: any) {
      setError(e?.message || "list failed");
    }
  }, []);

  const loadHealth = useCallback(async () => {
    try {
      const res = await apiFetch("/api/news/health");
      if (!res.ok) throw new Error(`health ${res.status}`);
      setHealth(await res.json());
    } catch {
      setHealth(null);
    }
  }, []);

  const loadFile = useCallback(async (filename: string) => {
    setSelected(filename);
    setContent("");
    try {
      const res = await apiFetch(`/api/briefing/file/${encodeURIComponent(filename)}`);
      if (!res.ok) throw new Error(`file ${res.status}`);
      const data = await res.json();
      setContent(data.content || "");
    } catch (e: any) {
      setError(e?.message || "file failed");
    }
  }, []);

  useEffect(() => {
    void loadList();
    void loadHealth();
  }, [loadList, loadHealth]);

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await apiFetch(
        `/api/briefing/generate?kind=${kind}&dry_run=false`,
        { method: "POST" }
      );
      if (!res.ok) throw new Error(`generate ${res.status}`);
      const data = await res.json();
      await loadList();
      await loadHealth();
      const name = (data.path || "").split(/[/\\]/).pop();
      if (name) await loadFile(name);
      else if (data.preview) setContent(data.preview);
    } catch (e: any) {
      setError(e?.message || "generate failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-[11px] text-gray-400">
        <span className={health?.ok ? "text-emerald-400" : "text-amber-400"}>
          Pool {health?.pool_total ?? "—"}
        </span>
        <span>· 18h {health?.pool_last_18h ?? "—"}</span>
        <span>
          · feeds failing{" "}
          <span className={(health?.feeds_failing || 0) > 0 ? "text-amber-400" : ""}>
            {health?.feeds_failing ?? "—"}
          </span>
        </span>
        <span>· retention {health?.retention_hours ?? 72}h</span>
        <button
          type="button"
          onClick={() => {
            void loadList();
            void loadHealth();
          }}
          className="ml-auto rounded border border-white/10 px-2 py-0.5 text-gray-300 hover:bg-white/5"
        >
          Refresh
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as BriefKind)}
          className="rounded-lg border border-white/10 bg-black/40 px-2 py-1.5 text-xs text-gray-200"
        >
          <option value="preopen">寄り前 (preopen)</option>
          <option value="postclose">大引け後 (postclose)</option>
        </select>
        <button
          type="button"
          onClick={() => void generate()}
          disabled={busy}
          className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-1.5 text-xs font-medium text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-50"
        >
          {busy ? "Generating…" : "いま生成"}
        </button>
      </div>

      {error && (
        <div className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          {error}
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-[220px_1fr]">
        <ul className="max-h-[420px] space-y-1 overflow-y-auto rounded-lg border border-white/10 bg-black/20 p-2">
          {files.length === 0 && (
            <li className="px-2 py-3 text-[11px] text-gray-500">保存済みブリーフなし</li>
          )}
          {files.map((f) => (
            <li key={f.filename}>
              <button
                type="button"
                onClick={() => void loadFile(f.filename)}
                className={`w-full rounded-md px-2 py-1.5 text-left text-[11px] transition ${
                  selected === f.filename
                    ? "bg-cyan-500/20 text-cyan-100"
                    : "text-gray-400 hover:bg-white/5 hover:text-gray-200"
                }`}
              >
                <div className="font-medium">{f.filename}</div>
                <div className="text-[10px] text-gray-600">
                  {new Date(f.mtime).toLocaleString("ja-JP")}
                </div>
              </button>
            </li>
          ))}
        </ul>

        <div className="min-h-[280px] max-h-[520px] overflow-y-auto rounded-lg border border-white/10 bg-black/30 p-4 prose prose-invert prose-sm max-w-none prose-headings:text-cyan-100 prose-a:text-cyan-300">
          {content ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          ) : (
            <p className="text-xs text-gray-500">左からブリーフを選ぶか、「いま生成」してください。</p>
          )}
        </div>
      </div>
    </div>
  );
}
