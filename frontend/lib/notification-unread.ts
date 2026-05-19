/** 상단 알림 벨·목록 등에서 읽지 않음 개수를 동기화할 때 사용합니다. */
export const NOTIFICATIONS_UNREAD_REFRESH_EVENT = "nemotron:notifications-unread-refresh";

export function requestNotificationsUnreadRefresh(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(NOTIFICATIONS_UNREAD_REFRESH_EVENT));
}
