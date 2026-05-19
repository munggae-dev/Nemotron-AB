"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { Theme } from "@/lib/theme";

const items = [
  { href: "/", label: "홈", icon: "home" },
  { href: "/jobs", label: "작업 큐", icon: "dashboard" },
  { href: "/jobs/new", label: "새 검증", icon: "splitscreen" },
  { href: "/notifications", label: "알림", icon: "notifications" },
  { href: "/reports", label: "분석·보고서", icon: "analytics" },
] as const;

type SidebarProps = {
  collapsed: boolean;
  onToggle: () => void;
  theme: Theme;
  onToggleTheme: () => void;
};

export function Sidebar({ collapsed, onToggle, theme, onToggleTheme }: SidebarProps) {
  const isDark = theme === "dark";
  const themeLabel = isDark ? "라이트 모드" : "다크 모드";
  const themeIcon = isDark ? "light_mode" : "dark_mode";
  const pathname = usePathname();

  return (
    <aside className={`sidebar${collapsed ? " sidebar--collapsed" : ""}`} aria-expanded={!collapsed}>
      <div className="sidebar-head">
        {collapsed ? (
          <Link href="/" className="sidebar-brand-mark" title="Nemotron A/B">
            N
          </Link>
        ) : (
          <div className="sidebar-brand">
            <h1>Nemotron A/B</h1>
            <p>A/B 평가</p>
          </div>
        )}
        <button
          type="button"
          className="sidebar-toggle"
          onClick={onToggle}
          aria-label={collapsed ? "사이드바 펼치기" : "사이드바 접기"}
        >
          <span className="material-symbols-outlined" aria-hidden>
            {collapsed ? "chevron_right" : "chevron_left"}
          </span>
        </button>
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
            <Link
              key={href}
              href={href}
              className={`sidebar-link${active ? " active" : ""}`}
              title={collapsed ? label : undefined}
            >
              <span className="material-symbols-outlined" aria-hidden>
                {icon}
              </span>
              <span className="sidebar-link-label">{label}</span>
            </Link>
          );
        })}
      </nav>
      <div className="sidebar-footer">
        <button
          type="button"
          role="switch"
          aria-checked={isDark}
          aria-label={themeLabel}
          className="sidebar-link sidebar-theme-toggle"
          title={collapsed ? themeLabel : undefined}
          onClick={onToggleTheme}
        >
          <span className="material-symbols-outlined" aria-hidden>
            {themeIcon}
          </span>
          <span className="sidebar-link-label">{themeLabel}</span>
          <span className={`sidebar-theme-switch${isDark ? " is-on" : ""}`} aria-hidden />
        </button>
        <span className="sidebar-credit" title="Renew with LLM">
          Renew with LLM
        </span>
      </div>
    </aside>
  );
}
