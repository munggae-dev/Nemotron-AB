"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { NOTIFICATIONS_UNREAD_REFRESH_EVENT } from "@/lib/notification-unread";

const UNREAD_POLL_MS = 12_000;

const titles: Record<string, string> = {
  "/": "개요",
  "/jobs": "작업 큐",
  "/jobs/new": "새 A/B 평가",
  "/notifications": "알림",
  "/reports": "분석·보고서",
};

function titleForPath(pathname: string): string {
  if (pathname.startsWith("/jobs/") && pathname !== "/jobs/new") {
    return "분석 리포트";
  }
  return titles[pathname] ?? "A/B 평가";
}

export function TopBar() {
  const pathname = usePathname();
  const [unreadCount, setUnreadCount] = useState(0);

  const refreshUnread = useCallback(async () => {
    try {
      const uc = await apiGet<{ count: number }>("/notifications/unread-count");
      setUnreadCount(Math.max(0, Number(uc.count) || 0));
    } catch {
      /* 다음 주기·포커스 시 재시도 */
    }
  }, []);

  useEffect(() => {
    void refreshUnread();
    const onRefresh = () => void refreshUnread();
    const onFocus = () => void refreshUnread();
    window.addEventListener(NOTIFICATIONS_UNREAD_REFRESH_EVENT, onRefresh);
    window.addEventListener("focus", onFocus);
    const id = window.setInterval(() => void refreshUnread(), UNREAD_POLL_MS);
    return () => {
      window.removeEventListener(NOTIFICATIONS_UNREAD_REFRESH_EVENT, onRefresh);
      window.removeEventListener("focus", onFocus);
      window.clearInterval(id);
    };
  }, [refreshUnread, pathname]);

  const hasUnread = unreadCount > 0;

  return (
    <header className="topbar">
      <div className="topbar-left">
        <Link href="/jobs" className="topbar-icon-btn" aria-label="작업 이력">
          <span className="material-symbols-outlined">history</span>
        </Link>
        <h2 className="topbar-heading">{titleForPath(pathname)}</h2>
      </div>
      <div className="topbar-actions">
        <Link
          href="/notifications"
          className="topbar-icon-btn topbar-icon-btn--notify"
          aria-label={hasUnread ? `알림, 읽지 않음 ${unreadCount}건` : "알림"}
        >
          <span className="material-symbols-outlined">notifications</span>
          {hasUnread ? <span className="topbar-notify-dot" aria-hidden /> : null}
        </Link>
      </div>
    </header>
  );
}
