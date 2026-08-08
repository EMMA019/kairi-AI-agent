import { useState, useEffect } from "react";
import { apiFetch } from "../utils/api";
import {
  ChevronRight,
  ChevronDown,
  Folder,
  FolderOpen,
  FileText,
} from "lucide-react";

export interface FileNode {
  name: string;
  path: string;
  type: "directory" | "file";
  children?: FileNode[];
}

interface FileExplorerProps {
  onFileSelect: (path: string) => void;
  onToggle: () => void; // 開閉用の関数
  refreshTrigger?: any; // 自動更新用のトリガー
  embedded?: boolean; // 親パネル内に埋め込むときヘッダーを隠す
}

const TreeNode = ({
  node,
  level,
  onSelect,
}: {
  node: FileNode;
  level: number;
  onSelect: (path: string) => void;
}) => {
  const [isOpen, setIsOpen] = useState(false);

  const handleClick = () => {
    if (node.type === "directory") {
      setIsOpen(!isOpen);
    } else {
      onSelect(node.path);
    }
  };

  return (
    <>
      <div
        className="flex items-center py-1 hover:bg-[#2a2d2e] cursor-pointer text-[#cccccc] text-sm select-none gap-1"
        style={{ paddingLeft: `${level * 12 + 8}px` }}
        onClick={handleClick}
      >
        {/* 開閉アイコン (ディレクトリのみ) */}
        <div className="w-4 h-4 flex items-center justify-center">
          {node.type === "directory" ? (
            isOpen ? (
              <ChevronDown size={14} />
            ) : (
              <ChevronRight size={14} />
            )
          ) : null}
        </div>

        {/* 種類別アイコン */}
        <div className="w-4 h-4 flex items-center justify-center text-gray-400">
          {node.type === "directory" ? (
            isOpen ? (
              <FolderOpen size={14} />
            ) : (
              <Folder size={14} />
            )
          ) : (
            <FileText size={14} />
          )}
        </div>

        <span className="ml-1">{node.name}</span>
      </div>

      {/* 子ノードの展開 */}
      {node.type === "directory" && isOpen && node.children && (
        <div>
          {node.children.map((child, i) => (
            <TreeNode
              key={i}
              node={child}
              level={level + 1}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </>
  );
};

export function FileExplorer({ onFileSelect, onToggle, refreshTrigger, embedded }: FileExplorerProps) {
  const [tree, setTree] = useState<FileNode[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchTree = async (isSilent = false) => {
    if (!isSilent) setLoading(true);
    try {
      const res = await apiFetch("/api/workspace/tree");
      const data = await res.json();
      setTree(data);
    } catch (e) {
      console.error("Failed to fetch workspace tree", e);
    } finally {
      if (!isSilent) setLoading(false);
    }
  };

  // refreshTrigger（AI出力・チャット更新）が変化した際に即時自動リフレッシュ！
  useEffect(() => {
    fetchTree(tree.length > 0); // 既にデータがあればサイレント更新（ちらつき防止）
  }, [refreshTrigger]);

  // 定期スマートポーリング（3.5秒間隔）＆ウィンドウフォーカス自動検知による常時ライブ同期！
  useEffect(() => {
    fetchTree();
    const interval = setInterval(() => fetchTree(true), 3500);
    const handleFocus = () => fetchTree(true);
    window.addEventListener("focus", handleFocus);
    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", handleFocus);
    };
  }, []);

  return (
    <div
      className={`${
        embedded ? "w-full border-l-0" : "w-64 border-l"
      } h-full flex flex-col bg-[#0d1117] border-[#3c4043] shrink-0`}
    >
      {!embedded && (
        <div className="flex items-center justify-between px-3 py-2 border-b border-[#3c4043]">
          <div className="flex items-center gap-2">
            <button
              onClick={onToggle}
              className="p-1 rounded hover:bg-[#2a2d2e] text-blue-400 transition-colors"
              title="エクスプローラーを閉じる"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
              </svg>
            </button>
            <span className="text-[#cccccc] text-sm font-medium">Workspace</span>
          </div>

          <button
            onClick={() => fetchTree(false)}
            className="text-gray-400 hover:text-white p-1 rounded hover:bg-[#2a2d2e] transition-colors"
            title="Refresh"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
              <path d="M3 3v5h5" />
            </svg>
          </button>
        </div>
      )}
      
      <div className="flex-1 overflow-y-auto py-2">
        {loading ? (
          <div className="px-4 py-2 text-sm text-gray-500">Loading...</div>
        ) : tree.length === 0 ? (
          <div className="px-4 py-2 text-sm text-gray-500">
            No files found.
          </div>
        ) : (
          tree.map((node, i) => (
            <TreeNode key={i} node={node} level={0} onSelect={onFileSelect} />
          ))
        )}
      </div>
    </div>
  );
}