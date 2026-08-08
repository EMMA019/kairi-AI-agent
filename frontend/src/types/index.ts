/** チャットアプリの TypeScript 型定義（仕様書 §3-2 準拠） */

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  reasoning?: string;
  sources?: Array<{ title: string; url: string; tier?: number }>;
  chartData?: { type: "bar" | "line" | "pie"; title: string; data: any[] };
}

export interface KVEntry {
  id: number;
  category: "profile" | "preference" | "agreement";
  quote: string;
  summary: {
    target: string;
    stance?: "like" | "dislike" | "conditional";
    note?: string;
  };
}

export type ViolationType =
  | "Unsolicited Proposal"
  | "Unauthorized Memory"
  | "Repeated Questions"
  | "Excessive Praise"
  | "Search Skipped"
  | "Thought Leakage"
  | "Other";

export interface ViolationLog {
  sessionId: string;
  userMessage: string;
  aiResponse: string;
  violationType: ViolationType;
  reason?: string;
  timestamp: Date;
}

/** SSE イベントの型定義 */
export type SSEEventType = "status" | "chunk" | "thinking" | "done" | "error" | "reasoning" | "sources" | "clear_buffer" | "pipeline" | "chart";

export interface SSEEvent {
  type: SSEEventType;
  status?: "thinking" | "searching" | "responding" | "planning_search";
  content?: string;
  query?: string;
  stage?: string;
  detail?: string;
  data?: any;
  message?: string;
  /** false = 空洞完了・失敗。完了通知を出さない */
  ok?: boolean;
}

export interface SessionInfo {
  session_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}
