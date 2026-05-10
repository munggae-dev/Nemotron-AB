"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const items = [
  { href: "/", label: "홈", icon: "home" },
  { href: "/jobs", label: "작업 큐", icon: "dashboard" },
  { href: "/jobs/new", label: "새 검증", icon: "splitscreen" },
  { href: "/notifications", label: "알림", icon: "notifications" },
  { href: "/reports", label: "분석·보고서", icon: "analytics" },
] as const;

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <h1>Nemotron A/B</h1>
        <p>마케팅 검증</p>
      </div>
      <nav className="sidebar-nav" aria-label="주 메뉴">
        {items.map(({ href, label, icon }) => {
          let active = false;
          if (href === "/") active = pathname === "/";
          else if (href === "/jobs/new") active = pathname === "/jobs/new";
          else if (href === "/jobs")
            active = pathname === "/jobs" || /^\/jobs\/\d+$/.test(pathname);
          else active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link key={href} href={href} className={`sidebar-link${active ? " active" : ""}`}>
              <span className="material-symbols-outlined" aria-hidden>
                {icon}
              </span>
              {label}
            </Link>
          );
        })}
      </nav>
      <div className="sidebar-footer">
        <span className="sidebar-link" style={{ cursor: "default", opacity: 0.7 }}>
          <span className="material-symbols-outlined" aria-hidden>
            info
          </span>
          FastAPI + 워커
        </span>
      </div>
    </aside>
  );
}
