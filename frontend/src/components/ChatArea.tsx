/**
 * ChatArea — 会話表示エリア
 * ユーザー（右寄せ）/ AI（左寄せ）のメッセージ一覧を表示。
 * ストリーミング中のリアルタイム文字追加表示 + 安全なスクロール制御。
 */
import { useEffect, useRef, memo, useState } from "react";
import { TypingIndicator } from "./TypingIndicator";
import { PipelineIndicator } from "./PipelineIndicator";
import { DataChart } from "./DataChart";
import ReactMarkdown from 'react-markdown';
import type { ChatMessage } from "../types";
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { getApiUrl } from "../utils/api";
import { useLocale } from "../i18n";

function StockImage({ src, alt, ...props }: { src?: string; alt?: string; [key: string]: any }) {
  const [failed, setFailed] = useState(false);
  if (failed || !src) {
    return (
      <div className="my-3 max-w-sm rounded-xl overflow-hidden border border-[#3c4043] bg-[#1a1b1e] shadow-lg">
        <div className="px-4 py-8 text-center text-xs text-gray-400">
          画像を読み込めませんでした
        </div>
        {alt && (
          <div className="px-3 py-1.5 text-xs text-gray-500 truncate bg-[#1e1f20] border-t border-[#3c4043]">
            {alt}
          </div>
        )}
      </div>
    );
  }
  return (
    <div className="my-3 max-w-sm rounded-xl overflow-hidden border border-[#3c4043] bg-[#1a1b1e] shadow-lg">
      <img
        src={src}
        alt={alt || "image"}
        className="w-full h-auto object-contain"
        onError={() => setFailed(true)}
        {...props}
      />
      {alt && (
        <div className="px-3 py-1.5 text-xs text-gray-400 truncate bg-[#1e1f20] border-t border-[#3c4043] font-medium flex items-center gap-1.5">
          <span>📸</span>
          <span className="truncate">{alt}</span>
        </div>
      )}
    </div>
  );
}

const markdownComponents: any = {
  img: ({ node, src, alt, ...props }: any) => {
    let resolvedSrc = src;
    if (src && src.startsWith("/api/")) {
      resolvedSrc = getApiUrl(src);
    }
    return (
      <StockImage src={resolvedSrc} alt={alt || "image"} {...props} />
    );
  },
  a: ({ node, href, children, ...props }: any) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-400 hover:text-blue-300 underline underline-offset-4 decoration-blue-400/60 hover:decoration-blue-300 transition-colors inline-flex items-center gap-1 font-medium"
      {...props}
    >
      {children}
      <span className="text-[10px] opacity-75">↗</span>
    </a>
  ),
  code({ node, inline, className, children, ...props }: any) {
    const match = /language-(\w+)/.exec(className || '');
    const { ref, ...rest } = props;
    return !inline && match ? (
      <SyntaxHighlighter
        {...rest}
        PreTag="div"
        language={match[1]}
        style={vscDarkPlus}
        customStyle={{ margin: "0.5em 0", borderRadius: "8px" }}
      >
        {String(children).replace(/\n$/, "")}
      </SyntaxHighlighter>
    ) : (
      <code {...props} className="bg-gray-800 px-1 rounded">{children}</code>
    );
  },
};

interface ChatAreaProps {
  sessionId: string;
  messages: ChatMessage[];
  streamingContent: string;
  status: "idle" | "thinking" | "searching" | "responding" | "planning_search";
  searchQuery: string | null;
  isFetchingHistory: boolean;
  streamingReasoning?: string;
  streamingSources?: Array<{title: string, url: string, tier?: number}>;
  streamingChart?: any;
  pipelineStages?: Array<{stage: string, detail: string, status: "pending" | "active" | "done"}>;
  onSend?: (content: string) => void;
}

// 簡易マークダウンリンク ＆ 添付ファイルパーサー
function renderMessageContent(content: string) {
  if (!content) return { blocks: [], rawContent: "" };

  // リアルタイムAI診断リクエストや長大システム指示を折りたたむ
  if (content.includes("以下の実数値JSONデータに基づく【") && (content.includes("```json:market_data") || content.includes("```json") || content.includes("【重要指示"))) {
    const lines = content.split('\n');
    const firstLine = lines[0] || content;
    const hiddenContent = lines.slice(1).join('\n').trim();
    return {
      blocks: [
        { type: 'text', content: firstLine },
        { type: 'collapsed_prompt', summary: '▶ System Context & Prompt Data (Click to expand)', content: hiddenContent }
      ],
      rawContent: content
    };
  }

  // <file> ブロックをスマートな注釈に置換
  const fileRegex = /<file path="([^"]+)">[\s\S]*?(?:<\/file>|$)/g;
  let cleanContent = content.replace(fileRegex, "\n\n*[📝 Generated file `$1` (Check editor panel on the right)]*\n\n");

  // <replace> ブロックをスマートな注釈に置換
  const replaceRegex = /<replace path="([^"]+)">[\s\S]*?(?:<\/replace>|$)/g;
  cleanContent = cleanContent.replace(replaceRegex, "\n\n*[🔧 Modified file `$1` (Check editor panel on the right)]*\n\n");

  // ツール実行のタグを非表示にする（結果はバックエンドからMarkdownブロックとして追記されているため）
  cleanContent = cleanContent.replace(/<run_command>[\s\S]*?<\/run_command>/g, "");
  cleanContent = cleanContent.replace(/<read_file path="[^"]+"\s*\/>/g, "");
  cleanContent = cleanContent.replace(/<list_dir path="[^"]+"\s*\/>/g, "");
  cleanContent = cleanContent.replace(/<search(?:_news|_codebase)?\s+query="[^"]+"\s*\/>/g, "");

  // AI Judgment の連携用 JSON ブロック（およびフェンス閉じ忘れ・生JSON）を左側チャット表示からスマートに除去し、緑色浸食バグとリンク不全を完全防止
  cleanContent = cleanContent.replace(/```(?:json:ai_judgment|json)?\s*\{[\s\S]*?"judgment"[\s\S]*?\}\s*(?:```)?\s*/g, "");
  cleanContent = cleanContent.replace(/\{\s*"judgment"\s*:\s*(?:\{[\s\S]*?\}|"[^"]+")[\s\S]*?\}\s*/g, "");

  // HTMLタグ漏れ防止（<span class="unconfirmed-badge">[未確認]</span> 等を綺麗なMarkdown装飾へ徹底置換）
  cleanContent = cleanContent.replace(/(?:<|&lt;)span[^>]*class=(?:"|'|&quot;)?[^"'>]*unconfirmed-badge[^"'>]*(?:"|'|&quot;)?[^>]*(?:>|&gt;)\s*\[?未確認\]?\s*(?:<|&lt;)\/span(?:>|&gt;)/gi, "⚠️ **[Unverified]** ");
  cleanContent = cleanContent.replace(/(?:<|&lt;)span[^>]*(?:>|&gt;)([\s\S]*?)(?:<|&lt;)\/span(?:>|&gt;)/gi, "$1");

  const combinedRegex = /(?:<plan>\n?([\s\S]*?)\n?<\/plan>)|(?:<attached_file filename="([^"]+)">[\s\S]*?<\/attached_file>)|(?:<attached_image\s+filename="([^"]+)"\s+mime="([^"]+)">([\s\S]*?)<\/attached_image>)/g;
  
  const blocks: any[] = [];
  let lastIndex = 0;
  let match;

  while ((match = combinedRegex.exec(cleanContent)) !== null) {
    if (match.index > lastIndex) {
      blocks.push({ type: 'text', content: cleanContent.substring(lastIndex, match.index) });
    }
    if (match[1] !== undefined) {
      // matched <plan>
      blocks.push({ type: 'plan', content: match[1] });
    } else if (match[2] !== undefined) {
      // matched <attached_file>
      blocks.push({ type: 'file', filename: match[2] });
    } else if (match[3] !== undefined) {
      // matched <attached_image>
      blocks.push({ type: 'image', filename: match[3], mime: match[4], base64: match[5] });
    }
    lastIndex = combinedRegex.lastIndex;
  }
  
  if (lastIndex < cleanContent.length) {
    blocks.push({ type: 'text', content: cleanContent.substring(lastIndex) });
  }

  return { blocks, rawContent: cleanContent };
}

function renderBlocks(blocks: any[], onSend?: (content: string) => void) {
  return blocks.map((block, i) => {
    if (block.type === 'collapsed_prompt') {
      return (
        <details key={i} className="my-2 text-xs text-gray-400 bg-[#141518] border border-white/5 rounded-lg p-2.5 transition-colors">
          <summary className="cursor-pointer select-none font-medium text-gray-300 hover:text-white transition-colors flex items-center gap-1.5">
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-gray-400">
              <polyline points="16 18 22 12 16 6"></polyline>
              <polyline points="8 6 2 12 8 18"></polyline>
            </svg>
            <span>{block.summary}</span>
          </summary>
          <div className="mt-2 pt-2 border-t border-white/5 opacity-80 max-h-60 overflow-y-auto font-mono text-[11px]">
            <pre className="whitespace-pre-wrap leading-relaxed">{block.content}</pre>
          </div>
        </details>
      );
    }
    if (block.type === 'image') {
      return (
        <div key={i} className="my-2 max-w-sm rounded-lg overflow-hidden border border-[#3c4043] bg-[#1a1b1e]">
          <img 
            src={`data:${block.mime};base64,${block.base64}`} 
            alt={block.filename} 
            className="w-full h-auto object-contain"
          />
          <div className="px-2 py-1 text-xs text-gray-500 truncate bg-[#1e1f20] border-t border-[#3c4043]">
            📎 {block.filename}
          </div>
        </div>
      );
    }
    if (block.type === 'file') {
      return (
        <div key={i} className="my-2 p-3 bg-[#1e1f20] border border-[#3c4043] rounded-lg text-sm flex items-center gap-2 text-blue-400 w-fit max-w-full">
          <span>📎</span> <span className="truncate">{block.filename}</span>
        </div>
      );
    }
    if (block.type === 'plan') {
      return (
        <div key={i} className="my-4 border border-blue-500/30 rounded-lg overflow-hidden bg-blue-500/5">
          <div className="bg-blue-500/10 px-4 py-2 border-b border-blue-500/30 flex items-center gap-2">
            <span className="text-blue-400">📋</span>
            <span className="font-medium text-blue-300">Proposed Implementation Plan</span>
          </div>
          <div className="p-4 prose prose-invert max-w-none prose-sm">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{block.content}</ReactMarkdown>
          </div>
          {onSend && (
            <div className="flex items-center gap-3 p-4 bg-[#1e1f20]/50 border-t border-[#3c4043]">
              <button
                onClick={() => onSend("Approved. Please implement.")}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-md font-medium text-sm transition-colors flex-1"
              >
                ✅ Approve & Start Implementation
              </button>
              <button
                onClick={() => onSend("Please revise the plan because...")}
                className="px-4 py-2 bg-[#30363d] hover:bg-[#3c4043] text-gray-200 rounded-md font-medium text-sm transition-colors flex-1"
              >
                🔄 Request Changes
              </button>
            </div>
          )}
        </div>
      );
    }
    return (
      <ReactMarkdown
        key={i}
        remarkPlugins={[remarkGfm]}
        components={markdownComponents}
      >
        {block.content}
      </ReactMarkdown>
    );
  });
}

export const ChatArea = memo(({
  sessionId: _sessionId,
  messages,
  streamingContent,
  status,
  searchQuery,
  isFetchingHistory,
  streamingReasoning,
  streamingSources,
  streamingChart,
  pipelineStages = [],
  onSend,
}: ChatAreaProps) => {
  const { t } = useLocale();
  // 1. ヘッダーを押し出さないための唯一の解決策：コンテナ自体を直接制御する
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (containerRef.current) {
      // ストリーミング時の連続更新に伴うスマホのスクロール競合・上下激震（Jitter）を完全防止
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [messages, streamingContent, status]);

  // ============================================================
  // 【修正ポイント】重複チェック：streamingContent が messages に既にあるか
  // ============================================================
  const isDuplicate = messages.some(
    m => m.role === "assistant" && m.content === streamingContent
  );
  // ============================================================

  return (
    <div className="chat-area" ref={containerRef} style={{ overflowY: 'auto' }}>
      {isFetchingHistory ? (
        <div className="flex justify-center p-8 text-gray-500 text-sm">Loading history...</div>
      ) : (
        <>
          {messages.map((msg) => {
            return (
              <div key={msg.id} className={`message ${msg.role} animate-fade-in`}>
                <div className="message-bubble">
                  {msg.role === "assistant" && msg.reasoning && (
                    <details className="mb-4 text-xs bg-white/[0.02] border border-white/5 rounded-lg px-3 py-2 transition-colors">
                      <summary className="cursor-pointer select-none text-gray-400 hover:text-gray-200 font-medium flex items-center gap-2">
                        <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-gray-500">
                          <circle cx="12" cy="12" r="10"></circle>
                          <polyline points="12 6 12 12 16 14"></polyline>
                        </svg>
                        <span>Thought process</span>
                      </summary>
                      <div className="mt-2.5 pt-2.5 border-t border-white/5 text-gray-400 whitespace-pre-wrap font-mono leading-relaxed opacity-90 shimmer-text text-[0.8rem]">
                        {msg.reasoning}
                      </div>
                    </details>
                  )}
                  {msg.role === "assistant" && msg.chartData && (
                    <DataChart data={msg.chartData} />
                  )}
                  {msg.role === "assistant" && msg.sources && msg.sources.length > 0 && (
                    <div className="mb-3 text-xs bg-[#1a1b1e] border border-[#3c4043] rounded p-2">
                      <div className="text-gray-400 font-medium mb-1">🔗 Sources:</div>
                      <ul className="list-disc list-inside text-blue-400">
                        {msg.sources.map((s: { title: string; url: string; tier?: number }, idx: number) => (
                          <li key={idx} className="truncate">
                            <a href={s.url} target="_blank" rel="noopener noreferrer" className="hover:underline">
                              {s.title || s.url}
                            </a>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {renderBlocks(renderMessageContent(msg.content).blocks, onSend)}
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <div className="message-time">
                    {msg.timestamp instanceof Date ? msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ""}
                  </div>
                  <button
                    onClick={async () => {
                      const { copyToClipboard } = await import('../utils/clipboard');
                      copyToClipboard(msg.content);
                    }}
                    className="text-xs text-[#8b949e] hover:text-[#c9d1d9] transition-colors flex items-center justify-center p-1 rounded hover:bg-[#30363d]"
                    title="Copy message"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                  </button>
                </div>
              </div>
            );
          })}

          {status === "planning_search" && (
            <div className="search-banner text-gray-400">
              <div className="spinner" />
              <span>{t("status.planningSearch")}</span>
            </div>
          )}

          {status === "searching" && searchQuery && pipelineStages.length === 0 && (
            <div className="search-banner">
              <div className="spinner" />
              <span>{t("status.searchingQuery", { query: searchQuery })}</span>
            </div>
          )}

          {(status === "thinking" || status === "searching" || status === "planning_search" || (status === "responding" && !streamingContent)) && (
            pipelineStages.length > 0 ? (
              <PipelineIndicator stages={pipelineStages} />
            ) : (
              <TypingIndicator status={status} searchQuery={searchQuery} />
            )
          )}

          {/* ============================================================
              【修正ポイント】streamingContent が messages にない場合のみ表示
              ============================================================ */}
          {streamingContent && !isDuplicate && (
            <div className="message assistant animate-fade-in">
              <div className="message-bubble">
                {streamingReasoning && (
                  <details className="mb-4 text-xs bg-white/[0.02] border border-white/5 rounded-lg px-3 py-2 transition-colors" open>
                    <summary className="cursor-pointer select-none text-gray-400 hover:text-gray-200 font-medium flex items-center gap-2">
                      <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-gray-500">
                        <circle cx="12" cy="12" r="10"></circle>
                        <polyline points="12 6 12 12 16 14"></polyline>
                      </svg>
                      <span>{t("status.thinkingProcess")}</span>
                    </summary>
                    <div className="mt-2.5 pt-2.5 border-t border-white/5 text-gray-400 whitespace-pre-wrap font-mono leading-relaxed opacity-90 shimmer-text text-[0.8rem]">
                      {streamingReasoning}
                    </div>
                  </details>
                )}
                {streamingChart && (
                  <DataChart data={streamingChart} />
                )}
                {streamingSources && streamingSources.length > 0 && (
                  <div className="mb-3 text-xs bg-[#1a1b1e] border border-[#3c4043] rounded p-2">
                    <div className="text-gray-400 font-medium mb-1">🔗 Sources:</div>
                    <ul className="list-disc list-inside text-blue-400">
                      {streamingSources.map((s, idx) => (
                        <li key={idx} className="truncate">
                          <a href={s.url} target="_blank" rel="noopener noreferrer" className="hover:underline">
                            {s.title || s.url}
                          </a>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {renderBlocks(renderMessageContent(streamingContent).blocks, onSend)}
                <span
                  style={{
                    display: "inline-block",
                    width: "2px",
                    height: "1em",
                    background: "var(--color-accent-blue)",
                    marginLeft: "2px",
                    animation: "pulse-dot 1s infinite",
                    verticalAlign: "text-bottom",
                  }}
                />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
});