"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const titles: Record<string, string> = {
  "/": "개요",
  "/jobs": "작업 큐",
  "/jobs/new": "캠페인 개요",
  "/notifications": "알림",
  "/reports": "분석·보고서",
};

function titleForPath(pathname: string): string {
  if (pathname.startsWith("/jobs/") && pathname !== "/jobs/new") {
    return "분석 리포트";
  }
  return titles[pathname] ?? "마케팅 검증";
}

export function TopBar() {
  const pathname = usePathname();

  return (
    <header className="topbar">
      <div className="topbar-left">
        <Link href="/jobs" className="topbar-icon-btn" aria-label="작업 이력">
          <span className="material-symbols-outlined">history</span>
        </Link>
        <h2 className="topbar-heading">{titleForPath(pathname)}</h2>
      </div>
      <div className="topbar-actions">
        <Link href="/notifications" className="topbar-icon-btn" aria-label="알림">
          <span className="material-symbols-outlined">notifications</span>
        </Link>
      </div>
    </header>
  );
}
