/**
 * チャット API 連携フック。
 * メッセージの送受信、SSE ストリーミング、会話履歴管理を統合。
 */
import { useState, useCallback, useRef, useEffect } from "react";
import { apiFetch } from "../utils/api";
import { useStreaming } from "./useStreaming";
import type { ChatMessage, SSEEvent } from "../types";

type ChatStatus = "idle" | "thinking" | "searching" | "responding" | "planning_search";

export interface PipelineStage {
  stage: string;
  detail: string;
  status: "pending" | "active" | "done";
}

export function useChat(sessionId: string, onMessageComplete?: () => void) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<ChatStatus>("idle");
  const [streamingContent, setStreamingContent] = useState("");
  const [streamingReasoning, setStreamingReasoning] = useState<string | undefined>();
  const [streamingSources, setStreamingSources] = useState<Array<{title: string, url: string, tier?: number}> | undefined>();
  const [streamingChart, setStreamingChart] = useState<any>(undefined);
  const [pipelineStages, setPipelineStages] = useState<PipelineStage[]>([]);
  const [searchQuery, setSearchQuery] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isFetchingHistory, setIsFetchingHistory] = useState(true);
  const messageIdRef = useRef<number>(0);
  const streamingContentRef = useRef<string>("");
  const streamingReasoningRef = useRef<string | undefined>(undefined);
  const streamingSourcesRef = useRef<Array<{title: string, url: string, tier?: number}> | undefined>(undefined);
  const streamingChartRef = useRef<any>(undefined);
  // メッセージIDのセット（二重保存防止）
  const messageIdSetRef = useRef<Set<string>>(new Set());

  const onMessageCompleteRef = useRef<(() => void) | undefined>(onMessageComplete);
  useEffect(() => {
    onMessageCompleteRef.current = onMessageComplete;
  }, [onMessageComplete]);

  // セッション切り替え時に即座にUIをクリア
  useEffect(() => {
    setMessages([]);
    setSearchQuery(null);
    setStreamingContent("");
    setStreamingReasoning(undefined);
    setStreamingSources(undefined);
    setStreamingChart(undefined);
    setPipelineStages([]);
    streamingReasoningRef.current = undefined;
    streamingSourcesRef.current = undefined;
    streamingChartRef.current = undefined;
    messageIdSetRef.current.clear();
    setError(null);
  }, [sessionId]);

  const handleEvent = useCallback((event: SSEEvent) => {
    switch (event.type) {
      case "status":
        setStatus(event.status as ChatStatus);
        if (event.status === "searching" && event.query) {
          setSearchQuery(event.query);
        }
        if (event.status === "responding") {
          setSearchQuery(null);
        }
        break;

      case "pipeline":
        if (event.stage && event.detail) {
          setPipelineStages(prev => {
            const next = [...prev];
            // 既存の同じステージがあれば更新
            const existingIdx = next.findIndex(p => p.stage === event.stage);
            if (existingIdx >= 0) {
              next[existingIdx] = { ...next[existingIdx], detail: event.detail!, status: "active" };
            } else {
              // 以前のステージはdoneにする
              next.forEach(p => p.status = "done");
              next.push({ stage: event.stage!, detail: event.detail!, status: "active" });
            }
            return next;
          });
        }
        break;

      case "clear_buffer":
        setStreamingContent("");
        streamingContentRef.current = "";
        break;

      case "chunk":
        if (event.content) {
          setStreamingContent((prev) => {
            const next = prev + event.content;
            streamingContentRef.current = next;
            return next;
          });
        }
        break;

      case "reasoning":
        if (event.content) {
          setStreamingReasoning(event.content);
          streamingReasoningRef.current = event.content;
        }
        break;

      case "sources":
        if (event.data && Array.isArray(event.data)) {
          setStreamingSources(event.data);
          streamingSourcesRef.current = event.data;
        }
        break;

      case "chart":
        if (event.data) {
          setStreamingChart(event.data);
          streamingChartRef.current = event.data;
        }
        break;

      case "done":
        // ============================================================
        // 【修正ポイント1】最終コンテンツを確定
        // Explicit empty string from server must NOT fall back to streamed CoT.
        // ============================================================
        const finalContent =
          event.content !== undefined && event.content !== null
            ? event.content
            : streamingContentRef.current;
        const ok = event.ok !== false && !!finalContent.trim();
        const looksFailed =
          !ok ||
          /応答の生成に失敗|フィルタリングされました|出力が空|本文が空|<<<FINAL_ANSWER>>>/.test(
            finalContent
          );

        // バックグラウンド通知: 成功のみ完了、失敗は失敗通知
        import("../utils/notifyComplete")
          .then(({ notifyChatComplete, notifyChatFailed }) => {
            if (looksFailed) return notifyChatFailed(finalContent);
            return notifyChatComplete(finalContent);
          })
          .catch(() => {});
        
        // ============================================================
        // 【修正ポイント2】二重表示防止：メッセージの重複チェック
        // ============================================================
        if (finalContent.trim()) {
          const aiMessage: ChatMessage = {
            id: `ai-${++messageIdRef.current}`,
            role: "assistant",
            content: finalContent,
            timestamp: new Date(),
            reasoning: streamingReasoningRef.current,
            sources: streamingSourcesRef.current,
            chartData: streamingChartRef.current
          };
          
          // 重複チェックを追加（同じ内容のメッセージが既にあれば追加しない）
          setMessages((prev) => {
            const lastMsg = prev[prev.length - 1];
            if (lastMsg && lastMsg.role === "assistant" && lastMsg.content === finalContent) {
              // 同じ内容のメッセージが既にある場合は追加しない
              return prev;
            }
            // ID重複もチェック
            const exists = prev.some(m => m.id === aiMessage.id);
            if (exists) return prev;
            return [...prev, aiMessage];
          });
        } else {
          // 空レスでも失敗であることが分かる1行を残す（トークン浪費の空完了を隠さない）
          const failMsg: ChatMessage = {
            id: `ai-${++messageIdRef.current}`,
            role: "assistant",
            content: "*(⚠️ 応答を画面に出せませんでした。もう一度送ってください)*",
            timestamp: new Date(),
          };
          setMessages((prev) => [...prev, failMsg]);
        }
        
        // ============================================================
        // 【修正ポイント3】ストリーミング状態を遅延クリア（一瞬消え防止）
        // ============================================================
        setTimeout(() => {
          setStreamingContent("");
          streamingContentRef.current = "";
          setStreamingReasoning(undefined);
          setStreamingSources(undefined);
          setStreamingChart(undefined);
          setPipelineStages([]);
          streamingReasoningRef.current = undefined;
          streamingSourcesRef.current = undefined;
          streamingChartRef.current = undefined;
          setStatus("idle");
          setSearchQuery(null);
        }, 0);
        
        if (onMessageCompleteRef.current) {
          onMessageCompleteRef.current();
        }
        break;

      case "error":
        setError(event.message || "An error occurred");
        setStatus("idle");
        setStreamingContent("");
        break;
    }
  }, []);  // 依存配列を空にして再生成を防止（値はrefで追跡）

  const handleError = useCallback((err: Error) => {
    setError(err.message);
    setStatus("idle");
    setStreamingContent("");
  }, []);

  const { startStream, cancelStream } = useStreaming({
    onEvent: handleEvent,
    onError: handleError,
  });

  const sendMessage = useCallback(
    async (content: string, mode: string = "chat", forceSearch: boolean = false) => {
      if (!content.trim() || status !== "idle") return;

      setError(null);

      // ユーザーメッセージを追加
      const userMessage: ChatMessage = {
        id: `user-${++messageIdRef.current}`,
        role: "user",
        content: content.trim(),
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMessage]);

      // SSE ストリーミング開始
      await startStream({
        message: content.trim(),
        session_id: sessionId,
        mode,
        force_search: forceSearch,
      });
    },
    [sessionId, status, startStream]
  );

  const loadHistory = useCallback(async () => {
    setIsFetchingHistory(true);
    try {
      const response = await apiFetch(`/api/history/${sessionId}`);
      if (response.ok) {
        const data = await response.json();
        const loaded: ChatMessage[] = data.messages.map(
          (m: { id: string; role: string; content: string; timestamp: string; reasoning?: string; sources?: any }) => {
            let tsStr = m.timestamp;
            if (typeof tsStr === "string" && !tsStr.endsWith("Z") && !/[+-]\d{2}:\d{2}$/.test(tsStr)) {
              tsStr = tsStr.replace(" ", "T") + "Z";
            }
            return {
              id: m.id,
              role: m.role as "user" | "assistant",
              content: m.content,
              timestamp: new Date(tsStr),
              reasoning: m.reasoning,
              sources: m.sources
            };
          }
        );
        
        // 履歴読み込み時の重複排除（IDベース）
        messageIdSetRef.current.clear();
        const uniqueLoaded = loaded.filter(m => {
          if (messageIdSetRef.current.has(m.id)) return false;
          messageIdSetRef.current.add(m.id);
          return true;
        });
        
        // 履歴読み込み時も重複チェック（内容ベース）
        const uniqueByContent: ChatMessage[] = [];
        const contentSet = new Set<string>();
        for (const msg of uniqueLoaded) {
          const key = `${msg.role}:${msg.content}`;
          if (!contentSet.has(key)) {
            contentSet.add(key);
            uniqueByContent.push(msg);
          }
        }
        
        setMessages(uniqueByContent);
        if (uniqueByContent.length > 0) {
          messageIdRef.current = uniqueByContent.length;
        }
      } else if (response.status === 404) {
        // 新規セッションの場合は空にする
        setMessages([]);
        messageIdSetRef.current.clear();
      }
    } catch (err) {
      console.error("Failed to fetch conversation history:", err);
    } finally {
      setIsFetchingHistory(false);
    }
  }, [sessionId]);

  return {
    messages,
    status,
    streamingContent,
    streamingReasoning,
    streamingSources,
    streamingChart,
    pipelineStages,
    searchQuery,
    error,
    isFetchingHistory,
    sendMessage,
    cancelStream,
    loadHistory,
  };
}