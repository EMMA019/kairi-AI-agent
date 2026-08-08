import { useState, useEffect } from "react";
import { apiFetch, getStoredApiToken, setStoredApiToken } from "../utils/api";
import { useLocale } from "../i18n";

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function AuthModal({ isOpen, onClose }: AuthModalProps) {
  const { t } = useLocale();
  const [appPin, setAppPin] = useState("");
  const [inputPin, setInputPin] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [inputApiToken, setInputApiToken] = useState("");
  const [statusMsg, setStatusMsg] = useState("");
  const [activeTab, setActiveTab] = useState<"byok" | "pin" | "token" | "audit">("byok");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (isOpen) {
      const stored = getStoredApiToken();
      setInputApiToken(stored);
      setApiToken(stored);
      apiFetch("/api/settings")
        .then((res) => res.json())
        .then((data) => {
          if (data.app_pin_set) setAppPin("********");
          else if (data.app_pin !== undefined) setAppPin(data.app_pin || "");
          if (data.api_token_set) {
            if (!stored) setApiToken("********");
          } else if (data.api_token) {
            setApiToken(data.api_token);
            if (!stored) {
              setStoredApiToken(data.api_token);
              setInputApiToken(data.api_token);
            }
          }
        })
        .catch(console.error);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSavePin = async () => {
    setSaving(true);
    setStatusMsg("");
    try {
      setStoredApiToken(inputPin);
      setInputApiToken(inputPin);
      setApiToken(inputPin);
      const res = await apiFetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          app_pin: inputPin,
        }),
      });
      if (res.status === 401) {
        setStatusMsg("PIN saved locally, but server auth failed. Check that values match.");
        return;
      }
      if (!res.ok) {
        setStatusMsg(`Could not save PIN (HTTP ${res.status}).`);
        return;
      }
      setAppPin(inputPin);
      setStatusMsg(
        inputPin
          ? "PIN lock enabled and synced for client auth."
          : "PIN lock cleared."
      );
    } catch {
      setStatusMsg("PIN saved locally, but the server was unreachable.");
    } finally {
      setSaving(false);
    }
  };

  const handleSaveApiToken = async () => {
    setSaving(true);
    setStatusMsg("");
    try {
      const token = inputApiToken.trim();
      setStoredApiToken(token);
      setApiToken(token);
      const res = await apiFetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          api_token: token,
        }),
      });
      if (res.status === 401) {
        setStatusMsg(
          "Token saved locally, but server auth failed. Use the same value as the server token."
        );
        return;
      }
      if (!res.ok) {
        setStatusMsg(`Could not save API token (HTTP ${res.status}).`);
        return;
      }
      setStatusMsg(
        token
          ? "API token saved. It will be sent with API requests."
          : "API token cleared."
      );
    } catch {
      setStatusMsg("Token saved locally, but the server was unreachable.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md animate-in fade-in duration-200">
      <div className="bg-[#0e121a] border border-[#2d3139] rounded-2xl w-full max-w-xl overflow-hidden shadow-2xl flex flex-col max-h-[85vh]">
        <div className="px-6 py-4.5 border-b border-[#2d3139] flex items-center justify-between bg-[#141822]/90">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center text-lg font-bold shadow-lg shadow-blue-500/20">
              🛡️
            </div>
            <div>
              <h2 className="text-base font-bold text-white leading-normal flex items-center gap-2">
                {t("auth.title")}
                <span className="text-[10px] bg-gradient-to-r from-emerald-500/20 to-teal-500/20 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded-full font-semibold">
                  BYOK
                </span>
              </h2>
              <p className="text-xs text-gray-400 leading-relaxed">
                Your API keys · optional PIN · optional token
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors p-2 rounded-lg hover:bg-[#1e2330]"
          >
            ✕
          </button>
        </div>

        <div className="flex border-b border-[#2d3139] bg-[#0b0e14] px-6 gap-2 pt-2 overflow-x-auto">
          {[
            { id: "byok", label: "API keys (required)" },
            { id: "token", label: "API Token" },
            { id: "pin", label: "PIN lock" },
            { id: "audit", label: "Checklist" },
          ].map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => {
                  setActiveTab(tab.id as typeof activeTab);
                  setStatusMsg("");
                }}
                className={`px-4 py-3 text-xs font-bold transition-all border-b-2 leading-normal whitespace-nowrap ${
                  isActive
                    ? "border-blue-500 text-blue-400 bg-[#141822]"
                    : "border-transparent text-gray-400 hover:text-gray-200"
                }`}
              >
                {tab.label}
              </button>
            );
          })}
        </div>

        <div className="p-6 overflow-y-auto space-y-5">
          {statusMsg && (
            <div className="p-3.5 rounded-xl bg-blue-900/30 border border-blue-500/40 text-xs text-blue-200 font-medium leading-relaxed">
              {statusMsg}
            </div>
          )}

          {activeTab === "byok" && (
            <div className="space-y-4 animate-in fade-in duration-200">
              <div className="bg-[#161a25] p-5 rounded-xl border border-[#2d3139] space-y-3">
                <h3 className="text-sm font-bold text-white leading-normal">
                  BYOK (Bring Your Own Key)
                </h3>
                <p className="text-xs text-gray-400 leading-relaxed">
                  No serial unlock. Chat needs your own LLM API key. Provider usage fees are
                  billed by that provider, not by this app.
                </p>
                <ol className="list-decimal list-inside space-y-2 text-xs text-gray-300 leading-relaxed">
                  <li>
                    Recommended: create a key at{" "}
                    <a
                      href="https://platform.deepseek.com/"
                      target="_blank"
                      rel="noreferrer"
                      className="text-blue-400 underline"
                    >
                      DeepSeek
                    </a>
                  </li>
                  <li>Open the ⚙️ Settings (gear) icon in the bottom-left Activity Bar, then the
                      API Keys tab, and save your DeepSeek key.</li>
                  <li>Optional: Brave Search key improves web search quality</li>
                </ol>
                <p className="text-[11px] text-gray-500 leading-relaxed">
                  Messages go to the LLM/search providers you configure. Data is stored locally
                  in SQLite by default.
                </p>
              </div>
            </div>
          )}

          {activeTab === "token" && (
            <div className="space-y-4 animate-in fade-in duration-200">
              <div className="bg-[#161a25] p-5 rounded-xl border border-[#2d3139]">
                <h3 className="text-sm font-bold text-white mb-2 leading-normal">
                  API Token (LAN exposure, etc.)
                </h3>
                <p className="text-xs text-gray-400 leading-relaxed mb-4">
                  Leave empty for normal desktop use (127.0.0.1 only). If set, use the same value
                  as backend <code className="text-blue-300">api_token</code> /{" "}
                  <code className="text-blue-300">KAIRI_API_TOKEN</code>.
                </p>
                <div className="space-y-3">
                  <div>
                    <label className="block text-xs text-gray-300 font-semibold mb-1.5 leading-normal">
                      API Token {apiToken ? "(set)" : "(not set)"}
                    </label>
                    <input
                      type="password"
                      value={inputApiToken}
                      onChange={(e) => setInputApiToken(e.target.value)}
                      placeholder="Same token as the server"
                      className="w-full bg-[#0b0e14] border border-[#2d3139] rounded-xl px-4 py-3 text-xs text-gray-200 font-mono focus:border-blue-500 focus:outline-none leading-normal"
                    />
                  </div>
                  <button
                    onClick={handleSaveApiToken}
                    disabled={saving}
                    className="w-full mt-2 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-bold rounded-xl transition-all shadow-lg shadow-blue-600/20 disabled:opacity-50"
                  >
                    {saving ? "Saving…" : "Save API Token"}
                  </button>
                </div>
              </div>
            </div>
          )}

          {activeTab === "pin" && (
            <div className="space-y-4 animate-in fade-in duration-200">
              <div className="bg-[#161a25] p-5 rounded-xl border border-[#2d3139]">
                <h3 className="text-sm font-bold text-white mb-2 leading-normal">
                  App unlock PIN
                </h3>
                <p className="text-xs text-gray-400 leading-relaxed mb-4">
                  When set, the PIN is also used for backend auth and synced to the client API
                  token.
                </p>
                <div className="space-y-3">
                  <div>
                    <label className="block text-xs text-gray-300 font-semibold mb-1.5 leading-normal">
                      New PIN (leave empty to clear)
                    </label>
                    <input
                      type="password"
                      value={inputPin}
                      onChange={(e) => setInputPin(e.target.value)}
                      placeholder={appPin ? "PIN is set (type to replace)" : "e.g. 2026"}
                      className="w-full bg-[#0b0e14] border border-[#2d3139] rounded-xl px-4 py-3 text-xs text-gray-200 font-mono focus:border-blue-500 focus:outline-none leading-normal"
                    />
                  </div>
                  <button
                    onClick={handleSavePin}
                    disabled={saving}
                    className="w-full mt-2 py-3 bg-[#1e2330] hover:bg-[#282f40] text-gray-200 text-xs font-bold rounded-xl border border-[#3e4452] transition-all disabled:opacity-50"
                  >
                    {saving ? "Saving…" : "Apply PIN"}
                  </button>
                </div>
              </div>
            </div>
          )}

          {activeTab === "audit" && (
            <div className="space-y-4 animate-in fade-in duration-200">
              <div className="bg-[#161a25] p-5 rounded-xl border border-[#2d3139] space-y-3">
                <h3 className="text-sm font-bold text-white mb-1 leading-normal">
                  Security checklist
                </h3>
                <ul className="space-y-2 text-xs text-gray-300">
                  <li className="p-3 bg-[#0b0e14] rounded-xl border border-[#2d3139]">
                    DeepSeek (or another) API key saved in Settings
                  </li>
                  <li className="p-3 bg-[#0b0e14] rounded-xl border border-[#2d3139]">
                    Do not share settings.json or API keys
                  </li>
                  <li className="p-3 bg-[#0b0e14] rounded-xl border border-[#2d3139]">
                    Set API Token / PIN only if you expose the app on a LAN
                  </li>
                </ul>
              </div>
            </div>
          )}
        </div>

        <div className="px-6 py-4 border-t border-[#2d3139] bg-[#141822]/50 flex justify-end">
          <button
            onClick={onClose}
            className="px-5 py-2.5 rounded-xl bg-[#282f40] hover:bg-[#343c52] text-gray-200 text-xs font-semibold transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
