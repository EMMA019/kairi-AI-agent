import { apiFetch } from "../utils/api";

export type MarketToolResult = {
  raw: string;
  parsed: unknown | null;
  error?: string;
};

export async function executeMarketTool(
  name: string,
  params: Record<string, unknown> = {},
): Promise<MarketToolResult> {
  try {
    const res = await apiFetch("/api/tools/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, params }),
    });
    if (!res.ok) {
      const text = await res.text();
      return { raw: text, parsed: null, error: `HTTP ${res.status}` };
    }
    const data = await res.json();
    const raw = typeof data.result === "string" ? data.result : JSON.stringify(data.result ?? data);
    let parsed: unknown | null = null;
    try {
      parsed = JSON.parse(raw);
    } catch {
      parsed = null;
    }
    return { raw, parsed };
  } catch (e) {
    return {
      raw: "",
      parsed: null,
      error: e instanceof Error ? e.message : String(e),
    };
  }
}
