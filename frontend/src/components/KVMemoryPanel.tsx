/**
 * KVMemoryPanel — KVメモリの一覧表示パネル
 * 修正: ID非表示、削除確認モーダル、バッジ色改善、削除ボタン常時表示
 */
import { useEffect, useState } from "react";
import { useKVMemory } from "../hooks/useKVMemory";

interface KVMemoryPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

interface DeleteTarget {
  id: number;
  category: string;
  target: string;
  quote: string;
  stance?: string;
  note?: string;
}

export function KVMemoryPanel({ isOpen, onClose }: KVMemoryPanelProps) {
  const { memories, isLoading, error, fetchMemories, deleteMemory, purgeJunk } = useKVMemory();
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [confirmPurge, setConfirmPurge] = useState(false);
  const [purgeBusy, setPurgeBusy] = useState(false);
  const [purgeResult, setPurgeResult] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      fetchMemories();
      setPurgeResult(null);
    }
  }, [isOpen, fetchMemories]);

  const handleDeleteClick = (mem: any) => {
    setDeleteTarget({
      id: mem.id,
      category: mem.category,
      target: mem.summary.target,
      quote: mem.quote,
      stance: mem.summary.stance,
      note: mem.summary.note,
    });
  };

  const handleConfirmDelete = async () => {
    if (deleteTarget) {
      await deleteMemory(deleteTarget.id);
      setDeleteTarget(null);
    }
  };

  const handleConfirmPurge = async () => {
    setPurgeBusy(true);
    try {
      const result = await purgeJunk();
      if (result.success) {
        setPurgeResult(
          result.deletedCount > 0
            ? `ジャンク ${result.deletedCount} 件を削除しました`
            : "削除対象のジャンクはありませんでした"
        );
      } else {
        setPurgeResult("ジャンク削除に失敗しました");
      }
    } finally {
      setPurgeBusy(false);
      setConfirmPurge(false);
    }
  };

  if (!isOpen) return null;

  const getCategoryStyle = (category: string) => {
    switch (category) {
      case "project":
        return "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm";
      case "profile":
        return "bg-blue-500/20 text-blue-300 border border-blue-500/30";
      case "preference":
        return "bg-pink-500/20 text-pink-300 border border-pink-500/30";
      case "rule":
        return "bg-amber-500/20 text-amber-300 border border-amber-500/30";
      case "exclusion":
        return "bg-red-500/20 text-red-300 border border-red-500/30";
      default:
        return "bg-purple-500/20 text-purple-300 border border-purple-500/30";
    }
  };

  return (
    <>
      <div 
        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[150] transition-opacity"
        onClick={onClose}
      />
      <div 
        className="fixed top-0 right-0 h-full w-80 sm:w-96 bg-[#13151a] shadow-2xl z-[200] flex flex-col transform transition-transform animate-slide-left border-l border-white/10"
        style={{
          paddingTop: 'env(safe-area-inset-top)',
          paddingBottom: 'env(safe-area-inset-bottom)'
        }}
      >
        <div className="flex justify-between items-center px-5 py-4 border-b border-white/10 bg-[#17191e] shrink-0">
          <h2 className="text-lg font-semibold text-gray-200 flex items-center gap-2">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a8 8 0 0 1 8 8c0 3.3-2 6.2-5 7.5V20a2 2 0 0 1-2 2h-2a2 2 0 0 1-2-2v-2.5C6 16.2 4 13.3 4 10a8 8 0 0 1 8-8z"/><path d="M12 2v4"/><path d="m4.9 7.5 3.5 2"/><path d="m19.1 7.5-3.5 2"/></svg>
            KV メモリ
          </h2>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setConfirmPurge(true)}
              disabled={isLoading || purgeBusy || memories.length === 0}
              className="text-xs px-2.5 py-1 rounded-md border border-amber-500/40 text-amber-300 hover:bg-amber-500/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              title="ニュース要約・会話メタなど長期記憶に不適切なエントリを一括削除"
            >
              ジャンク一括削除
            </button>
            <button 
              onClick={onClose}
              className="text-gray-400 hover:text-white p-1 rounded-full hover:bg-[#282a2c] transition-colors"
            >
              ✕
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
          {purgeResult && (
            <div className="text-xs text-amber-200/90 bg-amber-500/10 border border-amber-500/30 rounded-md px-3 py-2">
              {purgeResult}
            </div>
          )}
          {isLoading ? (
            <div className="text-center text-gray-400 py-8">読み込み中...</div>
          ) : error ? (
            <div className="text-red-400 text-sm">{error}</div>
          ) : (() => {
            const filteredMemories = memories.filter((mem) => {
              const cat = (mem.category || "").toLowerCase();
              const target = (mem.summary?.target || "").toLowerCase();
              const quote = (mem.quote || "").trim();

              // agreement, pending_plan 等の一過性ステータスは除外
              if (cat === "agreement" || cat === "pending_plan" || target === "pending_plan") {
                return false;
              }
              // 単なる「OK」「GO」「承認します」等の一時的な返答は除外
              if (/^(ok|go|いいね|了解|承認します|承認します。実装してください。|お願いします|続き|はい|うん)$/i.test(quote)) {
                return false;
              }
              return true;
            });

            if (filteredMemories.length === 0) {
              return <div className="text-center text-gray-400 py-8 text-sm">長期的な記憶・設定情報はまだありません</div>;
            }

            return filteredMemories.map((mem) => (
              <div key={mem.id} className="bg-[#282a2c] p-3 rounded-lg border border-[#3c4043] relative">
                {/* 削除ボタン（常時表示） */}
                <button 
                  onClick={() => handleDeleteClick(mem)}
                  className="absolute top-2 right-2 w-5 h-5 flex items-center justify-center rounded-full text-gray-500 hover:text-red-400 hover:bg-red-500/10 transition-colors text-xs"
                  title="削除"
                >
                  ✕
                </button>
                <div className="flex items-center gap-2 mb-2 pr-6">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${getCategoryStyle(mem.category)}`}>
                    {mem.category}
                  </span>
                </div>
                <div className="text-sm text-gray-200 font-medium mb-1">
                  {mem.summary.target}
                  {mem.summary.stance ? (
                    <span className="text-gray-400"> ({mem.summary.stance})</span>
                  ) : mem.summary.note ? (
                    <span className="text-gray-400"> — {mem.summary.note}</span>
                  ) : null}
                </div>
                <div className="text-xs text-gray-400 italic">
                  "{mem.quote}"
                </div>
              </div>
            ))
          })()}
        </div>
      </div>

      {/* ジャンク一括削除確認 */}
      {confirmPurge && (
        <>
          <div
            className="fixed inset-0 bg-black/70 backdrop-blur-sm z-[250]"
            onClick={() => !purgeBusy && setConfirmPurge(false)}
          />
          <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-[260] w-80 sm:w-96 bg-[#17191e] border border-white/10 rounded-2xl shadow-2xl p-5 animate-fade-in">
            <h3 className="text-sm font-semibold text-gray-200 mb-2">ジャンク記憶を一括削除しますか？</h3>
            <p className="text-xs text-gray-400 mb-4 leading-relaxed">
              市場ニュース要約・会話メタ・一時データなど、長期記憶に不適切なエントリだけを削除します。
              「覚えておいて」で保存した保有銘柄などは残します。
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setConfirmPurge(false)}
                disabled={purgeBusy}
                className="flex-1 py-2 text-sm rounded-lg bg-[#282a2c] text-gray-300 hover:bg-[#37393b] border border-[#3c4043] transition-colors disabled:opacity-50"
              >
                キャンセル
              </button>
              <button
                type="button"
                onClick={handleConfirmPurge}
                disabled={purgeBusy}
                className="flex-1 py-2 text-sm rounded-lg bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 border border-amber-500/30 transition-colors disabled:opacity-50"
              >
                {purgeBusy ? "削除中..." : "一括削除する"}
              </button>
            </div>
          </div>
        </>
      )}

      {/* 削除確認モーダル */}
      {deleteTarget && (
        <>
          <div 
            className="fixed inset-0 bg-black/70 backdrop-blur-sm z-[250]"
            onClick={() => setDeleteTarget(null)}
          />
          <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-[260] w-80 sm:w-96 bg-[#17191e] border border-white/10 rounded-2xl shadow-2xl p-5 animate-fade-in">
            <h3 className="text-sm font-semibold text-gray-200 mb-3">この記憶を削除しますか？</h3>
            
            {/* プレビュー */}
            <div className="bg-[#282a2c] p-3 rounded-lg border border-[#3c4043] mb-4 text-sm">
              <div className="mb-2">
                <span className={`text-xs px-2 py-0.5 rounded-full ${getCategoryStyle(deleteTarget.category)}`}>
                  {deleteTarget.category}
                </span>
              </div>
              <div className="text-gray-200 font-medium mb-1">
                {deleteTarget.target}
                {deleteTarget.stance && (
                  <span className="text-gray-400"> ({deleteTarget.stance})</span>
                )}
                {deleteTarget.note && (
                  <span className="text-gray-400"> — {deleteTarget.note}</span>
                )}
              </div>
              <div className="text-xs text-gray-400 italic">
                "{deleteTarget.quote}"
              </div>
            </div>

            {/* ボタン */}
            <div className="flex gap-2">
              <button
                onClick={() => setDeleteTarget(null)}
                className="flex-1 py-2 text-sm rounded-lg bg-[#282a2c] text-gray-300 hover:bg-[#37393b] border border-[#3c4043] transition-colors"
              >
                キャンセル
              </button>
              <button
                onClick={handleConfirmDelete}
                className="flex-1 py-2 text-sm rounded-lg bg-red-500/20 text-red-400 hover:bg-red-500/30 border border-red-500/30 transition-colors"
              >
                削除する
              </button>
            </div>
          </div>
        </>
      )}
    </>
  );
}
