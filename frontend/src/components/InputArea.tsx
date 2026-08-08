/**
 * InputArea — 入力欄 + 送信ボタン + 検索ボタン
 * テキストエリアの自動リサイズ、Enter送信、Shift+Enter改行対応。
 */
import { useState, useRef, useCallback, useEffect, type KeyboardEvent } from "react";
import { apiFetch } from "../utils/api";
import { FileUploadButton } from "./FileUploadButton";
import { useLocale } from "../i18n";

interface InputAreaProps {
  onSend: (message: string, forceSearch?: boolean) => void;
  onStop: () => void;
  status: "idle" | "thinking" | "searching" | "responding" | "planning_search";
}

export function InputArea({ onSend, onStop, status }: InputAreaProps) {
  const { t } = useLocale();
  const [input, setInput] = useState("");
  const [attachedFile, setAttachedFile] = useState<{ filename: string; content: string; mime_type?: string } | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [forceSearchToggle, setForceSearchToggle] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isGenerating = status !== "idle";
  const disabled = isGenerating;

  // テキストエリアの高さ調整関数（同期的に即時リサイズ）
  const adjustHeight = useCallback(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      const nextHeight = Math.min(Math.max(textarea.scrollHeight, 28), 160);
      textarea.style.height = `${nextHeight}px`;
    }
  }, []);

  useEffect(() => {
    adjustHeight();
  }, [input, adjustHeight]);

  const handleSend = useCallback(
    (forceSearch: boolean = false) => {
      if ((!input.trim() && !attachedFile) || disabled || isUploading) return;
      
      let finalMessage = input.trim();
      if (attachedFile) {
        if (attachedFile.mime_type && attachedFile.mime_type.startsWith("image/")) {
          finalMessage = `<attached_image filename="${attachedFile.filename}" mime="${attachedFile.mime_type}">\n${attachedFile.content}\n</attached_image>\n\n${finalMessage}`;
        } else {
          finalMessage = `<attached_file filename="${attachedFile.filename}">\n${attachedFile.content}\n</attached_file>\n\n${finalMessage}`;
        }
      }
      
      onSend(finalMessage, forceSearch || forceSearchToggle);
      setInput("");
      setAttachedFile(null);
      // 高さをリセット
      if (textareaRef.current) {
        textareaRef.current.style.height = "28px";
      }
    },
    [input, attachedFile, disabled, isUploading, forceSearchToggle, onSend]
  );

  const handleFileSelect = async (file: File) => {
    setIsUploading(true);
    setUploadError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      
      const response = await apiFetch("/api/upload", {
        method: "POST",
        body: formData,
      });
      
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Upload failed");
      }
      
      const data = await response.json();
      setAttachedFile({ filename: data.filename, content: data.content, mime_type: data.mime_type });
    } catch (err: any) {
      setUploadError(err.message);
      setTimeout(() => setUploadError(null), 3000);
    } finally {
      setIsUploading(false);
    }
  };

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      // 日本語IMEの変換中（かな漢字変換のEnter確定）は絶対に送信しない
      if (e.nativeEvent.isComposing || e.keyCode === 229) return;

      // スマホ・モバイル・画面幅768px以下のタッチデバイス環境判定
      const isTouchOrMobile =
        /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(
          navigator.userAgent
        ) ||
        (typeof window !== "undefined" &&
          (window.matchMedia("(pointer: coarse)").matches || window.innerWidth <= 768));

      // スマホ・モバイルでは Enter キーは「常に改行」にする（絶対に送信させない）
      if (isTouchOrMobile) {
        return;
      }

      // PCブラウザ: Enter で送信（Shift+Enter で改行）
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  const handlePaste = useCallback((e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    if (disabled || isUploading || attachedFile !== null) return;
    
    const items = e.clipboardData.items;
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.indexOf("image") !== -1) {
        const file = items[i].getAsFile();
        if (file) {
          e.preventDefault();
          const dateStr = new Date().toISOString().replace(/[:.]/g, '-');
          const ext = file.type.split('/')[1] || 'png';
          const newFile = new File([file], `pasted-image-${dateStr}.${ext}`, { type: file.type });
          handleFileSelect(newFile);
          break;
        }
      }
    }
  }, [disabled, isUploading, attachedFile]);

  return (
    <div className="input-area flex-col">
      {/* 添付ファイルプレビュー */}
      {attachedFile && (
        <div className="flex items-center gap-2 mb-2 bg-[#1e2025] w-fit px-3 py-1.5 rounded-lg border border-white/10 text-sm text-gray-200 shadow-sm">
          {attachedFile.mime_type && attachedFile.mime_type.startsWith("image/") ? (
            <img 
              src={`data:${attachedFile.mime_type};base64,${attachedFile.content}`} 
              alt={attachedFile.filename} 
              className="h-8 w-8 object-cover rounded"
            />
          ) : (
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-blue-400 shrink-0">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
            </svg>
          )}
          <span className="truncate max-w-[200px]">{attachedFile.filename}</span>
          <button 
            onClick={() => setAttachedFile(null)}
            className="ml-1 text-gray-500 hover:text-gray-300 transition-colors"
            title="Remove"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
        </div>
      )}
      {/* アップロード中・エラー表示 */}
      {isUploading && <div className="text-xs text-gray-400 mb-2">Uploading...</div>}
      {uploadError && <div className="text-xs text-red-400 mb-2">{uploadError}</div>}
      
      <div className="input-wrapper flex flex-col gap-2 relative bg-[#131825]/80 backdrop-blur-md border border-white/10 rounded-2xl p-3 shadow-lg focus-within:border-purple-500/50 transition-all">
        
        {/* 上段: フル幅テキスト入力 */}
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            // モバイル環境でも文字入力や改行と同時に即時リサイズ
            const el = e.target;
            el.style.height = "auto";
            el.style.height = `${Math.min(Math.max(el.scrollHeight, 28), 160)}px`;
          }}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder={t("input.placeholder")}
          rows={1}
          disabled={disabled || isUploading}
          className="w-full bg-transparent border-none text-gray-100 text-sm md:text-base resize-none outline-none min-h-[28px] max-h-[160px] leading-relaxed"
          id="message-input"
        />

        {/* 下段: ツールバーアクション（左: 添付/検索/現在地、右: 送信） */}
        <div className="flex items-center justify-between w-full pt-1.5 border-t border-white/5">
          <div className="flex items-center gap-1.5 overflow-x-auto scrollbar-hide py-0.5">
            <FileUploadButton 
              onFileSelect={handleFileSelect} 
              disabled={disabled || isUploading || attachedFile !== null} 
            />
            
            <button
              type="button"
              onClick={() => !disabled && setForceSearchToggle(!forceSearchToggle)}
              disabled={disabled}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-all duration-200 border shrink-0 ${
                forceSearchToggle
                  ? "bg-blue-500/15 text-blue-400 border-blue-500/30 shadow-sm"
                  : "bg-transparent text-gray-400 hover:text-gray-300 border-white/5 hover:border-white/10"
              }`}
              title={t("input.searchTitle")}
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="2" y1="12" x2="22" y2="12"></line>
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
              </svg>
              <span>{t("input.search")}</span>
            </button>

            {/* 現在地取得ボタン */}
            <button
              type="button"
              onClick={() => {
                if (disabled || !navigator.geolocation) return;
                navigator.geolocation.getCurrentPosition(
                  (pos) => {
                    const lat = pos.coords.latitude.toFixed(4);
                    const lon = pos.coords.longitude.toFixed(4);
                    const locTag = t("input.locationTag", { lat, lon });
                    setInput((prev) => (prev.includes(locTag) ? prev : locTag + prev));
                  },
                  (err) => {
                    alert(t("input.locationError", { message: err.message }));
                  },
                  { enableHighAccuracy: true, timeout: 8000 }
                );
              }}
              disabled={disabled}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-all duration-200 border bg-transparent text-gray-400 hover:text-emerald-400 border-white/5 hover:border-emerald-500/30 shrink-0"
              title={t("input.locationTitle")}
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
                <circle cx="12" cy="10" r="3"></circle>
              </svg>
              <span>{t("input.location")}</span>
            </button>
          </div>

          {/* 右側: 送信・停止ボタン */}
          <div className="flex items-center gap-1 shrink-0 ml-2">
            {isGenerating ? (
              <button
                className="flex items-center justify-center w-8 h-8 rounded-full bg-red-500 hover:bg-red-400 text-white transition-all"
                onClick={onStop}
                title={t("input.stop")}
              >
                <div className="w-3 h-3 bg-white rounded-sm" />
              </button>
            ) : (
              <button
                className={`flex items-center justify-center w-8 h-8 rounded-full transition-all duration-300 ${
                  input.trim() || attachedFile
                    ? "bg-[#ECECED] text-[#0e0f11] hover:bg-white hover:scale-105 shadow-md"
                    : "bg-black/40 text-gray-500 cursor-not-allowed border border-white/5"
                }`}
                onClick={() => handleSend()}
                disabled={(!input.trim() && !attachedFile) || isUploading}
                title="送信"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
