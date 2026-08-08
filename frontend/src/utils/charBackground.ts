/**
 * charモード専用の背景設定ユーティリティ。
 * 値はプリセットID（"room" 等）または画像URL（http(s):// か / 始まり）。
 */
import type { CSSProperties } from "react";
import { getApiUrl } from "./api";

export interface CharBgPreset {
  id: string;
  name: string;
  desc: string;
  /** プレビュー・実背景に使う CSS gradient */
  gradient?: string;
}

export const CHAR_BG_PRESETS: CharBgPreset[] = [
  { id: "", name: "なし (Default)", desc: "通常のダークテーマ" },
  {
    id: "room",
    name: "部屋 (Cozy Room)",
    desc: "暖色のくつろぎ空間",
    gradient: "linear-gradient(165deg, #2a1a2e 0%, #1c1126 45%, #0f0a18 100%)",
  },
  {
    id: "beach",
    name: "ビーチ (Sunset)",
    desc: "夕焼けの海辺",
    gradient: "linear-gradient(180deg, #1a1040 0%, #4a1c50 45%, #8c3458 78%, #b85a48 100%)",
  },
  {
    id: "city",
    name: "夜の街 (Neon City)",
    desc: "ネオンの夜景",
    gradient: "linear-gradient(180deg, #050816 0%, #0d1330 55%, #241a52 100%)",
  },
  {
    id: "school",
    name: "教室 (Classroom)",
    desc: "放課後の光",
    gradient: "linear-gradient(180deg, #20232c 0%, #2c2a24 60%, #3a3226 100%)",
  },
  {
    id: "sakura",
    name: "桜 (Sakura)",
    desc: "桜色のたそがれ",
    gradient: "linear-gradient(180deg, #241222 0%, #3a1c33 60%, #4d2440 100%)",
  },
];

export function isCharBgUrl(value: string): boolean {
  return /^https?:\/\//.test(value) || value.startsWith("/");
}

/**
 * charモードのチャットエリアに適用する背景スタイルを返す。
 * 値が空・不明なら undefined（デフォルトテーマのまま）。
 */
export function getCharBackgroundStyle(value: string | undefined): CSSProperties | undefined {
  const v = (value || "").trim();
  if (!v) return undefined;

  if (isCharBgUrl(v)) {
    const url = v.startsWith("/") ? getApiUrl(v) : v;
    return {
      backgroundImage: `linear-gradient(rgba(7,10,22,0.72), rgba(7,10,22,0.84)), url("${url}")`,
      backgroundSize: "cover",
      backgroundPosition: "center top",
      backgroundRepeat: "no-repeat",
    };
  }

  const preset = CHAR_BG_PRESETS.find((p) => p.id === v);
  if (preset?.gradient) {
    return { backgroundImage: preset.gradient };
  }
  return undefined;
}
