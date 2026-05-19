"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { BrowserNotificationListener } from "@/components/BrowserNotificationListener";
import { Sidebar } from "@/components/Sidebar";
import { TopBar } from "@/components/TopBar";
import { applyTheme, type Theme } from "@/lib/theme";

const SIDEBAR_STORAGE_KEY = "nemotron-sidebar-collapsed";

export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [theme, setTheme] = useState<Theme>("light");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(SIDEBAR_STORAGE_KEY) === "1");
    } catch {
      /* ignore */
    }
    const domDark = document.documentElement.getAttribute("data-theme") === "dark";
    setTheme(domDark ? "dark" : "light");
    setReady(true);
  }, []);

  const toggleSidebar = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_STORAGE_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => {
      const next: Theme = prev === "dark" ? "light" : "dark";
      applyTheme(next);
      return next;
    });
  }, []);

  return (
    <div className={`app-root${collapsed ? " sidebar-is-collapsed" : ""}${ready ? " shell-ready" : ""}`}>
      <BrowserNotificationListener />
      <Sidebar collapsed={collapsed} onToggle={toggleSidebar} theme={theme} onToggleTheme={toggleTheme} />
      <TopBar />
      <div className="main-area">
        <div className="main-inner">{children}</div>
      </div>
    </div>
  );
}
