import type { NotificationRow } from "@/lib/api";

export const BROWSER_NOTIFY_ENABLED_KEY = "nemotron-browser-notify";
export const BROWSER_NOTIFY_LAST_ID_KEY = "nemotron-notify-last-id";
export const BROWSER_NOTIFY_CHANGE_EVENT = "nemotron-browser-notify-change";

export function emitBrowserNotifyPreferenceChanged(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(BROWSER_NOTIFY_CHANGE_EVENT));
}

export function isBrowserNotificationSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

export function isBrowserNotifyEnabled(): boolean {
  if (!isBrowserNotificationSupported()) return false;
  try {
    return localStorage.getItem(BROWSER_NOTIFY_ENABLED_KEY) === "1";
  } catch {
    return false;
  }
}

export function setBrowserNotifyEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(BROWSER_NOTIFY_ENABLED_KEY, enabled ? "1" : "0");
  } catch {
    /* ignore */
  }
  emitBrowserNotifyPreferenceChanged();
}

export function getLastNotifiedId(): number {
  try {
    const raw = localStorage.getItem(BROWSER_NOTIFY_LAST_ID_KEY);
    const n = raw ? Number(raw) : 0;
    return Number.isFinite(n) && n >= 0 ? n : 0;
  } catch {
    return 0;
  }
}

export function setLastNotifiedId(id: number): void {
  try {
    localStorage.setItem(BROWSER_NOTIFY_LAST_ID_KEY, String(Math.max(0, Math.floor(id))));
  } catch {
    /* ignore */
  }
}

export function baselineLastNotifiedId(rows: NotificationRow[]): void {
  if (rows.length === 0) return;
  const maxId = Math.max(...rows.map((r) => r.id));
  const prev = getLastNotifiedId();
  if (maxId > prev) setLastNotifiedId(maxId);
}

export async function requestBrowserNotificationPermission(): Promise<NotificationPermission> {
  if (!isBrowserNotificationSupported()) return "denied";
  if (Notification.permission === "granted") return "granted";
  if (Notification.permission === "denied") return "denied";
  return Notification.requestPermission();
}

export function showBrowserNotification(row: NotificationRow): void {
  if (!isBrowserNotificationSupported() || Notification.permission !== "granted") return;

  const body = row.message?.trim() || undefined;
  const n = new Notification(row.title, {
    body,
    tag: `nemotron-notification-${row.id}`,
    requireInteraction: row.type === "error",
  });

  n.onclick = () => {
    window.focus();
    n.close();
    if (row.job_id != null) {
      window.location.assign(`/jobs/${row.job_id}`);
    } else {
      window.location.assign("/notifications");
    }
  };
}

export function findUnreadToNotify(rows: NotificationRow[], lastId: number): NotificationRow[] {
  return rows
    .filter((r) => !r.is_read && r.id > lastId)
    .sort((a, b) => a.id - b.id);
}
