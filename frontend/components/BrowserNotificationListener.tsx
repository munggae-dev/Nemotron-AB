"use client";

import { useEffect, useRef } from "react";
import { apiGet, type NotificationRow } from "@/lib/api";
import {
  BROWSER_NOTIFY_CHANGE_EVENT,
  findUnreadToNotify,
  getLastNotifiedId,
  isBrowserNotificationSupported,
  isBrowserNotifyEnabled,
  setLastNotifiedId,
  showBrowserNotification,
} from "@/lib/browser-notifications";
import { requestNotificationsUnreadRefresh } from "@/lib/notification-unread";

const POLL_MS = 12_000;
const FETCH_LIMIT = 30;

export function BrowserNotificationListener() {
  const pollingRef = useRef(false);

  useEffect(() => {
    if (!isBrowserNotificationSupported()) return undefined;

    let cancelled = false;

    async function poll() {
      if (cancelled || pollingRef.current) return;
      if (!isBrowserNotifyEnabled() || Notification.permission !== "granted") return;
      pollingRef.current = true;
      try {
        const rows = await apiGet<NotificationRow[]>(`/notifications?limit=${FETCH_LIMIT}`);
        if (cancelled) return;

        let lastId = getLastNotifiedId();
        const pending = findUnreadToNotify(rows, lastId);
        for (const row of pending) {
          if (cancelled) return;
          showBrowserNotification(row);
          lastId = Math.max(lastId, row.id);
        }
        if (lastId > getLastNotifiedId()) {
          setLastNotifiedId(lastId);
        }
        requestNotificationsUnreadRefresh();
      } catch {
        /* 네트워크·API 오류 시 다음 주기에 재시도 */
      } finally {
        pollingRef.current = false;
      }
    }

    void poll();
    const onPrefChange = () => void poll();
    window.addEventListener(BROWSER_NOTIFY_CHANGE_EVENT, onPrefChange);
    const id = window.setInterval(() => void poll(), POLL_MS);
    return () => {
      cancelled = true;
      window.removeEventListener(BROWSER_NOTIFY_CHANGE_EVENT, onPrefChange);
      window.clearInterval(id);
    };
  }, []);

  return null;
}
