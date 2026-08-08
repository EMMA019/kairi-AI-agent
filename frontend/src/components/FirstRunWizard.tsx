import { useState, useEffect } from "react";
import { apiFetch } from "../utils/api";
import { useLocale } from "../i18n";

interface FirstRunWizardProps {
  onComplete: () => void;
}

const LLM_SET_FLAGS = [
  "deepseek_api_key_set",
  "openai_api_key_set",
  "anthropic_api_key_set",
  "gemini_api_key_set",
] as const;

/**
 * First run: ask only for a DeepSeek key, verify with ping, then go to chat.
 */
export function FirstRunWizard({ onComplete }: FirstRunWizardProps) {
  const { t } = useLocale();
  const [visible, setVisible] = useState(false);
  const [checking, setChecking] = useState(true);
  const [key, setKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch("/api/settings");
        if (!res.ok) {
          if (!cancelled) setChecking(false);
          return;
        }
        const data = await res.json();
        const hasLlm = LLM_SET_FLAGS.some((f) => data[f] === true);
        if (!cancelled) {
          setVisible(!hasLlm);
          setChecking(false);
        }
      } catch {
        if (!cancelled) setChecking(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (checking || !visible) return null;

  const mapPingError = (code: string, detail?: string) => {
    switch (code) {
      case "invalid_key":
      case "empty":
        return t("firstRun.errorInvalid");
      case "balance":
        return t("firstRun.errorBalance");
      case "rate_limit":
        return t("firstRun.errorRateLimit");
      case "network":
        return t("firstRun.errorNetwork");
      default:
        return t("firstRun.errorUnknown", { detail: (detail || code || "").slice(0, 120) });
    }
  };

  const handleSave = async () => {
    const trimmed = key.trim();
    if (!trimmed) {
      setError(t("firstRun.errorEmpty"));
      return;
    }
    setSaving(true);
    setError("");
    try {
      const pingRes = await apiFetch("/api/settings/ping-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: "deepseek", api_key: trimmed }),
      });
      if (!pingRes.ok) {
        setError(t("firstRun.errorHttp", { status: pingRes.status }));
        return;
      }
      const ping = await pingRes.json();
      if (!ping.ok) {
        setError(mapPingError(ping.error || "unknown", ping.detail));
        return;
      }

      const res = await apiFetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ deepseek_api_key: trimmed }),
      });
      if (!res.ok) {
        setError(t("firstRun.errorHttp", { status: res.status }));
        return;
      }
      setVisible(false);
      onComplete();
    } catch {
      setError(t("firstRun.errorReach"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 backdrop-blur-md">
      <div className="bg-[#0e121a] border border-[#2d3139] rounded-2xl w-full max-w-md mx-4 overflow-hidden shadow-2xl">
        <div className="px-6 py-5 border-b border-[#2d3139] bg-[#141822]/90">
          <p className="text-[11px] font-semibold tracking-wide text-cyan-400/90 uppercase mb-1">
            Kairi
          </p>
          <h2 className="text-lg font-bold text-white leading-snug">
            {t("firstRun.title")}
          </h2>
          <p className="text-xs text-gray-400 mt-2 leading-relaxed">
            {t("firstRun.body")}
          </p>
        </div>

        <div className="p-6 space-y-4">
          <div>
            <label className="block text-xs font-semibold text-gray-300 mb-1.5">
              {t("firstRun.keyLabel")}
            </label>
            <input
              type="password"
              autoFocus
              value={key}
              onChange={(e) => setKey(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleSave();
              }}
              placeholder="sk-..."
              className="w-full bg-[#0b0e14] border border-[#2d3139] rounded-lg px-3.5 py-2.5 text-sm text-gray-100 focus:border-cyan-500 focus:outline-none"
            />
            <p className="text-[11px] text-gray-500 mt-2 leading-relaxed">
              {t("firstRun.keyHint")}{" "}
              <a
                href="https://platform.deepseek.com/"
                target="_blank"
                rel="noreferrer"
                className="text-cyan-400 underline"
              >
                platform.deepseek.com
              </a>
              {t("firstRun.keyHintAfter")}
            </p>
          </div>

          {error && (
            <div className="p-3 rounded-lg bg-red-900/30 border border-red-500/40 text-xs text-red-200">
              {error}
            </div>
          )}

          <button
            type="button"
            disabled={saving}
            onClick={() => void handleSave()}
            className="w-full py-2.5 rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white text-sm font-bold disabled:opacity-50 transition-all"
          >
            {saving ? t("firstRun.verifying") : t("firstRun.save")}
          </button>
        </div>
      </div>
    </div>
  );
}
