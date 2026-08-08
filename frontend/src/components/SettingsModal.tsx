import { useState, useEffect } from "react";
import { apiFetch } from "../utils/api";
import { CHAR_BG_PRESETS, isCharBgUrl } from "../utils/charBackground";
import { getShowAdvancedModes, setShowAdvancedModes } from "../utils/advancedModes";
import { useLocale, setLocaleLocal } from "../i18n";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

interface Settings {
  supervisor_provider: string;
  supervisor_model: string;
  executor_provider: string;
  executor_model: string;
  planner_provider: string;
  planner_model: string;
  user_name?: string;
  user_location?: string;
  persona_style?: string;
  char_profile?: string;
  visual_anchor?: string;
  char_background?: string;
  image_engine?: string;
  cf_account_id?: string;
  cf_api_token?: string;
  locale?: string;
  gemini_api_key?: string;
  anthropic_api_key?: string;
  openai_api_key?: string;
  deepseek_api_key?: string;
  brave_api_key?: string;
  world_news_api_key?: string;
  newsdata_api_key?: string;
  available_providers: string[];
  anthropic_models: string[];
  gemini_models: string[];
  deepseek_models: string[];
  openai_models: string[];
  notify_on_complete?: boolean;
}

export function SettingsModal({ isOpen, onClose }: SettingsModalProps) {
  const { t } = useLocale();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState<"models" | "persona" | "byok" | "system" | "stats">("models");
  const [usageStats, setUsageStats] = useState<any>(null);
  const [cacheStats, setCacheStats] = useState<any>(null);
  const [advancedModes, setAdvancedModes] = useState(getShowAdvancedModes);
  const [appVersion, setAppVersion] = useState<string>("");
  const [exporting, setExporting] = useState(false);
  const [exportSecrets, setExportSecrets] = useState(false);
  const [exportMsg, setExportMsg] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      setAdvancedModes(getShowAdvancedModes());
      setExportMsg(null);
      setLoading(true);
      Promise.all([
        apiFetch("/api/settings").then(res => res.json()),
        apiFetch("/api/usage").then(res => res.json()).catch(() => null),
        apiFetch("/api/stats").then(res => res.json()).catch(() => null),
        apiFetch("/api/version").then(res => res.json()).catch(() => null),
      ]).then(([settingsData, usageData, cacheData, versionData]) => {
        const stored = localStorage.getItem("kairi_notify_on_complete");
        settingsData.notify_on_complete = stored === null ? true : stored !== "false";
        setSettings(settingsData);
        if (usageData) setUsageStats(usageData);
        if (cacheData) setCacheStats(cacheData);
        if (versionData?.version) setAppVersion(versionData.version);
        setLoading(false);
      }).catch(err => {
        console.error(err);
        setLoading(false);
      });
    }
  }, [isOpen]);

  const handleExport = async () => {
    setExporting(true);
    setExportMsg(null);
    try {
      const q = exportSecrets ? "?include_secrets=true" : "";
      const res = await apiFetch(`/api/export${q}`);
      if (!res.ok) {
        setExportMsg(t("settings.exportFail"));
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const cd = res.headers.get("Content-Disposition") || "";
      const m = /filename=\"?([^\";]+)\"?/.exec(cd);
      a.href = url;
      a.download = m?.[1] || "kairi-backup.zip";
      a.click();
      URL.revokeObjectURL(url);
      setExportMsg(t("settings.exportDone"));
    } catch {
      setExportMsg(t("settings.exportFail"));
    } finally {
      setExporting(false);
    }
  };

  if (!isOpen) return null;

  const handleSave = async () => {
    if (!settings) return;
    setSaving(true);
    try {
      await apiFetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          supervisor_provider: settings.supervisor_provider,
          supervisor_model: settings.supervisor_model,
          executor_provider: settings.executor_provider,
          executor_model: settings.executor_model,
          planner_provider: settings.planner_provider,
          planner_model: settings.planner_model,
          user_name: settings.user_name || "Boss",
          user_location: settings.user_location || "",
          persona_style: settings.persona_style || "standard",
          char_profile: settings.char_profile || "",
          visual_anchor: settings.visual_anchor || "",
          char_background: settings.char_background || "",
          image_engine: settings.image_engine || "gallery",
          cf_account_id: settings.cf_account_id || "",
          cf_api_token: settings.cf_api_token || "",
          locale: settings.locale || "en",
          gemini_api_key: settings.gemini_api_key || "",
          anthropic_api_key: settings.anthropic_api_key || "",
          openai_api_key: settings.openai_api_key || "",
          deepseek_api_key: settings.deepseek_api_key || "",
          brave_api_key: settings.brave_api_key || "",
          world_news_api_key: settings.world_news_api_key || "",
          newsdata_api_key: settings.newsdata_api_key || "",
          notify_on_complete: settings.notify_on_complete !== false,
        })
      });
      try {
        const { setNotifyOnCompleteEnabled, ensureNotifyPermission } = await import("../utils/notifyComplete");
        setNotifyOnCompleteEnabled(settings.notify_on_complete !== false);
        if (settings.notify_on_complete !== false) {
          await ensureNotifyPermission();
        }
      } catch {
        /* ignore */
      }
      setLocaleLocal(settings.locale || "en");
      onClose();
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  const getModels = (provider: string) => {
    if (!settings) return [];
    switch (provider) {
      case "anthropic": return settings.anthropic_models || [];
      case "gemini": return settings.gemini_models || [];
      case "deepseek": return settings.deepseek_models || [];
      case "openai": return settings.openai_models || [];
      default: return [];
    }
  };

  const renderSection = (title: string, providerKey: keyof Settings, modelKey: keyof Settings) => {
    if (!settings) return null;
    const provider = settings[providerKey] as string;
    const model = settings[modelKey] as string;
    const models = getModels(provider);

    return (
      <div className="mb-4 bg-[#161a25] p-4 rounded-xl border border-[#2d3139]">
        <h3 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-2 leading-normal">
          {title}
        </h3>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-gray-400 mb-1 leading-normal">{t("settings.provider")}</label>
            <select
              value={provider}
              onChange={(e) => {
                const newProvider = e.target.value;
                const newModels = getModels(newProvider);
                setSettings({ 
                  ...settings, 
                  [providerKey]: newProvider, 
                  [modelKey]: newModels[0] || "" 
                });
              }}
              className="w-full bg-[#0b0e14] border border-[#2d3139] rounded-lg px-3 py-2 text-xs text-gray-200 focus:border-blue-500 focus:outline-none leading-normal"
            >
              {(settings.available_providers || []).map(p => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1 leading-normal">{t("settings.model")}</label>
            {provider === "local" ? (
              <input
                type="text"
                value={model}
                onChange={(e) => setSettings({ ...settings, [modelKey]: e.target.value })}
                placeholder="e.g. llama3, gemma2"
                className="w-full bg-[#0b0e14] border border-[#2d3139] rounded-lg px-3 py-2 text-xs text-gray-200 focus:border-blue-500 focus:outline-none leading-normal"
              />
            ) : (
              <select
                value={model}
                onChange={(e) => setSettings({ ...settings, [modelKey]: e.target.value })}
                className="w-full bg-[#0b0e14] border border-[#2d3139] rounded-lg px-3 py-2 text-xs text-gray-200 focus:border-blue-500 focus:outline-none leading-normal"
              >
                {models.map(m => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            )}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="fixed inset-0 z-[200] bg-black/70 flex items-center justify-center p-4 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-[#0b0e14] border border-[#2d3139] rounded-2xl w-full max-w-xl flex flex-col shadow-2xl overflow-hidden">
        {/* ヘッダー */}
        <div className="flex justify-between items-center px-6 py-4 border-b border-[#2d3139] bg-[#121621]">
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2.5 leading-normal">
              <span>⚙️</span> {t("settings.title")}
            </h2>
            <p className="text-xs text-gray-400 mt-0.5 leading-normal">{t("settings.subtitle")}</p>
          </div>
          <button onClick={onClose} className="p-1.5 text-gray-400 hover:text-white rounded-lg hover:bg-[#1a1f2e] transition-colors">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
        </div>

        {/* タブヘッダー */}
        <div className="flex border-b border-[#2d3139] bg-[#0e121b] px-6 pt-2 gap-1 overflow-x-auto">
          {[
            { id: "models", label: `🤖 ${t("settings.tab.models")}` },
            { id: "persona", label: `🎭 ${t("settings.tab.persona")}` },
            { id: "byok", label: `🔑 ${t("settings.tab.byok")}` },
            { id: "system", label: `🌐 ${t("settings.tab.system")}` },
            { id: "stats", label: `📈 ${t("settings.tab.stats")}` },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`px-4 py-2.5 text-xs font-bold transition-all border-b-2 leading-normal whitespace-nowrap ${
                activeTab === tab.id
                  ? "border-blue-500 text-blue-400 bg-blue-500/10 rounded-t-lg"
                  : "border-transparent text-gray-400 hover:text-gray-200"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        
        {/* タブボディ */}
        <div className="p-6 overflow-y-auto max-h-[60vh] space-y-4">
          {loading ? (
            <div className="text-center py-12 text-gray-400 text-xs font-medium">Loading settings...</div>
          ) : settings ? (
            <>
              {/* タブ 1: 🤖 モデル設定 */}
              {activeTab === "models" && (
                <div className="space-y-4 animate-in fade-in duration-200">
                  {renderSection("🧠 Supervisor Model", "supervisor_provider", "supervisor_model")}
                  {renderSection("🗣️ Executor Model", "executor_provider", "executor_model")}
                  {renderSection("🔍 Planner Model", "planner_provider", "planner_model")}
                  <div className="mt-4 rounded-xl border border-white/10 bg-white/5 p-4">
                    <label className="flex items-center gap-3 cursor-pointer text-sm text-zinc-200">
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-emerald-500"
                        checked={settings.notify_on_complete !== false}
                        onChange={(e) =>
                          setSettings({ ...settings, notify_on_complete: e.target.checked })
                        }
                      />
                      <span>回答完了時に通知（スマホでバックグラウンド中）</span>
                    </label>
                    <p className="mt-2 text-xs text-zinc-500">
                      タブやアプリが裏にあるとき、回答が届いたら通知します。完全なサーバPushではありません。
                    </p>
                  </div>
                </div>
              )}

              {/* タブ 2: 🎭 ペルソナ・応答 */}
              {activeTab === "persona" && (
                <div className="space-y-5 animate-in fade-in duration-200">
                  <div className="bg-[#161a25] p-4 rounded-xl border border-[#2d3139]">
                    <h3 className="text-sm font-semibold text-gray-200 mb-2 flex items-center gap-2 leading-normal">
                      👤 User Salutation (How AI addresses you)
                    </h3>
                    <input
                      type="text"
                      value={settings.user_name || ""}
                      onChange={(e) => setSettings({ ...settings, user_name: e.target.value })}
                      placeholder="e.g. Boss, Master, Nao"
                      className="w-full bg-[#0b0e14] border border-[#2d3139] rounded-lg px-3.5 py-2.5 text-xs text-gray-200 focus:border-blue-500 focus:outline-none leading-normal"
                    />
                    <p className="text-[11px] text-gray-400 mt-2 leading-relaxed">
                      💡 AI will consistently address you by this name across all modes.
                    </p>
                  </div>

                  <div className="bg-[#161a25] p-4 rounded-xl border border-[#2d3139]">
                    <h3 className="text-sm font-semibold text-gray-200 mb-2 flex items-center gap-2 leading-normal">
                      🏠 Home Location / Base City (お出かけ・移動起点の居住地)
                    </h3>
                    <input
                      type="text"
                      value={settings.user_location || ""}
                      onChange={(e) => setSettings({ ...settings, user_location: e.target.value })}
                      placeholder="e.g. 埼玉県久喜市, 東京都渋谷区, Osaka"
                      className="w-full bg-[#0b0e14] border border-[#2d3139] rounded-lg px-3.5 py-2.5 text-xs text-gray-200 focus:border-blue-500 focus:outline-none leading-normal"
                    />
                    <p className="text-[11px] text-gray-400 mt-2 leading-relaxed">
                      💡 Used as default origin for travel, transit routes, and local weather/events without affecting unrelated technical answers.
                    </p>
                  </div>

                  <div className="bg-[#161a25] p-4 rounded-xl border border-[#2d3139]">
                    <h3 className="text-sm font-semibold text-gray-200 mb-2 flex items-center gap-2 leading-normal">
                      🎭 Char Profile (キャラクターカスタム設定)
                    </h3>
                    <textarea
                      value={settings.char_profile || ""}
                      onChange={(e) => setSettings({ ...settings, char_profile: e.target.value })}
                      placeholder="例: あなたはツンデレな幼馴染の女の子「Kairi」です。普段は冷たい態度だけど二人きりだと優しくなります。敬語は禁止です。"
                      rows={5}
                      className="w-full min-h-[100px] bg-[#0b0e14] border border-[#2d3139] rounded-lg p-3 text-xs text-gray-200 focus:border-blue-500 focus:outline-none leading-relaxed resize-y overflow-y-auto"
                    />
                    <p className="text-[11px] text-gray-400 mt-2 leading-relaxed">
                      💡 「🎭 Charモード」を選択中やチャットで `/char` を使った際、この設定になりきって検索なしで爆速即答します！
                    </p>
                  </div>

                  <div className="bg-[#161a25] p-4 rounded-xl border border-[#2d3139]">
                    <h3 className="text-sm font-semibold text-gray-200 mb-2 flex items-center gap-2 leading-normal">
                      📸 Visual Anchor (見た目・自撮り外見呪文)
                    </h3>
                    <textarea
                      value={settings.visual_anchor || ""}
                      onChange={(e) => setSettings({ ...settings, visual_anchor: e.target.value })}
                      placeholder="例: 1girl, anime style, kairi, 19yo japanese cute girl, short magenta bob hair, pink eyes, earrings, high quality, masterpiece"
                      rows={3}
                      className="w-full min-h-[76px] bg-[#0b0e14] border border-[#2d3139] rounded-lg p-3 text-xs text-gray-200 focus:border-blue-500 focus:outline-none leading-relaxed resize-y overflow-y-auto"
                    />
                    <p className="text-[11px] text-gray-400 mt-2 leading-relaxed">
                      💡 自撮り画像は LoRA ストック（gallery）を優先し、クラウド生成時はこの外見トークンで髪・瞳を固定します。
                    </p>
                  </div>

                  <div className="bg-[#161a25] p-4 rounded-xl border border-[#2d3139]">
                    <h3 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-2 leading-normal">
                      🖼️ Char Mode Background (charモード専用チャット背景)
                    </h3>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5 mb-3">
                      {CHAR_BG_PRESETS.map((p) => {
                        const current = settings.char_background || "";
                        const isSelected = current === p.id;
                        return (
                          <button
                            key={p.id || "none"}
                            type="button"
                            onClick={() => setSettings({ ...settings, char_background: p.id })}
                            className={`rounded-lg border text-left overflow-hidden transition-all ${
                              isSelected
                                ? "border-pink-500 shadow-lg shadow-pink-500/10"
                                : "border-[#2d3139] hover:border-gray-500"
                            }`}
                          >
                            <div
                              className="h-10 w-full"
                              style={
                                p.gradient
                                  ? { backgroundImage: p.gradient }
                                  : { background: "#0b0e14" }
                              }
                            />
                            <div className="p-2 bg-[#0b0e14]">
                              <div className={`text-[11px] font-semibold leading-normal ${isSelected ? "text-pink-300" : "text-gray-200"}`}>
                                {p.name}
                              </div>
                              <div className="text-[10px] text-gray-500 leading-normal mt-0.5">{p.desc}</div>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                    <label className="block text-xs text-gray-300 font-semibold mb-1">
                      カスタム画像URL（任意）
                    </label>
                    <input
                      type="text"
                      value={isCharBgUrl(settings.char_background || "") ? settings.char_background : ""}
                      onChange={(e) => setSettings({ ...settings, char_background: e.target.value })}
                      placeholder="例: /api/image/generate?prompt=bedroom または https://..."
                      className="w-full bg-[#0b0e14] border border-[#2d3139] rounded-lg px-3.5 py-2 text-xs text-gray-200 font-mono focus:border-pink-500 focus:outline-none"
                    />
                    <p className="text-[11px] text-gray-400 mt-2 leading-relaxed">
                      💡 🎭 Charモードのチャット画面にだけ適用されます。URLを入れるとプリセットより優先され、暗めのオーバーレイ付きで表示されます。
                    </p>
                  </div>

                  <div className="bg-[#161a25] p-4 rounded-xl border border-[#2d3139]">
                    <h3 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-2 leading-normal">
                      🎨 Image Generation Engine (自撮り画像生成AIモデル)
                    </h3>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-3">
                      {[
                        { id: "gallery", name: "📸 LoRA Curated Gallery", desc: "事前作成LoRAストックから0.01秒表示・顔ブレ0%" },
                        { id: "gallery-hybrid", name: "✨ Hybrid (LoRA+AI)", desc: "8割ストック表示 ＋ 2割リアルタイムAI生成の二刀流" },
                        { id: "cf-flux", name: "🔥 Cloudflare FLUX.1", desc: "オープンソース最高峰 FLUX.1 による圧倒的高画質" },
                        { id: "cf-sdxl", name: "⚡ Cloudflare SDXL", desc: "SDXL Lightning による高品質＆高速生成" },
                        { id: "pollinations", name: "🌟 Pollinations.ai", desc: "無料・APIキー不要の標準画像生成エンジン" },
                      ].map((item) => {
                        const isSelected = (settings.image_engine || "gallery") === item.id;
                        return (
                          <button
                            key={item.id}
                            type="button"
                            onClick={() => setSettings({ ...settings, image_engine: item.id })}
                            className={`p-3 rounded-lg border text-left transition-all ${
                              isSelected
                                ? "bg-blue-600/15 border-blue-500 text-white shadow-lg shadow-blue-500/10"
                                : "bg-[#0b0e14] border-[#2d3139] text-gray-400 hover:border-gray-500 hover:text-gray-200"
                            }`}
                          >
                            <div className="font-semibold text-xs leading-normal">{item.name}</div>
                            <div className="text-[11px] opacity-80 mt-1 leading-relaxed">{item.desc}</div>
                          </button>
                        );
                      })}
                    </div>

                    {(settings.image_engine === "cf-sdxl" || settings.image_engine === "cf-flux") && (
                      <div className="mt-3 pt-3 border-t border-[#2d3139] space-y-3 bg-[#0b0e14]/50 p-3 rounded-lg">
                        <div className="text-xs text-blue-400 font-medium">
                          ⚡ Cloudflare Workers AI 設定（※無料枠対応）
                        </div>
                        <div>
                          <label className="block text-xs text-gray-300 font-semibold mb-1">
                            Cloudflare Account ID
                          </label>
                          <input
                            type="text"
                            value={settings.cf_account_id || ""}
                            onChange={(e) => setSettings({ ...settings, cf_account_id: e.target.value })}
                            placeholder="Cloudflare Account ID"
                            className="w-full bg-[#0b0e14] border border-[#2d3139] rounded-lg px-3.5 py-2 text-xs text-gray-200 font-mono focus:border-blue-500 focus:outline-none"
                          />
                        </div>
                        <div>
                          <label className="block text-xs text-gray-300 font-semibold mb-1">
                            Cloudflare API Token (Workers AI Read/Write 権限付き)
                          </label>
                          <input
                            type="password"
                            value={settings.cf_api_token || ""}
                            onChange={(e) => setSettings({ ...settings, cf_api_token: e.target.value })}
                            placeholder="Cloudflareのダッシュボードで発行したAPIトークン"
                            className="w-full bg-[#0b0e14] border border-[#2d3139] rounded-lg px-3.5 py-2 text-xs text-gray-200 font-mono focus:border-blue-500 focus:outline-none"
                          />
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="bg-[#161a25] p-4 rounded-xl border border-[#2d3139]">
                    <h3 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-2 leading-normal">
                      🎭 Assistant Tone & Persona
                    </h3>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {[
                        {
                          id: "standard",
                          name: "👔 Standard Tone",
                          desc: "Polite, professional standard English for general & business tasks (Default)",
                        },
                        {
                          id: "analyst",
                          name: "📊 Financial Analyst Mode",
                          desc: "Objective data strategist, quantitative grounding & structured market analysis",
                        },
                        {
                          id: "kairi_kansai",
                          name: "🐙 Casual Kairi",
                          desc: "Friendly, reliable engineering partner Kairi with casual tone",
                        },
                        {
                          id: "concise",
                          name: "⚡ Concise Mode",
                          desc: "Zero small talk, minimal word count, direct facts & diffs only",
                        },
                        {
                          id: "hyper_gal",
                          name: "💅 Hyper Gal Lv3 (omous Engine)",
                          desc: "テンションMAX＆極限ギャル文字コンパイラ自動変換モード",
                        },
                      ].map((p) => {
                        const isSelected = (settings.persona_style || "standard") === p.id;
                        return (
                          <button
                            key={p.id}
                            type="button"
                            onClick={() => setSettings({ ...settings, persona_style: p.id })}
                            className={`flex flex-col items-start p-3.5 rounded-xl border transition-all text-left ${
                              isSelected
                                ? "border-blue-500 bg-gradient-to-br from-blue-600/25 to-indigo-600/20 shadow-md shadow-blue-500/10"
                                : "border-[#2d3139] bg-[#0b0e14] hover:border-[#3e4452]"
                            }`}
                          >
                            <span className={`text-xs font-bold leading-normal mb-1 ${isSelected ? "text-blue-300" : "text-gray-200"}`}>
                              {p.name}
                            </span>
                            <span className="text-[11px] text-gray-400 leading-relaxed">
                              {p.desc}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}

              {/* タブ 3: 🔑 BYOK キー設定 */}
              {activeTab === "byok" && (
                <div className="space-y-4 animate-in fade-in duration-200">
                  {/* LLM モデル API キー */}
                  <div className="bg-[#161a25] p-4 rounded-xl border border-[#2d3139]">
                    <h3 className="text-sm font-bold text-white flex items-center gap-2 leading-normal mb-1">
                      🤖 LLM Provider API Keys (BYOK)
                    </h3>
                    <p className="text-xs text-gray-400 leading-relaxed mb-4">
                      Enter your API keys to store them safely on your local machine.
                    </p>

                    <div className="space-y-3">
                      {[
                        { label: "DeepSeek API Key（推奨・必須）", key: "deepseek_api_key", placeholder: "sk-..." },
                        { label: "OpenAI API Key", key: "openai_api_key", placeholder: "sk-proj-..." },
                        { label: "Anthropic API Key", key: "anthropic_api_key", placeholder: "sk-ant-..." },
                        { label: "Google Gemini API Key", key: "gemini_api_key", placeholder: "AIza..." },
                      ].map((item) => (
                        <div key={item.key}>
                          <label className="block text-xs text-gray-300 font-semibold mb-1 leading-normal">
                            {item.label}
                            {(settings as any)[`${item.key}_set`] ? (
                              <span className="ml-2 text-emerald-400 font-normal">設定済み</span>
                            ) : null}
                          </label>
                          <input
                            type="password"
                            value={
                              (settings as any)[item.key] === "********"
                                ? ""
                                : (settings as any)[item.key] || ""
                            }
                            onChange={(e) => setSettings({ ...settings, [item.key]: e.target.value })}
                            placeholder={
                              (settings as any)[`${item.key}_set`]
                                ? "変更する場合のみ新しいキーを入力"
                                : item.placeholder
                            }
                            className="w-full bg-[#0b0e14] border border-[#2d3139] rounded-lg px-3.5 py-2 text-xs text-gray-200 font-mono focus:border-blue-500 focus:outline-none leading-normal"
                          />
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* 検索・ニュース収集 API キー */}
                  <div className="bg-[#161a25] p-4 rounded-xl border border-[#2d3139]">
                    <h3 className="text-sm font-bold text-white flex items-center gap-2 leading-normal mb-1">
                      🔍 Search & News API Keys
                    </h3>
                    <p className="text-xs text-gray-400 leading-relaxed mb-4">
                      Configure external search & news engines like Brave Search or World News.
                    </p>

                    <div className="space-y-3">
                      {[
                        { label: "Brave Search API Key (BRAVE_API_KEY)", key: "brave_api_key", placeholder: "BSAvyU..." },
                        { label: "World News API Key (WORLD_NEWS_API_KEY)", key: "world_news_api_key", placeholder: "caef..." },
                        { label: "NewsData.io API Key (NEWSDATA_API_KEY)", key: "newsdata_api_key", placeholder: "pu..." },
                      ].map((item) => (
                        <div key={item.key}>
                          <label className="block text-xs text-gray-300 font-semibold mb-1 leading-normal">
                            {item.label}
                            {(settings as any)[`${item.key}_set`] ? (
                              <span className="ml-2 text-emerald-400 font-normal">設定済み</span>
                            ) : null}
                          </label>
                          <input
                            type="password"
                            value={
                              (settings as any)[item.key] === "********"
                                ? ""
                                : (settings as any)[item.key] || ""
                            }
                            onChange={(e) => setSettings({ ...settings, [item.key]: e.target.value })}
                            placeholder={
                              (settings as any)[`${item.key}_set`]
                                ? "変更する場合のみ新しいキーを入力"
                                : item.placeholder
                            }
                            className="w-full bg-[#0b0e14] border border-[#2d3139] rounded-lg px-3.5 py-2 text-xs text-gray-200 font-mono focus:border-blue-500 focus:outline-none leading-normal"
                          />
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Cloudflare Workers AI キー */}
                  <div className="bg-[#161a25] p-4 rounded-xl border border-[#2d3139]">
                    <h3 className="text-sm font-bold text-white flex items-center gap-2 leading-normal mb-1">
                      ⚡ Cloudflare Workers AI Keys (画像生成用)
                    </h3>
                    <p className="text-xs text-gray-400 leading-relaxed mb-4">
                      Configure Cloudflare Account ID & API Token for ultra-fast FLUX.1 & SDXL Lightning image generation.
                    </p>
                    <div className="space-y-3">
                      <div>
                        <label className="block text-xs text-gray-300 font-semibold mb-1">
                          Cloudflare Account ID (CF_ACCOUNT_ID)
                        </label>
                        <input
                          type="text"
                          value={settings.cf_account_id || ""}
                          onChange={(e) => setSettings({ ...settings, cf_account_id: e.target.value })}
                          placeholder="Cloudflare Account ID"
                          className="w-full bg-[#0b0e14] border border-[#2d3139] rounded-lg px-3.5 py-2 text-xs text-gray-200 font-mono focus:border-blue-500 focus:outline-none"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-gray-300 font-semibold mb-1">
                          Cloudflare API Token (CF_API_TOKEN)
                        </label>
                        <input
                          type="password"
                          value={settings.cf_api_token || ""}
                          onChange={(e) => setSettings({ ...settings, cf_api_token: e.target.value })}
                          placeholder="Workers AI AI-search/AI-run 権限トークン"
                          className="w-full bg-[#0b0e14] border border-[#2d3139] rounded-lg px-3.5 py-2 text-xs text-gray-200 font-mono focus:border-blue-500 focus:outline-none"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* タブ 5: 📈 System Stats */}
              {activeTab === "stats" && (
                <div className="space-y-4 animate-in fade-in duration-200">
                  <div className="bg-[#161a25] p-4 rounded-xl border border-[#2d3139]">
                    <h3 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-2 leading-normal">
                      💸 Today's API Usage & Budget
                    </h3>
                    {usageStats ? (
                      <div className="space-y-2">
                        <div className="flex justify-between text-xs">
                          <span className="text-gray-400">Total Tokens</span>
                          <span className="text-gray-200 font-mono">{usageStats.total_tokens?.toLocaleString()}</span>
                        </div>
                        <div className="flex justify-between text-xs">
                          <span className="text-gray-400">Estimated Cost</span>
                          <span className="text-blue-400 font-mono font-bold">${usageStats.estimated_cost?.toFixed(4)}</span>
                        </div>
                        <div className="flex justify-between text-xs">
                          <span className="text-gray-400">Daily Budget</span>
                          <span className="text-gray-200 font-mono">${usageStats.daily_budget?.toFixed(2)}</span>
                        </div>
                        
                        <div className="mt-3">
                          <div className="flex justify-between text-xs mb-1">
                            <span className="text-gray-400">Budget Utilization</span>
                            <span className="text-gray-200 font-mono">
                              {((usageStats.estimated_cost / (usageStats.daily_budget || 1)) * 100).toFixed(1)}%
                            </span>
                          </div>
                          <div className="w-full bg-[#0b0e14] rounded-full h-2">
                            <div 
                              className={`h-2 rounded-full ${usageStats.estimated_cost > usageStats.daily_budget * 0.8 ? 'bg-red-500' : 'bg-blue-500'}`}
                              style={{ width: `${Math.min(((usageStats.estimated_cost / (usageStats.daily_budget || 1)) * 100), 100)}%` }}
                            ></div>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="text-xs text-gray-500">Usage data not available.</div>
                    )}
                  </div>

                  <div className="bg-[#161a25] p-4 rounded-xl border border-[#2d3139]">
                    <h3 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-2 leading-normal">
                      ⚡ Cache Statistics
                    </h3>
                    {cacheStats ? (
                      <div className="space-y-3">
                        {Object.entries(cacheStats).map(([table, stat]: [string, any]) => {
                          if (table === "total") return null;
                          const hitRate = stat.hits + stat.entries > 0 ? (stat.hits / (stat.hits + stat.entries)) * 100 : 0;
                          return (
                            <div key={table} className="bg-[#0b0e14] p-3 rounded-lg border border-[#2d3139]">
                              <div className="text-xs font-semibold text-gray-300 mb-2 capitalize">{table.replace('_', ' ')}</div>
                              <div className="grid grid-cols-3 gap-2 text-center">
                                <div>
                                  <div className="text-[10px] text-gray-500">Entries</div>
                                  <div className="text-xs text-gray-200 font-mono">{stat.entries}</div>
                                </div>
                                <div>
                                  <div className="text-[10px] text-gray-500">Hits</div>
                                  <div className="text-xs text-green-400 font-mono">{stat.hits}</div>
                                </div>
                                <div>
                                  <div className="text-[10px] text-gray-500">Hit Rate</div>
                                  <div className="text-xs text-blue-400 font-mono">{hitRate.toFixed(1)}%</div>
                                </div>
                              </div>
                            </div>
                          );
                        })}
                        
                        <div className="mt-2 pt-2 border-t border-[#2d3139]">
                          <div className="flex justify-between items-center">
                            <span className="text-xs font-bold text-gray-300">Total Hit Rate</span>
                            <span className="text-sm font-bold text-blue-400 font-mono">
                              {cacheStats.total?.hits + cacheStats.total?.entries > 0 
                                ? ((cacheStats.total.hits / (cacheStats.total.hits + cacheStats.total.entries)) * 100).toFixed(1) 
                                : "0.0"}%
                            </span>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="text-xs text-gray-500">Cache stats not available.</div>
                    )}
                  </div>
                </div>
              )}

              {/* タブ 4: 🌐 表示・言語 (i18n) */}
              {activeTab === "system" && (
                <div className="space-y-4 animate-in fade-in duration-200">
                  {appVersion && (
                    <div className="text-[11px] text-gray-500 px-1">
                      {t("settings.version", { version: appVersion })}
                    </div>
                  )}
                  <div className="bg-[#161a25] p-4 rounded-xl border border-[#2d3139]">
                    <label className="flex items-start gap-3 cursor-pointer text-sm text-zinc-200">
                      <input
                        type="checkbox"
                        className="mt-0.5 h-4 w-4 accent-cyan-500"
                        checked={advancedModes}
                        onChange={(e) => {
                          const on = e.target.checked;
                          setAdvancedModes(on);
                          setShowAdvancedModes(on);
                        }}
                      />
                      <span>
                        <span className="font-semibold">{t("settings.advancedModes")}</span>
                        <span className="block text-xs text-zinc-500 mt-1 leading-relaxed">
                          {t("settings.advancedModesDesc")}
                        </span>
                      </span>
                    </label>
                  </div>
                  <div className="bg-[#161a25] p-4 rounded-xl border border-[#2d3139] space-y-3">
                    <h3 className="text-sm font-semibold text-gray-200 leading-normal">
                      {t("settings.exportTitle")}
                    </h3>
                    <p className="text-xs text-gray-400 leading-relaxed">{t("settings.exportDesc")}</p>
                    <p className="text-[11px] text-amber-200/80 leading-relaxed">{t("settings.upgradeHint")}</p>
                    <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer">
                      <input
                        type="checkbox"
                        className="accent-cyan-500"
                        checked={exportSecrets}
                        onChange={(e) => setExportSecrets(e.target.checked)}
                      />
                      {t("settings.exportSecrets")}
                    </label>
                    <button
                      type="button"
                      disabled={exporting}
                      onClick={() => void handleExport()}
                      className="px-3 py-2 rounded-lg text-xs font-bold bg-[#21262d] hover:bg-[#30363d] text-white disabled:opacity-50"
                    >
                      {exporting ? t("settings.exporting") : t("settings.exportBtn")}
                    </button>
                    {exportMsg && <p className="text-[11px] text-gray-400">{exportMsg}</p>}
                  </div>
                  <div className="bg-[#161a25] p-4 rounded-xl border border-[#2d3139]">
                    <h3 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-2 leading-normal">
                      🌐 {t("settings.localeTitle")}
                    </h3>
                    <div className="grid grid-cols-2 gap-3">
                      {[
                        { id: "en", name: `🇺🇸 ${t("settings.localeEn")}`, desc: t("settings.localeEnDesc") },
                        { id: "ja", name: `🇯🇵 ${t("settings.localeJa")}`, desc: t("settings.localeJaDesc") },
                      ].map((loc) => {
                        const isSelected = (settings.locale || "en") === loc.id;
                        return (
                          <button
                            key={loc.id}
                            type="button"
                            onClick={() => setSettings({ ...settings, locale: loc.id })}
                            className={`flex flex-col items-start p-3.5 rounded-xl border transition-all text-left ${
                              isSelected
                                ? "border-blue-500 bg-blue-500/15 text-blue-300"
                                : "border-[#2d3139] bg-[#0b0e14] text-gray-400 hover:text-gray-200"
                            }`}
                          >
                            <span className="text-xs font-bold leading-normal">{loc.name}</span>
                            <span className="text-[11px] text-gray-400 leading-normal mt-0.5">{loc.desc}</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="text-center py-12 text-red-400 text-xs">{t("settings.loadFailed")}</div>
          )}
        </div>
        
        {/* フッター */}
        <div className="px-6 py-4 border-t border-[#2d3139] flex justify-between items-center bg-[#121621]">
          <span className="text-[11px] text-gray-500">
            ✓ {t("settings.storedLocal")}
          </span>
          <div className="flex gap-2.5">
            <button 
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-semibold text-gray-300 hover:text-white hover:bg-[#1a1f2e] transition-colors leading-normal"
            >
              {t("settings.cancel")}
            </button>
            <button 
              onClick={handleSave}
              disabled={saving || !settings}
              className="px-5 py-2 rounded-xl text-xs font-bold bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white shadow-lg shadow-blue-600/25 transition-all disabled:opacity-50 active:scale-95 leading-normal"
            >
              {saving ? t("settings.saving") : t("settings.save")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
