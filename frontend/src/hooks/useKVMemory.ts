import { useState, useCallback } from "react";
import { apiFetch } from "../utils/api";
import type { KVEntry } from "../types";

export function useKVMemory() {
  const [memories, setMemories] = useState<KVEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchMemories = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiFetch("/api/kv");
      if (!res.ok) throw new Error("Failed to fetch memories");
      const data = await res.json();
      setMemories(data.memories || []);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const deleteMemory = useCallback(async (id: number) => {
    try {
      const res = await apiFetch(`/api/kv/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to delete memory");
      setMemories((prev) => prev.filter((m) => m.id !== id));
      return true;
    } catch (err: any) {
      setError(err.message);
      return false;
    }
  }, []);

  const purgeJunk = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiFetch("/api/kv/purge-junk", { method: "POST" });
      if (!res.ok) throw new Error("Failed to purge junk memories");
      const data = await res.json();
      await fetchMemories();
      return {
        success: Boolean(data?.success),
        deletedCount: Number(data?.deleted_count ?? 0),
        deletedIds: (data?.deleted_ids as number[]) || [],
      };
    } catch (err: any) {
      setError(err.message);
      return { success: false, deletedCount: 0, deletedIds: [] as number[] };
    } finally {
      setIsLoading(false);
    }
  }, [fetchMemories]);

  return { memories, isLoading, error, fetchMemories, deleteMemory, purgeJunk };
}
