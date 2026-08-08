/**
 * SSE ストリーミング受信フック。
 * fetch + ReadableStream で SSE イベントを処理。
 */
import { useCallback, useRef } from "react";
import { apiFetch } from "../utils/api";
import type { SSEEvent } from "../types";

interface UseStreamingOptions {
  onEvent: (event: SSEEvent) => void;
  onError?: (error: Error) => void;
}

export function useStreaming({ onEvent, onError }: UseStreamingOptions) {
  const abortRef = useRef<AbortController | null>(null);

  const startStream = useCallback(
    async (body: Record<string, unknown>) => {
      // 前のストリームがあればキャンセル
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const response = await apiFetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const reader = response.body?.getReader();
        if (!reader) throw new Error("Response body is not readable");

        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // SSE 形式のパース: "data: {...}\n\n"
          const lines = buffer.split("\n\n");
          buffer = lines.pop() || ""; // 最後の不完全な行をバッファに残す

          for (const line of lines) {
            const trimmed = line.trim();
            if (trimmed.startsWith("data: ")) {
              try {
                const data = JSON.parse(trimmed.slice(6)) as SSEEvent;
                onEvent(data);
              } catch {
                // JSON パースエラーは無視
              }
            }
          }
        }
      } catch (error) {
        if ((error as Error).name !== "AbortError") {
          onError?.(error as Error);
        }
      }
    },
    [onEvent, onError]
  );

  const cancelStream = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  return { startStream, cancelStream };
}
