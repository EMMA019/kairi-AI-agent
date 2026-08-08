import { useState, useCallback } from "react";
import { apiFetch } from "../utils/api";
import type { ViolationType } from "../types";

export function useViolation() {
  const [isSubmitting, setIsSubmitting] = useState(false);

  const submitViolation = useCallback(
    async (
      sessionId: string,
      userMessage: string,
      aiResponse: string,
      violationType: ViolationType,
      reason?: string
    ) => {
      setIsSubmitting(true);
      try {
        const response = await apiFetch("/api/log/violation", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionId,
            user_message: userMessage,
            ai_response: aiResponse,
            violation_type: violationType,
            reason,
          }),
        });

        if (!response.ok) {
          throw new Error("Failed to submit violation log");
        }
        return true;
      } catch (error) {
        console.error(error);
        return false;
      } finally {
        setIsSubmitting(false);
      }
    },
    []
  );

  return { submitViolation, isSubmitting };
}
