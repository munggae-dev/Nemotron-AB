"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { BrowserNotificationSettings } from "@/components/BrowserNotificationSettings";
import { apiGet, apiPatch, type NotificationRow } from "@/lib/api";
import { requestNotificationsUnreadRefresh } from "@/lib/notification-unread";

export default function NotificationsPage() {
  const [rows, setRows] = useState<NotificationRow[]>([]);
  const [unread, setUnread] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [markAllBusy, setMarkAllBusy] = useState(false);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const [list, uc] = await Promise.all([
        apiGet<NotificationRow[]>("/notifications"),
        apiGet<{ count: number }>("/notifications/unread-count"),
      ]);
      setRows(list);
      setUnread(uc.count);
      requestNotificationsUnreadRefresh();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function markRead(id: number) {
    try {
      await apiPatch(`/notifications/${id}/read`);
      await load();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function markAllRead() {
    if (!unread) return;
    setMarkAllBusy(true);
    setErr(null);
    try {
      await apiPatch<{ status: string; updated: number }>("/notifications/read-all");
      await load();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setMarkAllBusy(false);
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="h1">알림</h1>
          <p className="lede">
            {unread !== null ? (
              <>
                읽지 않음 <strong>{unread}</strong>건
              </>
            ) : (
              "불러오는 중…"
            )}
          </p>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
          <button
            type="button"
            className="btn secondary"
            disabled={markAllBusy || !unread}
            onClick={() => void markAllRead()}
          >
            {markAllBusy ? "처리 중…" : "모두 읽기"}
          </button>
          <button type="button" className="btn secondary" onClick={() => void load()} disabled={markAllBusy}>
            새로고침
          </button>
        </div>
      </div>
      <BrowserNotificationSettings />

      {err && <div className="msg err">{err}</div>}
      {rows.length === 0 && !err && <p style={{ color: "var(--on-surface-variant)" }}>알림이 없습니다.</p>}
      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {rows.map((n) => (
          <li key={n.id} className="card" style={{ opacity: n.is_read ? 0.75 : 1, listStyle: "none" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
              <div>
                <span className="badge">{n.type}</span>{" "}
                <strong>{n.title}</strong>
                <div style={{ color: "var(--on-surface-variant)", fontSize: 14, marginTop: 6 }}>{n.message}</div>
                <div style={{ color: "var(--on-surface-variant)", fontSize: 12, marginTop: 6 }}>{n.created_at}</div>
                {n.job_id != null && (
                  <div style={{ marginTop: 10 }}>
                    <Link href={`/jobs/${n.job_id}`}>작업 #{n.job_id}</Link>
                  </div>
                )}
              </div>
              {!n.is_read && (
                <button type="button" className="btn secondary" onClick={() => void markRead(n.id)}>
                  읽음
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
