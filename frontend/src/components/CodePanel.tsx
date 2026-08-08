/**
 * CodePanel (WorkspacePanel) — Canvas/Artifact風コードブロック表示・編集パネル
 * AIの応答から抽出されたコードブロックをタブで表示し、Monaco Editorで直接編集・保存可能。
 * MarkdownやMermaidのプレビュー機能、ワークスペース全体のZIPダウンロード機能も提供。
 */
import { useState, useEffect, useRef } from "react";
import Editor from "@monaco-editor/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import mermaid from "mermaid";
import { apiFetch } from "../utils/api";

export interface CodeBlock {
  language: string;
  code: string;
  index: number;
  path?: string;
}

interface CodePanelProps {
  codeBlocks: CodeBlock[];
  isOpen: boolean;
  onClose: () => void;
}

function normalizeLanguage(lang: string): string {
  const map: Record<string, string> = {
    js: "javascript",
    ts: "typescript",
    tsx: "typescript",
    jsx: "javascript",
    py: "python",
    rb: "ruby",
    sh: "shell",
    bash: "shell",
    yml: "yaml",
    md: "markdown",
    "": "plaintext",
  };
  return map[lang.toLowerCase()] || lang.toLowerCase();
}

function getExtension(lang: string): string {
  const map: Record<string, string> = {
    javascript: ".js",
    typescript: ".ts",
    tsx: ".tsx",
    jsx: ".jsx",
    python: ".py",
    ruby: ".rb",
    bash: ".sh",
    html: ".html",
    css: ".css",
    json: ".json",
    yaml: ".yml",
    markdown: ".md",
    text: ".txt",
    plaintext: ".txt",
  };
  return map[normalizeLanguage(lang)] || ".txt";
}

// Mermaidレンダリング用コンポーネント
const Mermaid = ({ chart }: { chart: string }) => {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    mermaid.initialize({ startOnLoad: false, theme: "dark" });
    if (ref.current) {
      mermaid.render("mermaid-svg-" + Math.random().toString(36).substr(2, 9), chart).then(({ svg }) => {
        if (ref.current) {
          ref.current.innerHTML = svg;
        }
      }).catch(e => {
        console.error("Mermaid error", e);
      });
    }
  }, [chart]);
  return <div ref={ref} className="mermaid-container flex justify-center p-4 bg-white/5 rounded-lg my-4" />;
};

export function CodePanel({ codeBlocks, isOpen, onClose }: CodePanelProps) {
  const [activeTab, setActiveTab] = useState(0);
  const [copied, setCopied] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [viewMode, setViewMode] = useState<"edit" | "preview" | "split">("split");
  const prevBlockCountRef = useRef(codeBlocks.length);
  
  // ユーザーのローカルな編集内容を保持するステート (keyは block.path または index)
  const [edits, setEdits] = useState<Record<string, string>>({});

  useEffect(() => {
    if (codeBlocks.length > prevBlockCountRef.current) {
      setActiveTab(codeBlocks.length - 1);
    }
    prevBlockCountRef.current = codeBlocks.length;
  }, [codeBlocks.length]);

  useEffect(() => {
    if (!isOpen) {
      setCopied(false);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  if (codeBlocks.length === 0) {
    return (
      <div 
        className="code-panel flex-1 flex flex-col bg-[#0d1117] border-l border-[#30363d] items-center justify-center w-full h-full relative"
      >
        <div className="absolute top-3 right-4">
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-gray-400 hover:text-white hover:bg-[#30363d] transition-colors"
            title="IDEを閉じてチャットに戻る"
          >
            ✕
          </button>
        </div>
        <div className="text-gray-500 flex flex-col items-center">
          <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" className="mb-4 opacity-50"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
          <p>ファイルを選択するか、AIにコードを生成させてください</p>
        </div>
      </div>
    );
  }

  const current = codeBlocks[Math.min(activeTab, codeBlocks.length - 1)];
  if (!current) return null;

  const blockKey = current.path || current.index.toString();
  const currentCode = edits[blockKey] !== undefined ? edits[blockKey] : current.code;
  const isPreviewable = current.language.toLowerCase() === "markdown" || current.language.toLowerCase() === "md" || current.language.toLowerCase() === "html";

  const handleEditorChange = (value: string | undefined) => {
    if (value !== undefined) {
      setEdits(prev => ({ ...prev, [blockKey]: value }));
    }
  };

  const handleCopy = async () => {
    try {
      const { copyToClipboard } = await import('../utils/clipboard');
      await copyToClipboard(currentCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy", err);
    }
  };

  const handleSave = async () => {
    if (current.path) {
      setIsSaving(true);
      try {
        const res = await apiFetch("/api/workspace/save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            files: [{ path: current.path, content: currentCode }]
          })
        });
        if (res.ok) {
          // Success indicator (could add a toast here)
          setTimeout(() => setIsSaving(false), 500);
        } else {
          alert(`Failed to save: ${current.path}`);
          setIsSaving(false);
        }
      } catch (e) {
        console.error("Save error", e);
        setIsSaving(false);
      }
    } else {
      // ダウンロードフォールバック
      const ext = getExtension(current.language);
      const fileName = `code_${activeTab + 1}${ext}`;
      const blob = new Blob([currentCode], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }
  };

  const handleDownloadWorkspace = async () => {
    try {
      const res = await apiFetch("/api/workspace/download");
      if (!res.ok) throw new Error(`Download failed: ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "workspace.zip";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error(e);
      alert("Failed to download workspace");
    }
  };

  return (
    <>
      <div 
        className="code-panel flex-1 flex flex-col bg-[#0d1117] border-l border-[#30363d] w-full h-full relative"
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#30363d] bg-[#161b22] shrink-0">
          <div className="flex items-center gap-2 truncate">
            <span className="text-sm text-gray-400">📄</span>
            <span className="text-sm font-medium text-gray-200 truncate">
              {current.path ? current.path : "Code"}
            </span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-[#30363d] text-gray-400 shrink-0">
              {normalizeLanguage(current.language)}
            </span>
          </div>
          <div className="flex items-center gap-1 shrink-0 ml-2">
            <button
              onClick={handleDownloadWorkspace}
              className="p-1.5 rounded-md text-blue-400 hover:text-white hover:bg-[#30363d] transition-colors text-sm font-medium"
              title="ワークスペース全体をZIPでダウンロード"
            >
              ⬇ ZIP
            </button>
            <button
              onClick={handleCopy}
              className="p-1.5 rounded-md text-gray-400 hover:text-white hover:bg-[#30363d] transition-colors text-sm"
              title="コピー"
            >
              {copied ? <span className="text-green-400">✓ Copied</span> : <span>📋 Copy</span>}
            </button>
            <button
              onClick={handleSave}
              className="p-1.5 rounded-md text-gray-400 hover:text-white hover:bg-[#30363d] transition-colors text-sm"
              title="ワークスペースに保存"
            >
              {isSaving ? <span className="text-blue-400">Saving...</span> : <span>💾 Save</span>}
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md text-gray-400 hover:text-white hover:bg-[#30363d] transition-colors ml-2"
              title="パネルを閉じる"
            >
              ✕
            </button>
          </div>
        </div>

        {codeBlocks.length > 1 && (
          <div className="flex overflow-x-auto border-b border-[#30363d] bg-[#161b22] shrink-0 scrollbar-hide">
            {codeBlocks.map((block, i) => {
              const bKey = block.path || i.toString();
              const isEdited = edits[bKey] !== undefined && edits[bKey] !== block.code;
              return (
                <button
                  key={i}
                  onClick={() => { setActiveTab(i); setViewMode("edit"); }}
                  className={`px-4 py-2 text-xs whitespace-nowrap border-b-2 transition-colors flex items-center gap-1 ${
                    i === activeTab
                      ? "border-blue-500 text-blue-400 bg-[#0d1117]"
                      : "border-transparent text-gray-500 hover:text-gray-300 hover:bg-[#21262d]"
                  }`}
                >
                  {block.path ? block.path.split('/').pop() : `${normalizeLanguage(block.language)} #${i + 1}`}
                  {isEdited && <span className="w-1.5 h-1.5 rounded-full bg-blue-500 inline-block ml-1"></span>}
                </button>
              );
            })}
          </div>
        )}

        {isPreviewable && (
          <div className="flex items-center px-4 py-1.5 bg-[#161b22] border-b border-[#30363d] shrink-0">
            <div className="flex bg-[#0d1117] rounded-md overflow-hidden border border-[#30363d]">
              <button 
                onClick={() => setViewMode("edit")}
                className={`px-3 py-1 text-xs font-medium transition-colors ${viewMode === "edit" ? "bg-[#30363d] text-white" : "text-gray-400 hover:text-gray-200"}`}
              >
                Code
              </button>
              <button 
                onClick={() => setViewMode("preview")}
                className={`px-3 py-1 text-xs font-medium transition-colors ${viewMode === "preview" ? "bg-[#30363d] text-white" : "text-gray-400 hover:text-gray-200"}`}
              >
                Preview
              </button>
              <button 
                onClick={() => setViewMode("split")}
                className={`px-3 py-1 text-xs font-medium transition-colors hidden md:block ${viewMode === "split" ? "bg-[#30363d] text-white" : "text-gray-400 hover:text-gray-200"}`}
              >
                Split
              </button>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-hidden bg-[#1e1e1e] relative flex flex-col md:flex-row">
          {(viewMode === "edit" || viewMode === "split" || !isPreviewable) && (
            <div className={`h-full ${viewMode === "split" && isPreviewable ? "w-full md:w-1/2 border-b md:border-b-0 md:border-r border-[#30363d]" : "w-full"}`}>
              <Editor
                height="100%"
                language={normalizeLanguage(current.language)}
                theme="vs-dark"
                value={currentCode}
                onChange={handleEditorChange}
                options={{
                  minimap: { enabled: false },
                  fontSize: 14,
                  wordWrap: "on",
                  scrollBeyondLastLine: false,
                  automaticLayout: true,
                  padding: { top: 16 }
                }}
              />
            </div>
          )}

          {(viewMode === "preview" || (viewMode === "split" && isPreviewable)) && isPreviewable && (
            <div className={`h-full overflow-auto bg-white ${viewMode === "split" ? "w-full md:w-1/2 bg-[#0d1117]" : "w-full"}`}>
              {current.language.toLowerCase() === "html" ? (
                <iframe
                  srcDoc={currentCode}
                  title="HTML Preview"
                  className="w-full h-full border-none bg-white"
                  sandbox="allow-scripts"
                />
              ) : (
                <div className="p-6 prose prose-invert max-w-none w-full bg-[#0d1117]">
                  <ReactMarkdown 
                    remarkPlugins={[remarkGfm]}
                    components={{
                      code({node, inline, className, children, ...props}: any) {
                        const match = /language-(\w+)/.exec(className || '')
                        if (!inline && match && match[1] === 'mermaid') {
                          return <Mermaid chart={String(children).replace(/\n$/, '')} />
                        }
                        return !inline ? (
                          <div className="bg-[#161b22] p-4 rounded-md overflow-x-auto border border-[#30363d] my-4">
                            <code className={className} {...props}>{children}</code>
                          </div>
                        ) : (
                          <code className="bg-[#30363d] px-1.5 py-0.5 rounded text-sm text-blue-300" {...props}>{children}</code>
                        )
                      }
                    }}
                  >
                    {currentCode}
                  </ReactMarkdown>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
