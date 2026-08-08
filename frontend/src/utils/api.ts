/**
 * API ベースURL解決と認証付き fetch ラッパー。
 *
 * バックエンドの APITokenMiddleware は api_token / app_pin / KAIRI_API_TOKEN を要求する。
 * <img> 以外の API 呼び出しはここ経由で X-API-Token を付与する。
 */

export const API_TOKEN_STORAGE_KEY = "kairi_api_token";
export const AUTH_REQUIRED_EVENT = "kairi:auth-required";

export const getApiUrl = (path: string): string => {
  const rawBaseUrl = (import.meta.env.VITE_API_BASE_URL || "").trim().replace(/\s+/g, "");
  const cleanBaseUrl = rawBaseUrl.replace(/\/+$/, "");
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  return `${cleanBaseUrl}${cleanPath}`;
};

export function getStoredApiToken(): string {
  try {
    return (localStorage.getItem(API_TOKEN_STORAGE_KEY) || "").trim();
  } catch {
    return "";
  }
}

export function setStoredApiToken(token: string): void {
  try {
    const cleaned = token.trim();
    if (cleaned) {
      localStorage.setItem(API_TOKEN_STORAGE_KEY, cleaned);
    } else {
      localStorage.removeItem(API_TOKEN_STORAGE_KEY);
    }
  } catch {
    // localStorage 不可環境では無視
  }
}

function notifyAuthRequired(path: string): void {
  console.warn(`[apiFetch] 401 Unauthorized: ${path} — API token / PIN の設定が必要です`);
  try {
    window.dispatchEvent(
      new CustomEvent(AUTH_REQUIRED_EVENT, { detail: { path } })
    );
  } catch {
    // ignore
  }
}

/**
 * 認証ヘッダ付き fetch。path は "/api/..." 形式。
 */
export async function apiFetch(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const headers = new Headers(init.headers || {});
  const token = getStoredApiToken();
  if (token && !headers.has("X-API-Token") && !headers.has("Authorization")) {
    headers.set("X-API-Token", token);
  }

  // FormData のときは Content-Type をブラウザに任せる（boundary 付与）
  if (init.body instanceof FormData) {
    headers.delete("Content-Type");
  }

  const response = await fetch(getApiUrl(path), {
    ...init,
    headers,
  });

  if (response.status === 401) {
    notifyAuthRequired(path);
  }

  return response;
}
