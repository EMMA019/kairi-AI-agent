/**
 * 回答完了通知（タブ/アプリがバックグラウンドのとき）。
 * Web Notification API + Capacitor LocalNotifications（あれば）。
 */
const STORAGE_KEY = "kairi_notify_on_complete";

export function isNotifyOnCompleteEnabled(): boolean {
  const v = localStorage.getItem(STORAGE_KEY);
  if (v === null) return true; // デフォルト ON
  return v !== "false";
}

export function setNotifyOnCompleteEnabled(on: boolean): void {
  localStorage.setItem(STORAGE_KEY, on ? "true" : "false");
}

export async function ensureNotifyPermission(): Promise<boolean> {
  if (!isNotifyOnCompleteEnabled()) return false;
  try {
    const { Capacitor } = await import("@capacitor/core");
    if (Capacitor.isNativePlatform()) {
      try {
        const mod = await import("@capacitor/local-notifications");
        const LocalNotifications = (mod as any).LocalNotifications;
        if (LocalNotifications?.requestPermissions) {
          const perm = await LocalNotifications.requestPermissions();
          return perm?.display === "granted" || perm?.receive === "granted";
        }
      } catch {
        /* package 未導入なら Web へ */
      }
    }
  } catch {
    /* ignore */
  }
  if (typeof window === "undefined" || !("Notification" in window)) return false;
  if (Notification.permission === "granted") return true;
  if (Notification.permission === "denied") return false;
  const p = await Notification.requestPermission();
  return p === "granted";
}

export async function notifyChatComplete(preview: string): Promise<void> {
  if (!isNotifyOnCompleteEnabled()) return;
  // 前面表示中は通知不要
  if (typeof document !== "undefined" && !document.hidden) return;

  const body = (preview || "回答が届きました").replace(/\s+/g, " ").trim().slice(0, 120) || "回答が届きました";
  await _showNotification("Kairi", body);
}

export async function notifyChatFailed(preview?: string): Promise<void> {
  if (!isNotifyOnCompleteEnabled()) return;
  if (typeof document !== "undefined" && !document.hidden) return;
  const body =
    (preview || "生成に失敗したか、本文が空です。もう一度送ってください")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 120) || "生成に失敗しました";
  await _showNotification("Kairi（失敗）", body);
}

async function _showNotification(title: string, body: string): Promise<void> {
  try {
    const { Capacitor } = await import("@capacitor/core");
    if (Capacitor.isNativePlatform()) {
      try {
        const mod = await import("@capacitor/local-notifications");
        const LocalNotifications = (mod as any).LocalNotifications;
        if (LocalNotifications?.schedule) {
          await LocalNotifications.requestPermissions?.();
          await LocalNotifications.schedule({
            notifications: [
              {
                title,
                body,
                id: Date.now() % 100000,
                schedule: { at: new Date(Date.now() + 200) },
              },
            ],
          });
          return;
        }
      } catch {
        /* fall through to Web */
      }
    }
  } catch {
    /* ignore */
  }

  if (typeof window === "undefined" || !("Notification" in window)) return;
  if (Notification.permission === "default") {
    await Notification.requestPermission();
  }
  if (Notification.permission === "granted") {
    try {
      new Notification(title, { body, icon: "/favicon.svg" });
    } catch {
      /* ignore */
    }
  }
}
